
import netsquid as ns
import logging
import os
from netsquid.nodes import Network
from netsquid.nodes import Node
from netsquid.protocols import NodeProtocol
from netsquid.components import QuantumProcessor
from netsquid.qubits.qformalism import QFormalism
from netsquid.util.simtools import MICROSECOND, MILLISECOND
from netsquid.components.models.qerrormodels import T1T2NoiseModel

from simlog import log
from components.protocols.phys import BSAProtocol, SwapWithBSAProtocol, PhysicalLayer
from components.protocols.util import Clock
from components.hardware import QuantumFibre, ClassicalFibre, QProcessor
from components.nodes import BSANode


def main():
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.INFO, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)

    net = Network('Quantum Network')
    
    alice = Node(
        name='Alice',
        port_names=['qout', 'cin'],
        qmemory=QProcessor(
            name='alices_processor',
            size=2, T1=1*MILLISECOND, T2=100*MICROSECOND,
            fallback_to_nonphysical=True
        )
    )
    bob = Node(
        name='Bob',
        port_names=['qout', 'cin'],
        qmemory=QProcessor(
            name='bobs_processor',
            size=2, T1=1*MILLISECOND, T2=100*MICROSECOND,
            fallback_to_nonphysical=True
        )
    )
    bsa = BSANode(name='BSA')

    clock = Clock(delta_time=20*MICROSECOND, nodes=[alice, bob, bsa])

    qA2BSA = QuantumFibre('Alice-BSA_quantum', 2, 0)
    qB2BSA = QuantumFibre('Bob-BSA_quantum', 2, 0)

    cA2BSA = ClassicalFibre('Alice-BSA_classical', 2)
    cB2BSA = ClassicalFibre('Bob-BSA_classical', 2)

    net.add_nodes([alice, bob, bsa])
    net.add_connection(
        alice, bsa, qA2BSA,
        label='Alice-BSA_quantum',
        port_name_node1='qout', port_name_node2='qinA'
    )
    net.add_connection(
        alice, bsa, cA2BSA,
        label='Alice-BSA_classical',
        port_name_node1='cin', port_name_node2='coutA'
    )
    net.add_connection(
        bob, bsa, qB2BSA,
        label='Bob-BSA_quantum',
        port_name_node1='qout', port_name_node2='qinB'
    )
    net.add_connection(
        bob, bsa, cB2BSA,
        label='Bob-BSA_classical',
        port_name_node1='cin', port_name_node2='coutB'
    )

    class MockPhysicalState(NodeProtocol):
        def __init__(self, node, phys_proto, name):
            super().__init__(node, name)
            self.add_subprotocol(phys_proto, name='physical_protocol')

        def run(self):
            self.start_subprotocols()
            phys_proto = self.subprotocols['physical_protocol']
            phys_proto.start_generation()
            while True:
                success = self.await_signal(
                    sender=phys_proto,
                    signal_label=PhysicalLayer.SUCCESS
                )
                failure = self.await_signal(
                    sender=phys_proto,
                    signal_label=PhysicalLayer.FAILURE
                )
                event = yield success | failure
                if event.first_term.value:
                    res = phys_proto.get_signal_result(PhysicalLayer.SUCCESS)
                    log.info(f'{self.name} succeeded in creating entanglement -> memory address: {res}')
                    self.node.qmemory.deallocate([res])
                else:
                    log.info(f'{self.name} failed to create entanglement')



    alice_proto = SwapWithBSAProtocol(alice, clock, 'qout', 'cin')
    bob_proto = SwapWithBSAProtocol(bob, clock, 'qout', 'cin')
    bsa_proto = BSAProtocol(bsa, clock, detection_offset=9*MICROSECOND, detection_window=1*MICROSECOND)

    alice_mock = MockPhysicalState(alice, alice_proto, 'Alice_mock')
    bob_mock = MockPhysicalState(bob, bob_proto, 'Bob_mock')

    bsa_proto.start()
    alice_mock.start()
    bob_mock.start()
    clock.start()

    ns.sim_run(200*MICROSECOND)


if __name__ == '__main__':
    main()
