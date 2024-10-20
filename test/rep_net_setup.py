
from netsquid.nodes import Node
from netsquid.util.simtools import MICROSECOND, MILLISECOND, SECOND
from netsquid.nodes import Network

from components.hardware import QuantumFibre, ClassicalFibre, QProcessor
from components.nodes import BSANode
from components.protocols.phys import BSAProtocol, SwapWithBSAProtocol
from components.protocols.util import Clock
from components.protocols.link import SimPLE
from components.protocols.net import SwapWithRepeaterProtocol, RepeaterProtocol
from components.protocols.net import ForwardProtocol
from simlog import log


def create_node(name, ports, proc_size):
    return Node(
        name=name,
        port_names=ports,
        qmemory=QProcessor(
            name=f'{name}PROC',
            size=proc_size, T1=200*MILLISECOND, T2=100*MILLISECOND,
            fallback_to_nonphysical=True
        )
    )


def classical_connect(net, node1, port1, node2, port2, length):
    conn = ClassicalFibre(f'{node1.name}-{node2.name}_classical', length)
    net.add_connection(
        node1, node2, conn,
        label=f'{node1.name}-{node2.name}_classical',
        port_name_node1=port1, port_name_node2=port2
    )


def quantum_connect(net, node1, port1, node2, port2, length):
    conn = QuantumFibre(f'{node1.name}-{node2.name}_quantum', length)
    net.add_connection(
        node1, node2, conn,
        label=f'{node1.name}-{node2.name}_quantum',
        port_name_node1=port1, port_name_node2=port2
    )

_bsa_count = 0
def install_bsa(net, node1, qport1, cport1, node2, qport2, cport2):
    global _bsa_count
    bsa_name = f'Bsa{_bsa_count}'
    bsa = BSANode(name=bsa_name)
    net.add_node(bsa)
    _bsa_count += 1

    classical_connect(net, node1, cport1, bsa, 'coutA', 2)
    quantum_connect(net, node1, qport1, bsa, 'qinA', 2)

    classical_connect(net, node2, cport2, bsa, 'coutB', 2)
    quantum_connect(net, node2, qport2, bsa, 'qinB', 2)

    clock = Clock(20*MICROSECOND, [node1, node2, bsa], name=f'Clk{_bsa_count}')
    bsa_phys = BSAProtocol(bsa, clock, 9*MICROSECOND, 1*MICROSECOND, 1, name=f'{bsa_name}PHYS')
    phys1 = SwapWithBSAProtocol(node1, clock, qport1, cport1, name=f'{node1.name}PHYS')
    phys2 = SwapWithBSAProtocol(node2, clock, qport2, cport2, name=f'{node2.name}PHYS')

    bsa_phys.start()
    clock.start()
    return phys1, phys2


def create_rep_chain(net, count, app_headers=None):
    global _bsa_count
    _bsa_count = 0

    # instantiate nodes
    alice = create_node('Alc', ['qout', 'cin', 'cRep'], 2)
    bob = create_node('Bob', ['qout', 'cin', 'cRep'], 2)
    reps = [
        create_node(f'Rep{i}', ['qoutA', 'cinA', 'qoutB', 'cinB', 'cNodeA', 'cNodeB'], 2)
        for i in range(count)
    ]

    net.add_nodes([alice, bob])
    net.add_nodes(reps)

    if count > 0:
        # Network connections, and physical protocols
        rep_phys = [[None, None] for _ in range(count)]

        (head_phys, rep_phys[0][0]) = install_bsa(net, alice, 'qout', 'cin', reps[0], 'qoutA', 'cinA')
        classical_connect(net, alice, 'cRep', reps[0], 'cNodeA', 4)

        for i in range(count-1):
            (rep_phys[i][1], rep_phys[i+1][0]) = (
                install_bsa(net, reps[i], 'qoutB', 'cinB', reps[i+1], 'qoutA', 'cinA')
            )
            classical_connect(net, reps[i], 'cNodeB', reps[i+1], 'cNodeA', 4)

        (rep_phys[-1][1], tail_phys) = install_bsa(net, reps[-1], 'qoutB', 'cinB', bob, 'qout', 'cin')
        classical_connect(net, reps[-1], 'cNodeB', bob, 'cRep', 4)

        log.info(f'{rep_phys}, {reps}')
        # Link and Network layer on each repeater
        for (rep_physA, rep_physB), rep in zip(rep_phys, reps):
            linkA = SimPLE(rep, rep_physA, [0], name=f'{rep.name}LINK1')
            linkB = SimPLE(rep, rep_physB, [1], name=f'{rep.name}LINK2')
            rep_net = RepeaterProtocol(rep, 'cNodeA', linkA, 'cNodeB', linkB, name=f'{rep.name}NET')
            rep_net.start()

        if app_headers:
            for rep in reps:
                rep_forward = ForwardProtocol(
                    rep, app_headers,
                    dict(cNodeA='cNodeB', cNodeB='cNodeA'),
                    name=f'{rep.name}FWD'
                )
                rep_forward.start()
    else:
        # Network connections, and physical protocols
        (head_phys, tail_phys) = install_bsa(net, alice, 'qout', 'cin', bob, 'qout', 'cin')
        classical_connect(net, alice, 'cRep', bob, 'cRep', 4)

    # Link and Network layer on head and tail nodes
    head_link = SimPLE(alice, head_phys, [0], name=f'{alice.name}LINK')
    head_net = SwapWithRepeaterProtocol(alice, 'cRep', head_link, 100*SECOND, name=f'{alice.name}NET')

    tail_link = SimPLE(bob, tail_phys, [0], name=f'{bob.name}LINK')
    tail_net = SwapWithRepeaterProtocol(bob, 'cRep', tail_link, 100*SECOND, name=f'{bob.name}NET')

    return (alice, head_net), (bob, tail_net)
