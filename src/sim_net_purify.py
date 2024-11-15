
import logging
import os
import pandas as pd
import numpy as np
from tqdm import tqdm
from netsquid.qubits.qformalism import QFormalism

from components.protocols.link.link_purification import LinkWithPurification
from components.protocols.purify.ladder_purify import LadderPurify
from prep_net import *
from config_reder import *


class NetStateLogger (LocalProtocol):
    def __init__(self, node1, node2, net1, net2, rounds, name):
        super().__init__(
            dict(node1=node1, node2=node2),
            name
        )
        self.add_subprotocol(net1, name='net1')
        self.add_subprotocol(net2, name='net2')
        self.net1 = net1
        self.net2 = net2
        self.node1 = node1
        self.node2 = node2
        self.rounds = rounds

    def run(self):
        self.start_subprotocols()
        self.F = np.zeros(self.rounds, dtype=float)
        self.t = np.zeros(self.rounds, dtype=float)
        self.T = -ns.sim_time()

        req1 = self.net1.initiate_sharing(self.rounds)
        req2 = self.net2.recieve()

        qubits1 = []
        qubits2 = []

        round = 0
        while round < self.rounds:
            ev1 = req1.resp_event(self)
            ev2 = req2.resp_event(self)
            
            expr = yield ev1 | ev2
            if expr.first_term.value:
                resp = req1.get_answare(self)
                qubits1.append(resp.qubit)
            else:
                resp = req2.get_answare(self)
                qubits2.append(resp.qubit)

            if len(qubits1) > 0 and len(qubits2) > 0:
                pos1 = qubits1.pop(0).position
                pos2 = qubits2.pop(0).position
                [q1] = self.node1.qmemory.peek([pos1])
                [q2] = self.node2.qmemory.peek([pos2])
                self.F[round] = ns.qubits.fidelity([q1, q2], ns.qubits.ketstates.b00, squared=True)
                print(f'{round+1}/{self.rounds}: ', self.F[round])
                self.node1.qmemory.deallocate([pos1])
                self.node2.qmemory.deallocate([pos2])
                round +=1
            

        req1.cancelled = True
        req2.cancelled = True
        self.T += ns.sim_time()
        self.T /= SECOND
        ns.sim_stop()


def fixed_dst(config, dst, counts):
    iters = range(0, 4)
    rounds = 50
    df = pd.DataFrame(index=counts, columns=[
        f'iter_{i}_{v}' for i in iters for v in ['F_avg', 'F_max', 'F_min', 'f']
    ])

    for iters in iters:
        for count in counts:
            net, alice, bob = create_head_nodes(config, 'Quantum Network')
            alice_net, bob_net = connect_with_rep_chain(
                config, net, alice, bob, dst, count,
                link_setup=lambda n1,l1,p1,n2,l2,p2: (
                    LinkWithPurification(n1,
                        LadderPurify(n1, p1, iters, True, 2, log.Layer.LINK, f'{n1.name}PUR'),
                        l1, name=f'{n1.name}LINKPUR'

                    ),
                    LinkWithPurification(n2,
                        LadderPurify(n2, p2, iters, False, 2, log.Layer.LINK, f'{n2.name}PUR'),
                        l2, name=f'{n2.name}LINKPUR'
                    )
                )
            )

            logger = NetStateLogger(
                alice, bob, alice_net, bob_net, rounds, 'NetStateLogger'
            )
            logger.start()

            ns.sim_run()
            ns.sim_reset()

            df.loc[count, f'iter_{iters}_F_avg'] = np.average(logger.F)
            df.loc[count, f'iter_{iters}_F_max'] = np.max(logger.F)
            df.loc[count, f'iter_{iters}_F_min'] = np.min(logger.F)
            df.loc[count, f'iter_{iters}_f'] = rounds / logger.T
            print(f'Finished iteration {iters}/4 with {count} repeater(s)')

    df.to_csv('data/repeaters.csv', index=True)


if __name__ == '__main__':
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.INFO, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)
    config = read_config('netconf/testvalues')

    fixed_dst(config, 60, range(1, 7))