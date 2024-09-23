
from netsquid.qubits.kettools import KetRepr
from netsquid.qubits import ketstates
from netsquid.components.instructions import \
    INSTR_INIT, INSTR_CNOT, INSTR_H, INSTR_X, INSTR_Z

from ..util import *
from .physical_layer import PhysicalLayer
from simlog import log
from .bsa_protocol import BSAProtocol


class SwapWithBSAProtocol (PhysicalLayer):
    def __init__(self, node, clock, qport, cport, name=None) -> None:
        super().__init__(node, name)
        self.clock = clock
        self.qport_name = qport
        self.cport_name = cport

    def _start_attempts(self):
        qout = self.node.ports[self.qport_name]
        cin = self.node.ports[self.cport_name]
        mem = self.node.qmemory

        while True:
            yield self.await_signal(
                sender=self.clock,
                signal_label=Clock.TICK
            )
            log.info(f'Initializing memory', at=self.node)
            [allocated_qubit] = mem.allocate(1)
            qubits = [allocated_qubit, mem.photon_pos()]
            yield from self.prepare_bell_state().on(qubits)
            log.info(f'Memory ready', at=self.node)

            [photon] = mem.pop_photon()
            qout.tx_output(photon)
            log.info(f'Sent photon', outof=self.node)

            yield self.await_port_input(cin)
            (result, controls) = cin.rx_input().items[0]
            log.info(f'Received message: {result}, {controls}', into=self.node)

            if result == BSAProtocol.SUCCESS:
                yield from self.execute_correction(cX=(controls['cX']==1), cZ=controls['cZ']==1).on([allocated_qubit])
                [q] = self.node.qmemory.peek(allocated_qubit)
                correct = KetRepr(ket=ketstates.b00)
                fidelity = q.qstate.qrepr.fidelity(correct)
                log.info(f'Entanglement swapping successful with fidelity: {fidelity}', at=self.node)
                self.send_signal(PhysicalLayer.SUCCESS, result=allocated_qubit)
            else:
                mem.discard(allocated_qubit)
                self.send_signal(PhysicalLayer.FAILURE)
            

    @program_function(num_qubits=2)
    def prepare_bell_state(self, prog, qubits):
        [q1, q2] = qubits
        prog.apply(INSTR_INIT, [q1, q2])
        prog.apply(INSTR_H, q1)
        prog.apply(INSTR_CNOT, [q1, q2])

    @program_function(num_qubits=1)
    def execute_correction(self, prog, qubits, cX=False, cZ=False):
        [q] = qubits
        if cX: prog.apply(INSTR_X, q)
        if cZ: prog.apply(INSTR_Z, q)
