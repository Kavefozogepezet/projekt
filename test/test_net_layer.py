

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
from components.protocols.net import SwapWithRepeaterProtocol

from mock.trans_mock import MockTransportLayer


def test_net_layer():
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.DEBUG, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)

    net = Network('Quantum Network')
    
    alice = Node(
        name='Alice',
        port_names=['qout', 'cin', 'cdirect'],
        qmemory=QProcessor(
            name='Alice_proc',
            size=2, T1=1*MILLISECOND, T2=100*MICROSECOND,
            fallback_to_nonphysical=True
        )
    )
    bob = Node(
        name='Bob',
        port_names=['qout', 'cin', 'cdirect'],
        qmemory=QProcessor(
            name='Bob_proc',
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

    cA2B = ClassicalFibre('Alice-Bob_classical', 4)

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
    net.add_connection(
        alice, bob, cA2B,
        label='Alice-Bob_classical',
        port_name_node1='cdirect', port_name_node2='cdirect'
    )

    alice_phys = SwapWithBSAProtocol(alice, clock, 'qout', 'cin', name='Alice_PHYS')
    alice_link = SimPLE(alice, alice_phys, name='Alice_LINK')
    alice_net = SwapWithRepeaterProtocol(alice, 'cdirect', alice_link, name='Alice_NET')

    bob_phys = SwapWithBSAProtocol(bob, clock, 'qout', 'cin', name='Bob_PHYS')
    bob_link = SimPLE(bob, bob_phys, name='Bob_LINK')
    bob_net = SwapWithRepeaterProtocol(bob, 'cdirect', bob_link, name='Bob_NET')

    bsa_phys = BSAProtocol(bsa, clock, 9*MICROSECOND, 1*MICROSECOND, 1, name='AB_BSA')

    trans_mock = MockTransportLayer(alice, bob, alice_net, bob_net, name='MockLinkLayer')

    bsa_phys.start()
    clock.start()
    trans_mock.start()

    ns.sim_run(1*MILLISECOND)
