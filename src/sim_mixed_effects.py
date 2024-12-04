
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
from sim_link_purify import PurifyStatLogger

def main(config):
    rounds = 500
    dst = 30
    liter = 3
    giters = range(1, 4)
    df = pd.DataFrame(index=range(0, rounds), columns=[
        f'{value}{giter}' for giter in giters for value in ['F', 'dt']
    ])
        
    for giter in range(1, 4):
        net, alice, bob = create_head_nodes(config, 'Quantum Network')
        direct = create_cfibre(config, dst, 'AlcBobDIR')
        connect_nodes(net, alice, 'cdir', bob, 'cdir', direct)
        alice_link, bob_link = create_link_with_insertion(config, dst, net, alice, bob)

        alice_purify = MixedPurify(alice, 'cdir', liter, giter, True, 2, log.Layer.LINK, 'AlcPUR')
        alice_linkpurify = LinkWithPurification(
            alice, alice_purify, alice_link, name='AlcLINKPUR')

        bob_purify = MixedPurify(bob, 'cdir', liter, giter, False, 2, log.Layer.LINK, 'BobPUR')
        bob_linkpurify = LinkWithPurification(
            bob, bob_purify, bob_link, name='BobLINKPUR')

        logger = PurifyStatLogger(
            alice, bob, alice_linkpurify, bob_linkpurify, rounds, f'greedy_{dst}')
        logger.start()

        ns.sim_run()
        ns.sim_reset()

        F_avg = np.average(logger.F)

        df[f'F{giter}'] = logger.F
        df[f'dt{giter}'] = logger.t

        print(f'Finished iteration {giter}: {F_avg}')
        df.to_csv('data/mixed_effect_l3.csv', index=False)


if __name__ == '__main__':
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.INFO, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)
    config = read_config('netconf/testvalues')

    main(config)
