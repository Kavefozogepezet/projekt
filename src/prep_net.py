
from netsquid.nodes import Network
from netsquid.nodes import Node
from netsquid.util.simtools import MICROSECOND, MILLISECOND, SECOND, NANOSECOND

from simlog import log
from components.hardware import NVCProcessor, QuantumFibre, ClassicalFibre
from components.protocols.phys import BSAProtocol, SwapWithBSAProtocol, PhysicalLayer
from components.protocols.util import *
from components.nodes import BSANode
from components.protocols.net import SwapWithRepeaterProtocol, RepeaterProtocol, ForwardProtocol
from components.protocols.link import SimPLE, LinkResponseType, LinkDescriptor, StateInsertionProtocol, LinkLayer


def create_nvc_processor(config, centre_count=1, name=None):
    proc = config.node.processor
    mem = proc.memory_qubits
    multi = proc.multiqubit_gates
    inter = proc.inter_centre_gates

    return NVCProcessor(
        T1=mem.T1, T2=mem.T2, num_in_centre=mem.num_in_centre,
        t_gate=mem.t_gate, t_CX=multi.t_CX, t_init=mem.t_init, t_readout=mem.t_readout,
        F_gate=mem.F_gate, F_CX=multi.F_CX, F_init=mem.F_init, F_readout=mem.F_readout,
        centre_count=centre_count, F_iCX=inter.F_CX, t_iCX=inter.t_CX, name=name
    )


def create_qfibre(config, length, name=None):
    fibre = config.fibre
    return QuantumFibre(
        length=length,
        attenuation=fibre.attenuation,
        refractive_index=fibre.index_of_refraction,
        depolarizing_coeff=fibre.depolarization_length,
        name=name
    )


def create_cfibre(config, length, name=None):
    fibre = config.fibre
    return ClassicalFibre(
        length=length,
        refractive_index=fibre.index_of_refraction,
        name=name
    )

def connect_nodes(net, node1, port1, node2, port2, fibre, name=None):
    net.add_connection(
        node1, node2, fibre,
        label=name,
        port_name_node1=port1, port_name_node2=port2
    )

def create_head_nodes(config, net_name):
    net = Network(net_name)
    alice = Node(
        name='Alc',
        port_names=['qout', 'cin', 'cdir'],
        qmemory=create_nvc_processor(config, name='AlcPROC'),
    )
    bob = Node(
        name='Bob',
        port_names=['qout', 'cin', 'cdir'],
        qmemory=create_nvc_processor(config, name='BobPROC'),
    )
    net.add_nodes([alice, bob])
    return net, alice, bob


def create_repeater_nodes(config, net, count, multi_centre=False):
    reps = [
        Node(
            name=f'Rep{i}',
            port_names=['cA', 'cB'],
            qmemory=create_nvc_processor(config, (
                2 if multi_centre else 1
            ), name=f'Rep{i}PROC')
        )
        for i in range(count)
    ]
    net.add_nodes(reps)
    return reps


def create_physical_link(config, dst, net, alice, bob):
    bsa = BSANode(name='BSA')
    net.add_node(bsa)

    roundtrip = dst*1.45/3e5
    clk = (roundtrip) * SECOND + 8*MICROSECOND
    travel = roundtrip * SECOND / 2
    fiber = dst / 2

    clock = Clock(delta_time=clk, nodes=[alice, bob, bsa])

    qA2BSA = create_qfibre(config, fiber, 'Alc-BSA_q')
    qB2BSA = create_qfibre(config, fiber, 'Bob-BSA_q')

    cA2BSA = create_cfibre(config, fiber, 'Alc-BSA_c')
    cB2BSA = create_cfibre(config, fiber, 'Bob-BSA_c')

    # TODO use connect_nodes
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

    alice_phys = SwapWithBSAProtocol(
        alice, clock, 'qout', 'cin',
        collection_eff=config.node.processor.communication_qubit.photon_collection,
        qfc_eff=config.node.qfc.efficiency,
        name='AlcPHYS'
    )
    alice_link = SimPLE(alice, alice_phys, name='AlcLINK')

    bob_phys = SwapWithBSAProtocol(
        bob, clock, 'qout', 'cin',
        collection_eff=config.node.processor.communication_qubit.photon_collection,
        qfc_eff=config.node.qfc.efficiency,
        name='BobPHYS'
    )
    bob_link = SimPLE(bob, bob_phys, name='BobLINK')

    bsa_phys = BSAProtocol(bsa, clock,
        detection_offset=travel*0.9,
        detection_window=travel*0.2,
        detector_efficiency=config.bsa.SPD_efficiency
    )
    bsa_phys.start()
    clock.start()

    return alice_link, bob_link


