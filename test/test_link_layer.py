
import netsquid as ns
import logging
import os
from netsquid.nodes import Network
from netsquid.nodes import Node
from netsquid.protocols import NodeProtocol
from netsquid.qubits.qformalism import QFormalism
from netsquid.util.simtools import MICROSECOND, MILLISECOND

from simlog import log
from components.protocols.phys import BSAProtocol, SwapWithBSAProtocol, PhysicalLayer
from components.protocols.util import Clock
from components.hardware import QuantumFibre, ClassicalFibre, QProcessor
from components.nodes import BSANode
from components.protocols.link import SimPLE
from mock.net_mock import MockNetLayer


def test_link_layer():
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
            size=2, T1=80*MICROSECOND, T2=40*MICROSECOND,
            fallback_to_nonphysical=True
        )
    )
    bob = Node(
        name='Bob',
        port_names=['qout', 'cin'],
        qmemory=QProcessor(
            name='bobs_processor',
            size=2, T1=80*MICROSECOND, T2=40*MICROSECOND,
            fallback_to_nonphysical=True
        )
    )
    bsa = BSANode(name='BSA')

    clock = Clock(delta_time=20*MICROSECOND, nodes=[alice, bob, bsa])

    qA2BSA = QuantumFibre('Alice-BSA_quantum', 2)
    qB2BSA = QuantumFibre('Bob-BSA_quantum', 2)

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

    alice_phys = SwapWithBSAProtocol(alice, clock, 'qout', 'cin')
    alice_link = SimPLE(alice, alice_phys)

    bob_phys = SwapWithBSAProtocol(bob, clock, 'qout', 'cin')
    bob_link = SimPLE(bob, bob_phys)

    bsa_phys = BSAProtocol(bsa, clock, 9*MICROSECOND, 1*MICROSECOND, 1)

    net_mock = MockNetLayer(alice, bob, alice_link, bob_link, 'MockLinkLayer')

    bsa_phys.start()
    clock.start()
    net_mock.start()

    ns.sim_run(1*MILLISECOND)

