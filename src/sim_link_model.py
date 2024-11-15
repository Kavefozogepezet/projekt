
import netsquid as ns
import pandas as pd
import numpy as np
import logging
import os
from tqdm import tqdm
from netsquid.protocols import LocalProtocol
from netsquid.qubits.qformalism import QFormalism
from netsquid.components.instructions import *

from simlog import log
from components.protocols.util import *
from components.protocols.link import LinkResponseType, LinkLayer

from prep_net import *
from config_reder import *


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
        fidelity = ns.qubits.fidelity([q1, q2], ns.qubits.ketstates.b00, squared=True)
        self.df.at[self.idx, self.name] = fidelity
        req1.cancelled = True
        req2.cancelled = True
        ns.sim_stop()


def main():
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.INFO, log.TimeUnit.MICROSECONDS)
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
    df = pd.DataFrame(index=range(len(x)), columns=['distance', 'physical', 'inserted'])
    df['distance'] = x
    
    for i in tqdm(range(len(x))):
        dst = x[i]
        config = read_config('netconf/link_fidelity')

        net, alice, bob = create_head_nodes(config, 'Quantum Network')
        alice_link, bob_link = create_physical_link(config, dst, net, alice, bob)
        logger = LinkFidelityLogger(alice, bob, alice_link, bob_link, df, i, 'physical')
        logger.start()
        ns.sim_run()
        ns.sim_reset()

        net, alice, bob = create_head_nodes(config, 'Quantum Network')
        alice_link, bob_link = create_link_with_insertion(config, dst, net, alice, bob)
        logger = LinkFidelityLogger(alice, bob, alice_link, bob_link, df, i, 'inserted')
        logger.start()

        ns.sim_run()
        ns.sim_reset()

    df.to_csv('data/link_fidelity_2.csv', index=False)


if __name__ == '__main__':
    main()
