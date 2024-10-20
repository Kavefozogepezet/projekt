
import numpy as np
from netsquid.qubits.kettools import KetRepr
from netsquid.qubits import ketstates
from netsquid.components.instructions import \
    INSTR_INIT, INSTR_CNOT, INSTR_H, INSTR_X, INSTR_Z

from ..util import *
from .physical_layer import PhysicalLayer
from simlog import log
from .bsa_protocol import BSAProtocol
from components.hardware import program_function, ProgramPriority


class SwapWithBSAProtocol (PhysicalLayer):
    def __init__(self, node, clock, qport, cport, collection_eff=1, qfc_eff=1, name=None) -> None:
        super().__init__(node, name)
        self.clock = clock
        self.qport_name = qport
        self.cport_name = cport
        self.coll_eff = collection_eff
        self.qfc_eff = qfc_eff

    def _attempt_entanglement(self, req):
        qout = self.node.ports[self.qport_name]
        cin = self.node.ports[self.cport_name]
        mem = self.node.qmemory

        yield self.await_signal(
            sender=self.clock,
            signal_label=Clock.TICK
        )

        qubits = [pos, _] = [req.position, mem.photon_pos()]
        yield from self.prepare_bell_state(qubits)

        [coll, qfc] = np.random.rand(2)
        if coll > self.coll_eff:
            log.info(f'Collection of photon failed', at=self)
        elif qfc > self.qfc_eff:
            log.info(f'Frequency conversion failed', at=self)
        else:
            [photon] = mem.pop_photon()
            qout.tx_output(photon)
            log.info(f'Sent photon', outof=self)

        yield self.await_port_input(cin)
        msg = cin.rx_input(header=PhysicalLayer.MSG_HEADER)
        if not msg: return
        
        log.info(f'Received: {log.msg2str(msg.items)}', into=self)
        result = msg.items[0]
        if result == BSAProtocol.SUCCESS:
            data = msg.items[1]
            yield from self.execute_correction([pos], cX=data['cX'], cZ=data['cZ'])
            [q] = self.node.qmemory.peek(pos)
            correct = KetRepr(ket=ketstates.b00)
            fidelity = q.qstate.qrepr.fidelity(correct)
            req.answare(result=PhysicalLayer.SUCCESS, position=pos, etgm_id=data['id'])
            log.info(f'Entanglement swapping successful, fidelity: {fidelity}', at=self)
        else:
            req.answare(result=PhysicalLayer.FAILURE)
            log.info(f'Entanglement swapping failed', into=self)
            
    @program_function(2, ProgramPriority.REAL_TIME)
    def prepare_bell_state(self, prog, qubits):
        [q1, q2] = qubits
        prog.apply(INSTR_INIT, [q1])
        prog.apply(INSTR_INIT, [q2])
        prog.apply(INSTR_H, q1)
        prog.apply(INSTR_CNOT, [q1, q2])

    @program_function(1, ProgramPriority.REAL_TIME)
    def execute_correction(self, prog, qubits, cX=False, cZ=False):
        [q] = qubits
        if cX: prog.apply(INSTR_X, q)
        if cZ: prog.apply(INSTR_Z, q)
