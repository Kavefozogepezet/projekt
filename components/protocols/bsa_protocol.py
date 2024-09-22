
import netsquid as ns
from enum import Enum
from netsquid.protocols import NodeProtocol
from netsquid.qubits.kettools import KetRepr
from netsquid.qubits import ketstates
from netsquid.components.instructions import \
    INSTR_INIT, INSTR_CNOT, INSTR_H, INSTR_X, INSTR_Z

from .util import *
from .protocol_stack import PhysicalLayer


class BSAState (Enum):
    WAITING_TICK = 'BSAState.WAITING_TICK',
    WAITING_OFFSET = 'BSAState.WAITING_OFFSET',
    WAITING_PHOTON_1 = 'BSAState.WAITING_PHOTON_1'
    WAITING_PHOTON_2 = 'BSAState.WAITING_PHOTON_2'


class BSAProtocol(
    StatefulProtocolTemplate(NodeProtocol, BSAState.WAITING_TICK),
):
    SUCCESS = 'BSAProtocol.SUCCESS'
    FAILURE = 'BSAProtocol.FAILURE'

    def __init__(self, node, clock, detection_offset, detection_window, name=None):
        super().__init__(node, name)
        if detection_offset + detection_window > clock.delta_time():
            raise ValueError('Detection time exceeds clock period.')
        
        self.detection_offset = detection_offset
        self.detection_window = detection_window
        self.clock = clock
    
    @statehandler(BSAState.WAITING_TICK)
    def _waiting_tick(self):
        yield self.await_signal(
            sender=self.clock,
            signal_label=Clock.TICK
        )
        return BSAState.WAITING_OFFSET
    
    @statehandler(BSAState.WAITING_OFFSET)
    def _waiting_offset(self):
        yield self.await_timer(self.detection_offset)
        return BSAState.WAITING_PHOTON_1
    
    @statehandler(BSAState.WAITING_PHOTON_1, BSAState.WAITING_PHOTON_2)
    def _waiting_photons(self):
        qportA = self.node.ports['qinA']
        qportB = self.node.ports['qinB']

        detection_window_expire = self.await_timer(
            self.detection_window
        )
        photon_arrived = (
            self.await_port_input(qportA)
            | self.await_port_input(qportB)
        )
        event = yield detection_window_expire | photon_arrived

        if event.second_term.value:
            return self._process_photon()
        else:
            log.info(f'BSA detected photon loss', at=self.node)
            self._announce(BSAProtocol.FAILURE)
            return BSAState.WAITING_TICK
        
    def _process_photon(self):
        if self.get_state() == BSAState.WAITING_PHOTON_1:
            return BSAState.WAITING_PHOTON_2
        else:
            self.node.qmemory.operate(ns.CNOT, [0, 1])
            self.node.qmemory.operate(ns.H, 0)
            [mX, mZ], _ = self.node.qmemory.measure([0, 1])
            if mZ == 0:
                log.info(f'BSA found undistinguishable state', at=self.node)
                self._announce(BSAProtocol.FAILURE)
            else:
                log.info(f'BSA conducted successful measurement', at=self.node)
                self._announce(
                    BSAProtocol.SUCCESS,
                    { 'cX': mZ, 'cZ': mX },
                    { 'cX': 0, 'cZ': 0 }
                )
            return BSAState.WAITING_TICK

    def _announce(self, result, A=None, B=None):
        cportA = self.node.ports['coutA']
        cportB = self.node.ports['coutB']
        cportA.tx_output((result, A))
        log.info(f'BSA message to A -> result: {result}, msg: {A}', outof=self.node)
        cportB.tx_output((result, B))
        log.info(f'BSA message to B -> result: {result}, msg: {B}', outof=self.node)


class SwapWithBSA (PhysicalLayer):
    def __init__(self, node, clock, name=None) -> None:
        super().__init__(node, name)
        self.clock = clock

    def _start_attempts(self):
        qout = self.node.ports['qout']
        cin = self.node.ports['cin']

        while True:
            yield self.await_signal(
                sender=self.clock,
                signal_label=Clock.TICK
            )
            log.info(f'Initializing memory', at=self.node)
            yield from self.init_memory()
            log.info(f'Memory ready', at=self.node)

            [photon] = self.node.qmemory.pop(1)
            qout.tx_output(photon)
            log.info(f'Sent photon', outof=self.node)

            yield self.await_port_input(cin)
            (result, controls) = cin.rx_input().items[0]
            log.info(f'Received message: {result}, {controls}', into=self.node)

            if result == BSAProtocol.SUCCESS:
                yield from self.execute_correction(cX=(controls['cX']==1), cZ=controls['cZ']==1)
                [q] = self.node.qmemory.peek(0)
                correct = KetRepr(ket=ketstates.b00)
                fidelity = q.qstate.qrepr.fidelity(correct)
                log.info(f'Entanglement swapping successful with fidelity: {fidelity}', at=self.node)
            

    @program_function(num_qubits=2)
    def init_memory(self, prog, qubits):
        [q1, q2] = qubits
        prog.apply(INSTR_INIT, [q1, q2])
        prog.apply(INSTR_H, q1)
        prog.apply(INSTR_CNOT, [q1, q2])

    @program_function(num_qubits=1)
    def execute_correction(self, prog, qubits, cX=False, cZ=False):
        [q] = qubits
        if cX: prog.apply(INSTR_X, q)
        if cZ: prog.apply(INSTR_Z, q)