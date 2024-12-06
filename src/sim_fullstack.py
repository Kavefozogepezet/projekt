
import os
import sys
import json
import logging
import pandas as pd
import numpy as np
from tqdm import tqdm
from netsquid.qubits.qformalism import QFormalism
from netsquid.qubits.dmtools import DenseDMRepr
from netsquid.qubits import create_qubits, assign_qstate

from components.protocols.link.link_purification import LinkWithPurification
from components.protocols.purify import *
from components.protocols.net import NetWithPurification
from components.protocols.trans import *
from components.protocols.app import *
from prep_net import *
from config_reder import *
from sim_net_purify import NetStateLogger
from sim_spawn import *


class TransportLogger (LocalProtocol):
    def __init__(self, node1, node2, trans1, trans2, rounds, part1, name):
        super().__init__(
            dict(node1=node1, node2=node2),
            name
        )
        self.add_subprotocol(trans1, name='net1')
        self.add_subprotocol(trans2, name='net2')
        self.trans1 = trans1
        self.trans2 = trans2
        self.node1 = node1
        self.node2 = node2
        self.rounds = rounds
        self.part1 = part1

    def run(self):
        self.start_subprotocols()
        req1 = self.trans1.transmit(TransportMethod.PULL, self.rounds)
        req2 = self.trans2.recieve()

        round = 0
        while round < self.rounds:
            ev1 = req1.resp_event(self)
            ev2 = req2.resp_event(self)

            expr = yield ev1 | ev2
            if expr.first_term.value:
                resp = req1.get_answare(self)
                [q] = self.node1.qmemory.allocate(1, self.part1)
                dm = np.mat([
                    [0.5, 0],
                    [0, 0.5]
                ], dtype=np.complex128)
                repr = DenseDMRepr(dm=dm)
                qubits = create_qubits(1)
                assign_qstate(qubits, repr)
                self.node1.qmemory.put(qubits, [q])
                resp.transmit(q)
            else:
                resp = req2.get_answare(self)
                pos = resp.position
                [q] = self.node2.qmemory.peek([pos])
                print(f'Round #{round+1}/{self.rounds}', q.qstate.qrepr)
                self.node2.qmemory.destroy([pos])
                round += 1

        ns.sim_stop()


def tobin(arr):
    return ''.join(map(str, arr))


class QKDLogger (LocalProtocol):
    def __init__(self, node1, node2, qkd1, qkd2, length, name):
        super().__init__(
            dict(node1=node1, node2=node2),
            name
        )
        self.add_subprotocol(qkd1, name='net1')
        self.add_subprotocol(qkd2, name='net2')
        self.qkd1 = qkd1
        self.qkd2 = qkd2
        self.node1 = node1
        self.node2 = node2
        self.length = length

    def run(self):
        self.start_subprotocols()
        start_time = ns.sim_time()
        req1 = self.qkd1.generate_key(self.length)
        req2 = self.qkd2.recieve_key(self.length)

        resp1, resp2 = yield from ProtocolRequest.await_all(self, req1, req2)
        self.key1 = resp1.key
        self.key2 = resp2.key
        self.duration = ns.sim_time() - start_time
        self.duration /= SECOND
        ns.sim_stop()


def base_net(config, dst, repeaters, nl, ng, ll, lg, apppart=1):
    net, alice, bob = create_head_nodes(config, 'Quantum Network')
    alice_net, bob_net = connect_with_rep_chain(
        config, net, alice, bob, dst, repeaters,
        reserve_on_nodes=apppart,
        net_cutoff=0.5*SECOND,
        link_setup=lambda n1,l1,p1,n2,l2,p2: (
            LinkWithPurification(n1,
                MixedPurify(n1, p1, ll, lg, True, 2, log.Layer.LINK, f'{n1.name}PUR', 'linkpuri'),
                l1, name=f'{n1.name}LINKPUR'
            ),
            LinkWithPurification(n2,
                MixedPurify(n2, p2, ll, lg, False, 2, log.Layer.LINK, f'{n2.name}PUR', 'linkpuri'),
                l2, name=f'{n2.name}LINKPUR'
            )
        ),
        app_headers=[
            BB84Protocol.MSG_HEADER,
            TransportLayer.MSG_HEADER,
            NetWithPurification.PURIFY_HEADER,
            DEJMPSProtocol.get_header(log.Layer.NETWORK)
        ]
    )

    alice_purify = MixedPurify(alice, 'cdir', nl, ng, True, 2, log.Layer.NETWORK, 'AlcNPUR', 'netpuri')
    alice_netpurify = NetWithPurification(
        alice, 'cdir', alice_purify, alice_net, name='AlcNETPUR')

    bob_purify = MixedPurify(bob, 'cdir', nl, ng, False, 2, log.Layer.NETWORK, 'BobNPUR', 'netpuri')
    bob_netpurify = NetWithPurification(
        bob, 'cdir', bob_purify, bob_net, name='BobNETPUR')

    alice_trans = TeleportProtocol(alice, 'cdir', alice_netpurify, name='AlcTRANS')
    bob_trans = TeleportProtocol(bob, 'cdir', bob_netpurify, name='BobTRANS')
    return net, alice, alice_trans, bob, bob_trans


