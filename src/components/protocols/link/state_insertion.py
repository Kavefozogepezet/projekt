
import numpy as np
from collections import namedtuple, deque
from sortedcontainers import SortedKeyList
from netsquid.protocols import NodeProtocol, ServiceProtocol
from netsquid.qubits.dmtools import DenseDMRepr
from netsquid.qubits import create_qubits, assign_qstate
from netsquid.util.simtools import SECOND, MICROSECOND

from components.hardware.nvcprocessor import NVCProcessor

from .link_base import *


_GenerationRecord = namedtuple('AttemptRecord', ['ready_time', 'tries', 'rec1', 'rec2', 'etgm_id'])
_AttemptRecord = namedtuple('AttemptRecord', ['req_id', 'pos'])


class StateInsertionLocalProxy (LinkBase):
    def __init__ (self, node, partition, parent, name=None):
        super().__init__(node, partition, name)
        self.parent = parent

    def _share_entanglement(self, req):
        [pos] = yield from self._allocate_qubits(1)
        log.info(f'Allocated qubit at {pos}', at=self)
        self.parent.start_attempts(self.node, req.id, pos)
        yield self.await_signal(
            sender=self.parent,
            signal_label=StateInsertionProtocol.ETGM_READY
        )
        gen = self.parent.get_signal_result(StateInsertionProtocol.ETGM_READY, self)
        return EntanglementRecord(pos, gen.etgm_id), gen.tries
    
    def _reset_link(self):
        self.parent.reset(self.node)


class LinkDescriptor:
    def __init__ (self,
        distance,
        qfc_eff, collection_eff, detection_eff,
        init_time, init_fidelity, correction_time,
        L0, T1, T2,
        attenuation=0.2, refractive_index=1.45,
        clk=None
    ):
        travel_time = distance * refractive_index / 3e8 * SECOND
        l = distance / 2
        t = (travel_time + correction_time) / SECOND

        self.clk = (clk if clk is not None 
            else init_time + correction_time + travel_time)
        
        # coefficients
        kap = 1 - np.exp(-l/L0)
        lam = 1 - np.exp(t/T1 - 2*t/T2)
        gam = 1 - np.exp(-t/T1)
        eta = init_fidelity
        
        # state after successful heralding
        A = (eta - 2)**2
        B = (1 - gam)**2 * (2*kap - kap**2)

        dm = np.zeros((4,4), dtype=np.complex128)
        dm[0,0] = dm[3,3] = 2*(1 - gam) - B
        dm[1,1] = 4 * gam + B
        dm[2,2] = B
        dm[0,3] = dm[3,0] =  2 * eta**2 / A * (1-gam) * (1-lam) * (1-kap)**2
        self.dm = dm * 0.25

        # success probability
        self.p = 0.5 * ( qfc_eff * collection_eff * detection_eff
            * 10**(-attenuation*l/10) ) ** 2


