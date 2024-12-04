
import logging
import os
import pandas as pd
import numpy as np
from tqdm import tqdm
from netsquid.qubits.qformalism import QFormalism

from simlog import log
from components.protocols.util import *
from components.protocols.link import \
    LinkResponseType, LinkWithPurification
from components.protocols.purify import *
from prep_net import *
from config_reder import *


class PurifyStatLogger (LocalProtocol):
    def __init__(self, node1, node2, link1, link2, rounds, name):
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
        self.rounds = rounds

    def run(self):
        self.start_subprotocols()
        self.F = np.zeros(self.rounds, dtype=float)
        self.t = np.zeros(self.rounds, dtype=float)
        self.T = -ns.sim_time()
        start = ns.sim_time()

        req1 = self.link1.request_entanglement(response_type=LinkResponseType.CONSECUTIVE)
        req2 = self.link2.request_entanglement(response_type=LinkResponseType.CONSECUTIVE)

        for i in range(self.rounds):
            [resp1, resp2] = yield from ProtocolRequest.await_all(self, req1, req2)
            self.t[i] = (ns.sim_time() - start) / SECOND
            start = ns.sim_time()
            [q1] = self.node1.qmemory.peek([resp1.qubit.position])
            [q2] = self.node2.qmemory.peek([resp2.qubit.position])
            self.F[i] = ns.qubits.fidelity([q1, q2], ns.qubits.ketstates.b00, squared=True)
            print(f'{i+1}/{self.rounds}: ', self.F[i])
            self.node1.qmemory.deallocate([resp1.qubit.position])
            self.node2.qmemory.deallocate([resp2.qubit.position])

        req1.cancelled = True
        req2.cancelled = True
        self.T += ns.sim_time()
        self.T /= SECOND
        ns.sim_stop()


def main(config):
    rounds = 100
    dsts = [10, 20, 30, 40]
    max_iter = 5
    iters = range(0, max_iter+1)
    data = pd.DataFrame(
        columns=
        [f'{dst}_fidelity'for dst in dsts]
        + [f'{dst}_frequency'for dst in dsts],
        index = range(0, 10)
    )

    #bar = tqdm(range(len(dsts) * len(iters)))
    for dst in tqdm(dsts):
        iterations = 0
        max_iters = 7 if dst < 35 else 6
        for iterations in range(0, max_iters):
            net, alice, bob = create_head_nodes(config, 'Quantum Network')
            direct = create_cfibre(config, dst, 'AlcBobDIR')
            connect_nodes(net, alice, 'cdir', bob, 'cdir', direct)
            alice_link, bob_link = create_link_with_insertion(config, dst, net, alice, bob)

            alice_purify = LadderPurify(alice, 'cdir', iterations, True, 2, log.Layer.LINK, 'AlcPUR')
            alice_linkpurify = LinkWithPurification(
                alice, alice_purify, alice_link, name='AlcLINKPUR')

            bob_purify = LadderPurify(bob, 'cdir', iterations, False, 2, log.Layer.LINK, 'BobPUR')
            bob_linkpurify = LinkWithPurification(
                bob, bob_purify, bob_link, name='BobLINKPUR')

            logger = PurifyStatLogger(
                alice, bob, alice_linkpurify, bob_linkpurify, rounds, f'greedy_{dst}')
            logger.start()

            ns.sim_run()
            ns.sim_reset()

            F_avg = np.average(logger.F)
            f = rounds / logger.T

            data.loc[iterations, f'{dst}_fidelity'] = F_avg
            data.loc[iterations, f'{dst}_frequency'] = f

            print(f'Finished iteration {iterations}: {F_avg}')

    data.to_csv('data/ladder3.csv', index=True)