def export_proc(net, name):
    with open(f'data/{name}.json', 'w') as f:
        jsondict = {
            'simtime': ns.sim_time(),
            'nodes': list(),
        }
        for node in net.nodes.values():
            jsondict['nodes'].append(
                {
                    'name': node.name,
                    'usage': node.qmemory.usage_info,
                    'timeline': list(node.qmemory.usage_timeline)
                }
            )
        json.dump(
            jsondict,
            fp=f,
            indent=2
        )

def teleport(config):
    nl, ng, ll, lg = 1, 1, 1, 1
    dst = 60
    count = 3
    rounds = 50

    net, alice, alice_trans, bob, bob_trans = base_net(
        config, dst, count, nl, ng, ll, lg
    )

    logger = TransportLogger(
        alice, bob, alice_trans, bob_trans, rounds,
        alice.qmemory.centre_partition()[-1:], 'TransportLogger'
    )
    logger.start()

    ns.sim_run()
    export_proc(net, 'teleport')
    ns.sim_reset()

def qkd_proc(config):
    nl, ng, ll, lg = 3, 1, 3, 1
    dst = 60
    count = 3
    length = 20

    net, alice, alice_trans, bob, bob_trans = base_net(
        config, dst, count, nl, ng, ll, lg, 2
    )
    partition = alice.qmemory.centre_partition()[-2:]
    alice_qkd = BB84Protocol(alice, 'cdir', alice_trans, partition, name='AlcQKD')
    bob_qkd = BB84Protocol(bob, 'cdir', bob_trans, name='BobQKD')

    logger = QKDLogger(alice, bob, alice_qkd, bob_qkd, length, 'QKDLogger')
    logger.start()

    ns.sim_run()
    export_proc(net, 'qkd_proc')
    ns.sim_reset()

def qkdsim(lock, config, seed, reps, pconf, length):
    simulation(lock, formalism=QFormalism.KET)
    np.random.seed(seed)
    (nl, ng, ll, lg) = pconf
    dst = 60

    net, alice, alice_trans, bob, bob_trans = base_net(
        config, dst, reps, nl, ng, ll, lg, 2
    )
    partition = alice.qmemory.centre_partition()[-2:]
    alice_qkd = BB84Protocol(alice, 'cdir', alice_trans, partition, name='AlcQKD')
    bob_qkd = BB84Protocol(bob, 'cdir', bob_trans, name='BobQKD')

    logger = QKDLogger(alice, bob, alice_qkd, bob_qkd, length, 'QKDLogger')
    logger.start()

    ns.sim_run()
    with lock:
        with open(f'data/qkd/key_{reps}_{nl}-{ng}+{ll}-{lg}.json', 'a') as f:
            print(f'''  {{
    "key_length": {len(logger.key1)},
    "duration": {logger.duration},
    "key1":   "{tobin(logger.key1)}",
    "key2":   "{tobin(logger.key2)}",
    "errors": "{tobin(logger.key1 ^ logger.key2)}"
  }},''', file=f)
    ns.sim_reset()


def repeati(it, ns):
    for i, n in zip(it, ns):
        for _ in range(n):
            yield i


def qkd_init():
    config = read_config('netconf/testvalues')
    if not os.path.exists('data/qkd'):
        os.makedirs('data/qkd')

    reps = [
        # 2+3  | 3+3 | 2/2+3
        3, 4, 5, 3   , 3
    ]
    pconfs = [
        (2, 1, 3, 1),
        (2, 1, 3, 1),
        (2, 1, 3, 1),
        (3, 1, 3, 1),
        (2, 2, 3, 1)
    ]
    iters = [
        0, 0, 0, 1, 1
    ]

    #for rep, pconf in zip(reps, pconfs):
    #    (nl, ng, ll, lg) = pconf
    #    with open(f'data/qkd/key_{rep}_{nl}-{ng}+{ll}-{lg}.json', 'w') as f:
    #        print('[', file=f)
    spawner = SimulationSpawner(qkdsim, 2)
    spawner.run(
        repeat(config),
        np.random.randint(0, 2**32, len(reps)*10),
        repeati(reps, iters),
        repeati(pconfs, iters),
        repeat(50)
    )
    for rep, pconf in zip(reps, pconfs):
        (nl, ng, ll, lg) = pconf
        with open(f'data/qkd/key_{rep}_{nl}-{ng}+{ll}-{lg}.json', 'a') as f:
            print(']', file=f)

if __name__ == '__main__':
    config = read_config('netconf/testvalues')
    ns.set_qstate_formalism(QFormalism.KET)
    qkd_proc(config)
