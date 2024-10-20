
import netsquid as ns
import pandas as pd
import numpy as np
import logging
import os
from tqdm import tqdm
from netsquid.nodes import Network
from netsquid.nodes import Node
from netsquid.protocols import LocalProtocol
from netsquid.qubits.qformalism import QFormalism
from netsquid.util.simtools import MICROSECOND, MILLISECOND, SECOND, NANOSECOND
from netsquid.components.instructions import *
from netsquid.components.models.qerrormodels import DepolarNoiseModel
from netsquid.components.qprocessor import PhysicalInstruction

from simlog import log
from components.protocols.phys import BSAProtocol, SwapWithBSAProtocol, PhysicalLayer
from components.protocols.util import *
from components.hardware import QuantumFibre, ClassicalFibre, QProcessor
from components.nodes import BSANode
from components.protocols.link import SimPLE, LinkResponseType, LinkDescriptor, StateInsertionProtocol, LinkLayer


class LinkTriesLogger (LocalProtocol):
    def __init__(self, node1, node2, link1, link2, runs, name=None):
        super().__init__(
            dict(node1=node1, node2=node2),
            name
        )
        self.add_subprotocol(link1, name='link1')
        self.add_subprotocol(link2, name='link2')
        self.link1 = link1
        self.link2 = link2
        self.node1 = node1
        self.node2 = node2
        self.runs = runs
        self.stats = pd.DataFrame(
            index=range(self.runs),
            columns=['fidelity', 'tries']
        )

    def run(self):
        self.start_subprotocols()

        req1 = self.link1.request_entanglement(response_type=LinkResponseType.CONSECUTIVE)
        req2 = self.link2.request_entanglement(response_type=LinkResponseType.CONSECUTIVE)

        for i in tqdm(range(self.runs)):
            [resp1, resp2] = yield from ProtocolRequest.await_all(self, req1, req2)
            assert resp1.result == resp2.result
            if resp1.result != LinkLayer.OK:
                raise Exception('Entanglement request failed')
            
            [q1] = self.node1.qmemory.peek([resp1.qubit.position])
            [q2] = self.node2.qmemory.peek([resp2.qubit.position])

            fidelity = ns.qubits.fidelity([q1, q2], ns.qubits.ketstates.b00)
            tries = resp1.tries
            self.stats.loc[i] = [fidelity, tries]

            self.node1.qmemory.deallocate([resp1.qubit.position])
            self.node2.qmemory.deallocate([resp2.qubit.position])

        self.stats.to_csv(f'data/{self.name}_link_stats.csv.gz', index=False, compression='gzip')
        req1.cancelled = True
        req2.cancelled = True
        ns.sim_stop()


class LinkFidelityLogger (LocalProtocol):
    def __init__(self, node1, node2, link1, link2, df, idx, name):
        super().__init__(
            dict(node1=node1, node2=node2),
            name
        )
        self.add_subprotocol(link1, name='link1')
        self.add_subprotocol(link2, name='link2')
        self.link1 = link1
        self.link2 = link2
        self.node1 = node1
        self.node2 = node2
        self.df = df
        self.idx = idx

    def run(self):
        self.start_subprotocols()
        req1 = self.link1.request_entanglement(response_type=LinkResponseType.CONSECUTIVE)
        req2 = self.link2.request_entanglement(response_type=LinkResponseType.CONSECUTIVE)
        [resp1, resp2] = yield from ProtocolRequest.await_all(self, req1, req2)
        [q1] = self.node1.qmemory.peek([resp1.qubit.position])
        [q2] = self.node2.qmemory.peek([resp2.qubit.position])
        fidelity = ns.qubits.fidelity([q1, q2], ns.qubits.ketstates.b00)
        self.df.at[self.idx, self.name] = fidelity
        req1.cancelled = True
        req2.cancelled = True
        ns.sim_stop()


def net_setup():
    net = Network('Quantum Network')

    alice = Node(
        name='Alice',
        port_names=['qout', 'cin'],
        qmemory=QProcessor(
            name='AlcPROC',
            size=2, T1=3600*SECOND, T2=1.46*SECOND,
            #fallback_to_nonphysical=True,
            phys_instructions=[
                PhysicalInstruction(
                    INSTR_INIT, duration=0, topology=[0,1],
                    quantum_noise_model=DepolarNoiseModel(
                        time_independent=True,
                        depolar_rate=0.1
                    )
                ),
                PhysicalInstruction(INSTR_INIT, duration=0, topology=[2]),
                PhysicalInstruction(INSTR_CNOT, duration=0, topology=[(0,2),(1,2),(2,0),(2,1)]),
                PhysicalInstruction(INSTR_X, duration=0, topology=[0,1]),
                PhysicalInstruction(INSTR_Z, duration=0, topology=[0,1]),
                PhysicalInstruction(INSTR_H, duration=0, topology=[0,1])
            ]
        )
    )
    bob = Node(
        name='Bob',
        port_names=['qout', 'cin'],
        qmemory=QProcessor(
            name='BobPROC',
            size=2, T1=3600*SECOND, T2=1.46*SECOND,
            #fallback_to_nonphysical=True,
            phys_instructions=[
                PhysicalInstruction(
                    INSTR_INIT, duration=0, topology=[0,1],
                    quantum_noise_model=DepolarNoiseModel(
                        time_independent=True,
                        depolar_rate=0.1
                    )
                ),
                PhysicalInstruction(INSTR_INIT, duration=0, topology=[2]),
                PhysicalInstruction(INSTR_CNOT, duration=0, topology=[(0,2),(1,2)]),
                PhysicalInstruction(INSTR_X, duration=0, topology=[0,1]),
                PhysicalInstruction(INSTR_Z, duration=0, topology=[0,1]),
                PhysicalInstruction(INSTR_H, duration=0, topology=[0,1])
            ]
        )
    )

    net.add_nodes([alice, bob])
    return net, alice, bob


