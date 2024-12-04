
import logging
import os
import sys
import pandas as pd
import numpy as np
from tqdm import tqdm
from netsquid.qubits.qformalism import QFormalism
import json

from components.protocols.link.link_purification import LinkWithPurification
from components.protocols.purify import *
from components.protocols.net import NetWithPurification
from prep_net import *
from config_reder import *
from sim_net_purify import NetStateLogger


def qkd():
    nl, ng, ll, lg = 1, 1, 1, 1
    dst = 60
    count = 3
    rounds = 2

    net, alice, bob = create_head_nodes(config, 'Quantum Network')
    alice_net, bob_net = connect_with_rep_chain(
        config, net, alice, bob, dst, count,
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

    logger = NetStateLogger(
        alice, bob, alice_netpurify, bob_netpurify, rounds, 'NetStateLogger'
    )
    logger.start()

    ns.sim_run()
    with open('data/qkd.json', 'w') as f:
        json.dump(
            {
                'simtime': ns.sim_time(),
                'alice': {
                    'usage': alice.qmemory.usage_info,
                    'timeline': list(alice.qmemory.usage_timeline)
                },
                'bob': {
                    'usage': bob.qmemory.usage_info,
                    'timeline': list(bob.qmemory.usage_timeline)
                }
            },
            fp=f,
            indent=2
        )
    ns.sim_reset()


if __name__ == '__main__':
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.CRITICAL, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)
    config = read_config('netconf/testvalues')

    qkd()