def create_link_with_insertion(
    config, dst, net, alice, bob, 
    part_alice=None, part_bob=None,
    clk_factor=1
):
    comm = config.node.processor.communication_qubit
    qfc = config.node.qfc
    fibre = config.fibre
    bsa = config.bsa

    link_desc = LinkDescriptor(
        distance=dst,
        qfc_eff=qfc.efficiency,
        collection_eff=comm.photon_collection,
        detection_eff=bsa.SPD_efficiency,
        init_time=comm.t_init,
        init_fidelity=comm.F_init,
        correction_time=comm.t_gate*2,
        L0=fibre.depolarization_length,
        T1=comm.T1, T2=comm.T2,
        attenuation=fibre.attenuation,
        refractive_index=fibre.index_of_refraction
    )

    common_link = StateInsertionProtocol(
        alice, bob, link_desc,
        name=f'{alice.name}{bob.name}INS',
        clk_factor=clk_factor
    )
    alice_link, bob_link = common_link.node_protocols(part_alice, part_bob)
    common_link.start()

    return alice_link, bob_link


def connect_with_rep_chain(
    config, net, alice, bob, dst, count,
    app_headers=None, multi_centre=False,
    reserve_on_nodes=0,
    link_setup=lambda n1,l1,p1,n2,l2,p2: (l1,l2)
):
    if count < 1:
        raise ValueError('There must be 1 repeater in the network')
    
    reps = create_repeater_nodes(config, net, count, multi_centre)
    node_dst = dst / (count + 1)

    rep0, rep1 = reps[0], reps[-1]
    connect_nodes(
        net, alice, 'cdir', rep0, 'cA',
        create_cfibre(config, dst, f'{alice.name}{rep0.name}')
    )
    connect_nodes(
        net, rep1, 'cB', bob, 'cdir',
        create_cfibre(config, dst, f'{alice.name}{rep0.name}')
    )

    partA = alice.qmemory.centre_partition()[:-reserve_on_nodes]
    partB = bob.qmemory.centre_partition()[:-reserve_on_nodes]
    if multi_centre:
        rep_partA = reps[0].qmemory.centre_partition(0)
        rep_partB = reps[0].qmemory.centre_partition(1)
        clk_factor = 1
    else:
        whole_part = reps[0].qmemory.centre_partition()
        half = len(whole_part) // 2
        rep_partA = whole_part[:half]
        rep_partB = whole_part[half:]
        clk_factor = 2

    alice_link, repA = create_link_with_insertion(
        config, node_dst, net, alice, reps[0],
        part_alice=partA, part_bob=rep_partA, clk_factor=clk_factor
    )
    alice_link, repA = link_setup(alice, alice_link, 'cdir', reps[0], repA, 'cA')
    repB, bob_link = create_link_with_insertion(
        config, node_dst, net, reps[-1], bob,
        part_alice=rep_partB, part_bob=partB, clk_factor=clk_factor
    )
    repB, bob_link = link_setup(reps[-1], repB, 'cB', bob, bob_link, 'cdir')
    if count > 1:
        rep_links = [[repA, None]] + [[None, None] for _ in range(count-2)] + [[None, repB]]
    else:
        rep_links = [[repA, repB]]
    repA.name += '1'
    repB.name += '2'

    for i, (rep1, rep2) in enumerate(zip(reps[:-1], reps[1:])):
        connect_nodes(
            net, rep1, 'cB', rep2, 'cA',
            create_cfibre(config, node_dst, f'{rep1.name}{rep2.name}')
        )
        repl1, repl2 = create_link_with_insertion(
            config, node_dst, net, rep1, rep2,
            part_alice=rep_partB, part_bob=rep_partA, clk_factor=clk_factor
        )
        repl1.name += '2'
        repl2.name += '1'
        rep_links[i][1], rep_links[i+1][0] = link_setup(rep1, repl1, 'cB', rep2, repl2, 'cA')

    for rep, (linkA, linkB) in zip(reps, rep_links):
        if rep != linkA.node or rep != linkB.node:
            raise ValueError('Link node does not match repeater node')
        RepeaterProtocol(rep, 'cA', linkA, 'cB', linkB, name=f'{rep.name}NET').start()
        if app_headers is not None:
            ForwardProtocol(
                rep, app_headers,
                dict(cA='cB', cB='cA'),
                name=f'{rep.name}FWD'
            ).start()

    alice_net = SwapWithRepeaterProtocol(
        alice, 'cdir', alice_link,
        cutoff_time=10*SECOND, name=f'{alice.name}NET')
    bob_net = SwapWithRepeaterProtocol(
        bob, 'cdir', bob_link,
        cutoff_time=10*SECOND, name=f'{bob.name}NET')
    return alice_net, bob_net