def max_fidelity(config):
    rounds = 20
    dsts = np.linspace(10, 50, 17)
    df = pd.DataFrame(index=range(0, len(dsts)), columns=[
        'dst', 'F_avg', 'F_min', 'F_max', 'iters', 'f'
    ])

    for i, dst in enumerate(tqdm(dsts)):
        F_last = F_this = 0
        F_avg = F_min = F_max = 0
        f = 0
        iterations = 0
        while F_last <= F_this:
            net, alice, bob = create_head_nodes(config, 'Quantum Network')
            direct = create_cfibre(config, dst, 'AlcBobDIR')
            connect_nodes(net, alice, 'cdir', bob, 'cdir', direct)
            alice_link, bob_link = create_link_with_insertion(config, dst, net, alice, bob)

            alice_purify = LadderPurify(alice, 'cdir', iterations, True, 2, log.Layer.LINK, 'AlcPUR')
            alice_linkpurify = LinkWithPurification(
                alice, alice_purify, alice_link, name='AlcLINKPUR')

            bob_purify = LadderPurify(bob, 'cdir', iterations, False, 2, log.Layer.LINK, 'BobPUR')
            bob_linkpurify = LinkWithPurification(
                bob, bob_purify, bob_link, name='BobLINKPUR')

            logger = PurifyStatLogger(
                alice, bob, alice_linkpurify, bob_linkpurify, rounds, f'greedy_{dst}')
            logger.start()

            ns.sim_run()
            ns.sim_reset()
            iterations += 1
            F_last = F_this
            F_this = np.average(logger.F)
            print(f'Finished iteration {iterations}: {F_this}')
            if F_this > F_avg:
                F_avg, F_min, F_max = F_this, np.min(logger.F), np.max(logger.F)
                f = rounds / logger.T
        df.iloc[i] = [dst, F_avg, F_min, F_max, iterations-1, f]
        df.to_csv('data/maxF_dst2.csv', index=False)



def test(config):
    #iterations = 7
    dst = 10
    rounds = 1

    net, alice, bob = create_head_nodes(config, 'Quantum Network')
    direct = create_cfibre(config, dst, 'AlcBobDIR')
    connect_nodes(net, alice, 'cdir', bob, 'cdir', direct)
    alice_link, bob_link = create_link_with_insertion(config, dst, net, alice, bob)

    alice_purify = MixedPurify(alice, 'cdir', 4, 2, True, 2, log.Layer.LINK, 'AlcPUR')
    alice_linkpurify = LinkWithPurification(
        alice, alice_purify, alice_link, name='AlcLINKPUR')

    bob_purify = MixedPurify(bob, 'cdir', 4, 2, False, 2, log.Layer.LINK, 'BobPUR')
    bob_linkpurify = LinkWithPurification(
        bob, bob_purify, bob_link, name='BobLINKPUR')

    logger = PurifyStatLogger(
        alice, bob, alice_linkpurify, bob_linkpurify, rounds, f'greedy_{dst}')
    logger.start()

    ns.sim_run()
    ns.sim_reset()


def test_mixed(config):
    dst = 20
    mixiters = [(6,1), (2,2), (3,2), (4,2)]

    for liter, giter in mixiters:
        net, alice, bob = create_head_nodes(config, 'Quantum Network')
        direct = create_cfibre(config, dst, 'AlcBobDIR')
        connect_nodes(net, alice, 'cdir', bob, 'cdir', direct)
        alice_link, bob_link = create_link_with_insertion(config, dst, net, alice, bob)

        alice_purify = LadderPurify(alice, 'cdir', liter, True, 2, log.Layer.LINK, 'AlcPUR')
        alice_linkpurify = LinkWithPurification(
            alice, alice_purify, alice_link, name='AlcLINKPUR')

        bob_purify = LadderPurify(bob, 'cdir', liter, False, 2, log.Layer.LINK, 'BobPUR')
        bob_linkpurify = LinkWithPurification(
            bob, bob_purify, bob_link, name='BobLINKPUR')

        logger = PurifyStatLogger(
            alice, bob, alice_linkpurify, bob_linkpurify, 10, f'greedy_{dst}')
        logger.start()

        ns.sim_run()
        ns.sim_reset()
        print(f'{liter}/{giter}', np.average(logger.F), 10/logger.T)


if __name__ == '__main__':
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.INFO, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)
    config = read_config('netconf/testvalues')

    max_fidelity(config)
