
import logging
import os
import sys
import pandas as pd
import numpy as np
from tqdm import tqdm
from netsquid.qubits.qformalism import QFormalism

from components.protocols.link.link_purification import LinkWithPurification
from components.protocols.purify import *
from components.protocols.net import NetWithPurification
from prep_net import *
from config_reder import *
from sim_spawn import *


class NetStateLogger (LocalProtocol):
    def __init__(self, node1, node2, net1, net2, rounds, name, prefix=''):
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
        self.prefix = prefix

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
                print(f'{self.prefix} {round+1}/{self.rounds}: ', self.F[round])
                self.node1.qmemory.deallocate([pos1])
                self.node2.qmemory.deallocate([pos2])
                round +=1
            

        req1.cancelled = True
        req2.cancelled = True
        self.T += ns.sim_time()
        self.T /= SECOND
        ns.sim_stop()


def fixed_dst(config, dst, counts, multi_centre=False):
    iters = range(0, 4) if not multi_centre else range(1, 7)
    rounds = 50
    df = pd.DataFrame(index=counts, columns=[
        f'iter_{i}_{v}' for i in iters for v in ['F_avg', 'F_max', 'F_min', 'f']
    ])

    for iters in iters:
        for count in counts:
            net, alice, bob = create_head_nodes(config, 'Quantum Network')
            alice_net, bob_net = connect_with_rep_chain(
                config, net, alice, bob, dst, count,
                net_cutoff=5*SECOND,
                link_setup=lambda n1,l1,p1,n2,l2,p2: (
                    LinkWithPurification(n1,
                        LadderPurify(n1, p1, iters, True, 2, log.Layer.LINK, f'{n1.name}PUR'),
                        l1, name=f'{n1.name}LINKPUR'

                    ),
                    LinkWithPurification(n2,
                        LadderPurify(n2, p2, iters, False, 2, log.Layer.LINK, f'{n2.name}PUR'),
                        l2, name=f'{n2.name}LINKPUR'
                    )
                ),
                multi_centre=multi_centre
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

    ismulti = 'multi' if multi_centre else 'single'
    df.to_csv(f'data/repeaters_{ismulti}.csv', index=True)


def fixed_dst_mixed(config, dst, counts):
    cutoff = float(sys.argv[1]) * SECOND

    iters = [(3,2)] #[(3,1), (2,2), (3,2), (3,3)]
    rounds = 50
    df = pd.DataFrame(index=counts, columns=[
        f'iter_{liter}/{giter}_{v}' for liter, giter in iters for v in ['F_avg', 'F_max', 'F_min', 'f']
    ])

    for liter, giter in iters:
        for count in counts:
            net, alice, bob = create_head_nodes(config, 'Quantum Network')
            alice_net, bob_net = connect_with_rep_chain(
                config, net, alice, bob, dst, count,
                net_cutoff=cutoff,
                link_setup=lambda n1,l1,p1,n2,l2,p2: (
                    LinkWithPurification(n1,
                        MixedPurify(n1, p1, liter, giter, True, 2, log.Layer.LINK, f'{n1.name}PUR'),
                        l1, name=f'{n1.name}LINKPUR'

                    ),
                    LinkWithPurification(n2,
                        MixedPurify(n2, p2, liter, giter, False, 2, log.Layer.LINK, f'{n2.name}PUR'),
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

            df.loc[count, f'iter_{liter}/{giter}_F_avg'] = np.average(logger.F)
            df.loc[count, f'iter_{liter}/{giter}_F_max'] = np.max(logger.F)
            df.loc[count, f'iter_{liter}/{giter}_F_min'] = np.min(logger.F)
            df.loc[count, f'iter_{liter}/{giter}_f'] = rounds / logger.T
            print(f'Finished iteration {liter}/{giter} with {count} repeater(s)')

            df.to_csv(f'data/mcr/c{cutoff/SECOND}.csv', index=True)


def multiple_cutoffs(config, dst, counts, cutoffs):
    iters = 3
    rounds = 50
    df = pd.DataFrame(index=counts, columns=[
        f'cutoff_{i/SECOND}_{v}' for i in cutoffs for v in ['F', 'f']
    ])

    for cutoff in cutoffs:
        for count in counts:
            net, alice, bob = create_head_nodes(config, 'Quantum Network')
            alice_net, bob_net = connect_with_rep_chain(
                config, net, alice, bob, dst, count,
                net_cutoff=cutoff,
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

            df.loc[count, f'cutoff_{cutoff/SECOND}_F'] = np.average(logger.F)
            df.loc[count, f'cutoff_{cutoff/SECOND}_f'] = rounds / logger.T
            print(f'Finished {cutoff/SECOND}s cutoff with {count} repeater(s)')
            df.to_csv(f'data/cutoff_effect.csv', index=True)


def end_to_end(dst, counts, nl, ng, ll, lg):
    link_iter, net_iter = 3, 3
    rounds = 100
    df = pd.DataFrame(index=counts, columns=['F_avg', 'F_max', 'F_min', 'f'])

    for count in counts:
        net, alice, bob = create_head_nodes(config, 'Quantum Network')
        alice_net, bob_net = connect_with_rep_chain(
            config, net, alice, bob, dst, count,
            net_cutoff=0.5*SECOND,
            link_setup=lambda n1,l1,p1,n2,l2,p2: (
                LinkWithPurification(n1,
                    MixedPurify(n1, p1, ll, lg, True, 2, log.Layer.LINK, f'{n1.name}PUR'),
                    l1, name=f'{n1.name}LINKPUR'
                ),
                LinkWithPurification(n2,
                    MixedPurify(n2, p2, ll, lg, False, 2, log.Layer.LINK, f'{n2.name}PUR'),
                    l2, name=f'{n2.name}LINKPUR'
                )
            ),
            app_headers=[
                NetWithPurification.PURIFY_HEADER,
                DEJMPSProtocol.get_header(log.Layer.NETWORK)
            ]
        )

        alice_purify = MixedPurify(alice, 'cdir', nl, ng, True, 2, log.Layer.NETWORK, 'AlcNPUR')
        alice_netpurify = NetWithPurification(
            alice, 'cdir', alice_purify, alice_net, name='AlcNETPUR')

        bob_purify = MixedPurify(bob, 'cdir', nl, ng, False, 2, log.Layer.NETWORK, 'BobNPUR')
        bob_netpurify = NetWithPurification(
            bob, 'cdir', bob_purify, bob_net, name='BobNETPUR')

        logger = NetStateLogger(
            alice, bob, alice_netpurify, bob_netpurify, rounds, 'NetStateLogger'
        )
        logger.start()

        ns.sim_run()
        ns.sim_reset()

        df.loc[count, f'F_avg'] = np.average(logger.F)
        df.loc[count, f'F_max'] = np.max(logger.F)
        df.loc[count, f'F_min'] = np.min(logger.F)
        df.loc[count, f'f'] = rounds / logger.T
        print(f'{dst} : {nl}-{ng}+{ll}-{lg} | Finished purification with {count} repeater(s)')

        df.to_csv(f'data/e2edst/dst_{dst}_{nl}-{ng}+{ll}-{lg}.csv', index=True)


def cutoff_F_vd_f(lock, config, dst, cutoff):
    simulation(lock)
    liter, giter = 3, 2
    rounds = 200

    net, alice, bob = create_head_nodes(config, 'Quantum Network')
    alice_net, bob_net = connect_with_rep_chain(
        config, net, alice, bob, dst, 2,
        net_cutoff=cutoff,
        link_setup=lambda n1,l1,p1,n2,l2,p2: (
            LinkWithPurification(n1,
                MixedPurify(n1, p1, liter, giter, True, 2, log.Layer.LINK, f'{n1.name}PUR'),
                l1, name=f'{n1.name}LINKPUR'
            ),
            LinkWithPurification(n2,
                MixedPurify(n2, p2, liter, giter, False, 2, log.Layer.LINK, f'{n2.name}PUR'),
                l2, name=f'{n2.name}LINKPUR'
            )
        )
    )

    logger = NetStateLogger(
        alice, bob, alice_net, bob_net, rounds, 'NetStateLogger', f'Cutoff: {cutoff/SECOND}s - '
    )
    logger.start()

    ns.sim_run()
    ns.sim_reset()

    print(f'Finished {cutoff/SECOND}s cutoff')
    with lock:
        df = pd.read_csv('data/cutoff_F_vs_f.csv', index_col=0)
        df.loc[cutoff, 'F_avg'] = np.average(logger.F)
        df.loc[cutoff, 'F_max'] = np.max(logger.F)
        df.loc[cutoff, 'F_min'] = np.min(logger.F)
        df.loc[cutoff, 'f'] = rounds / logger.T
        df.to_csv(f'data/cutoff_F_vs_f.csv', index=True)

def cutoff_F_vd_f_init():
    cutoffs = np.array([0.2, 0.3, 0.4, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.5, 4, 5, 6])*SECOND
    df = pd.DataFrame(index=cutoffs, columns=['F_avg', 'F_max', 'F_min', 'f'])
    df.to_csv('data/cutoff_F_vs_f.csv', index=True)

    spawner = SimulationSpawner(cutoff_F_vd_f)
    spawner.run(
        repeat(config),
        repeat(60),
        cutoffs
    )


if __name__ == '__main__':
    config = read_config('netconf/testvalues')

    #fixed_dst(config, 60, range(1, 7))
    #multiple_cutoffs(config, 60, range(1, 7), [1*SECOND, 3*SECOND, 5*SECOND, 10*SECOND])
    #fixed_dst_mixed(config, 60, range(1, 7))

    #niter = 0
    #liter = 2
    #end_to_end(50, range(1, 5), niter, 1, liter, 1)
    #end_to_end(60, range(1, 6), niter, 1, liter, 1)
    #end_to_end(70, range(2, 7), niter, 1, liter, 1)
    #end_to_end(80, range(2, 8), niter, 1, liter, 1)
    #end_to_end(90, range(2, 9), niter, 1, liter, 1)
    #end_to_end(100, range(3, 10), niter, 1, liter, 1)
    #end_to_end(110, range(3, 11), niter, 1, liter, 1)
    #end_to_end(120, range(3, 12), niter, 1, liter, 1)
    #end_to_end(130, range(4, 13), niter, 1, liter, 1)
    #end_to_end(140, range(4, 14), niter, 1, liter, 1)
    #end_to_end(150, range(4, 15), niter, 1, liter, 1)

    cutoff_F_vd_f_init()