class StateInsertionProtocol (LocalProtocol):
    ETGM_READY = 'ETGM_READY'
    _GEN_ADDED = 'GEN_ADDED'
    _NODE_RESET = 'NODE_RESET'
    _PROC_BUSY = 'PROC_BUSY'


    def __init__(self, node1, node2, link_desc,  name=None):
        super().__init__(
            dict(node1=node1, node2=node2), name
        )
        self.add_signal(StateInsertionProtocol._GEN_ADDED)
        self.add_signal(StateInsertionProtocol._NODE_RESET)
        self.add_signal(StateInsertionProtocol.ETGM_READY)
        self.add_signal(StateInsertionProtocol._PROC_BUSY)
        self.node1 = node1
        self.node2 = node2
        self.attempts1 = deque()
        self.attempts2 = deque()
        self.gens = SortedKeyList(key=lambda item: item.ready_time)
        self.link_desc = link_desc
        node1.qmemory.add_busy_subscriber(self._proc_busy_cb)
        node2.qmemory.add_busy_subscriber(self._proc_busy_cb)

    def run(self):
        while True:
            yield self._gen_added_event()
            while len(self.gens) > 0:
                gens = self.gens.pop(0)
                yield from self._handle_generation(gens)

    def _handle_generation(self, gen):
        self.t_gen = gen.ready_time
        self.t_halt = 0
        generated = False
        while not generated:
            start_time = ns.sim_time()
            timer = self._timer_event()
            reset = self._reset_event()
            proc = self._proc_busy_event()

            expr = yield timer | (proc | reset)
            if expr.first_term.value:
                if self.t_halt > 0:
                    self.t_halt = 0
                    log.info('Generation resumed', at=self)
                else:
                    self._insert_state(gen)
                    self.node1.qmemory.register_usage('state_insertion', start_time, self.t_gen)
                    self.node2.qmemory.register_usage('state_insertion', start_time, self.t_gen)
                    generated = True
            elif expr.second_term.first_term.value:
                delta_t = ns.sim_time() - start_time
                if self.t_halt > 0:
                    self.t_halt -= delta_t
                else:
                    self.node1.qmemory.register_usage('state_insertion', start_time, delta_t)
                    self.node2.qmemory.register_usage('state_insertion', start_time, delta_t)
                    self.t_gen -= delta_t

                if self.node1.qmemory.busy:
                    busy_proc = self.node1.qmemory
                elif self.node2.qmemory.busy:
                    busy_proc = self.node2.qmemory
                else:
                    raise ValueError('Received false PROC_BUSY signal')
                
                t_prog = busy_proc.sequence_end_time - ns.sim_time()
                self.t_halt = max(self.t_halt, t_prog)
                log.info(f'Halting for {self.t_halt/MICROSECOND} us, {busy_proc.name} is busy', at=self)
            else:
                self.gens.clear()
                break


    def _gen_added_event(self):
        return self.await_signal(
            sender=self,
            signal_label=StateInsertionProtocol._GEN_ADDED
        )
    
    def _timer_event(self):
        if self.t_halt > 0:
            return self.await_timer(max(self.t_halt, 0))
        else:
            return self.await_timer(max(self.t_gen, 0))
    
    def _proc_busy_event(self):
        return self.await_signal(
            sender=self,
            signal_label=StateInsertionProtocol._PROC_BUSY
        )
    
    def _reset_event(self):
        return self.await_signal(
            sender=self,
            signal_label=StateInsertionProtocol._NODE_RESET
        )

    def node_protocols(self, part1=None, part2=None):
        return (
            StateInsertionLocalProxy(self.node1, part1, self, name=f'{self.node1.name}LINK'),
            StateInsertionLocalProxy(self.node2, part2, self, name=f'{self.node2.name}LINK')
        )
    
    def start_attempts(self, node, req_id, pos):
        rec1 = _AttemptRecord(req_id, pos)
        if node == self.node1:
            if len(self.attempts2) > 0:
                rec2 = self.attempts2.popleft()
                self._add_generation_record(rec1, rec2)
            else:
                self.attempts1.append(rec1)
        elif node == self.node2:
            if len(self.attempts1) > 0:
                rec2 = self.attempts1.popleft()
                self._add_generation_record(rec2, rec1)
            else:
                self.attempts2.append(rec1)
        else:
            raise ValueError(f'Node {node} is not part of this link')

    def reset(self, node):
        self.gens.clear()
        if node == self.node1:
            self.attempts1.clear()
        elif node == self.node2:
            self.attempts2.clear()
        else:
            raise ValueError(f'Node {node} is not part of this link')
        self.send_signal(StateInsertionProtocol._NODE_RESET)

    def _add_generation_record(self, rec1, rec2):
        # TODO proper implementation of overflow protection (*0.999)
        link = self.link_desc
        u = np.random.rand()*0.999
        tries = np.ceil( np.log(1-u) / np.log(1-link.p) )
        ready_time = tries * self.link_desc.clk

        gen = _GenerationRecord(ready_time, int(tries), rec1, rec2, etgmid('link'))
        self.gens.add(gen)
        self.send_signal(StateInsertionProtocol._GEN_ADDED)

    def _insert_state(self, gen):
        dm = np.copy(self.link_desc.dm)
        repr = DenseDMRepr(dm=dm)
        qubits = create_qubits(2)
        assign_qstate(qubits, repr)

        self.node1.qmemory.put(qubits[0], [gen.rec1.pos])
        self.node2.qmemory.put(qubits[1], [gen.rec2.pos])

        self.send_signal(
            StateInsertionProtocol.ETGM_READY,
            result=gen
        )
        log.info(f'State inserted into {gen.rec1.pos}@{self.node1.name} and {gen.rec2.pos}@{self.node2.name}', at=self)

    def _proc_busy_cb(self):
        self.send_signal(StateInsertionProtocol._PROC_BUSY)