def with_phys_layer(dst):
    net, alice, bob = net_setup()
    bsa = BSANode(name='BSA')
    net.add_node(bsa)

    roundtrip = dst*1.45/3e5
    clk = (roundtrip) * SECOND + 8*MICROSECOND
    travel = roundtrip * SECOND / 2
    fiber = dst / 2

    clock = Clock(delta_time=clk, nodes=[alice, bob, bsa])

    qA2BSA = QuantumFibre('Alice-BSA_quantum', fiber, 0)
    qB2BSA = QuantumFibre('Bob-BSA_quantum', fiber, 0)

    cA2BSA = ClassicalFibre('Alice-BSA_classical', fiber)
    cB2BSA = ClassicalFibre('Bob-BSA_classical', fiber)

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

    #alice_phys = SwapWithBSAProtocol(alice, clock, 'qout', 'cin',
    #    collection_eff=0.286, qfc_eff=0.32, name='AlcPHYS')
    #alice_link = SimPLE(alice, alice_phys, name='AlcLINK')
    alice_phys = SwapWithBSAProtocol(alice, clock, 'qout', 'cin',
    collection_eff=1, qfc_eff=1, name='AlcPHYS')
    alice_link = SimPLE(alice, alice_phys, name='AlcLINK')

    #bob_phys = SwapWithBSAProtocol(bob, clock, 'qout', 'cin',
    #    collection_eff=0.286, qfc_eff=0.32, name='BobPHYS')
    #bob_link = SimPLE(bob, bob_phys, name='BobLink')
    bob_phys = SwapWithBSAProtocol(bob, clock, 'qout', 'cin',
    collection_eff=1, qfc_eff=1, name='BobPHYS')
    bob_link = SimPLE(bob, bob_phys, name='BobLink')

    bsa_phys = BSAProtocol(bsa, clock,
        detection_offset=travel*0.9,
        detection_window=travel*0.2,
        #detector_efficiency=0.93
        detector_efficiency=1
    )
    bsa_phys.start()
    clock.start()

    return net, alice, bob, alice_link, bob_link


def with_state_insertion(dst):
    net, alice, bob = net_setup()

    link_desc = LinkDescriptor(
        distance=dst,
        qfc_eff=0.32,
        collection_eff=0.286,
        detection_eff=0.93,
        init_time=8*MICROSECOND,
        init_fidelity=0.94,
        correction_time=5*NANOSECOND,
        L0=100, T1=3600*SECOND, T2=1.46*SECOND
    )

    common_link = StateInsertionProtocol(alice, bob, link_desc)
    alice_link, bob_link = common_link.node_protocols()
    common_link.start()

    return net, alice, bob, alice_link, bob_link


def main():
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.DEBUG, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)

    #_, alice, bob, alice_link, bob_link = with_phys_layer(4)
    #stat_logger = LinkStatLogger(alice, bob, alice_link, bob_link, 1000, 'physical')
    #stat_logger.start()
    #ns.sim_run()
    #ns.sim_reset()

    #ns.logger.info('-' * 80)

    #_, alice, bob, alice_link, bob_link = with_state_insertion(4)
    #stat_logger = LinkStatLogger(alice, bob, alice_link, bob_link, 1000, 'inserted')
    #stat_logger.start()
    #ns.sim_run()

    x = np.logspace(0, 2.5, 8)
    print(x)
    df = pd.DataFrame(index=range(len(x)), columns=['distance', 'physical', 'inserted'])
    df['distance'] = x
    for i in tqdm(range(len(x))):
        dst = x[i]

        _, alice, bob, alice_link, bob_link = with_phys_layer(dst)
        logger = LinkFidelityLogger(alice, bob, alice_link, bob_link, df, i, 'physical')
        logger.start()
        ns.sim_run()
        ns.sim_reset()

        _, alice, bob, alice_link, bob_link = with_state_insertion(dst)
        logger = LinkFidelityLogger(alice, bob, alice_link, bob_link, df, i, 'inserted')
        logger.start()

        ns.sim_run()
        ns.sim_reset()

    df.to_csv('data/link_fidelity.csv', index=False)


if __name__ == '__main__':
    main()
