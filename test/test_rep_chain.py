

import netsquid as ns
import logging
import os
from netsquid.nodes import Network
from netsquid.qubits.qformalism import QFormalism
from netsquid.util.simtools import MILLISECOND

from simlog import log
from mock.trans_mock import MockTransportLayer
from rep_net_setup import *


def test_net_layer():
    if not os.path.exists('log'):
        os.makedirs('log')

    log.init(logging.INFO, log.TimeUnit.MICROSECONDS)
    ns.set_qstate_formalism(QFormalism.DM)
    ns.logger.setLevel(logging.INFO)

    net = Network('Quantum Network')

    (alice, alice_net), (bob, bob_net) = create_rep_chain(net, 4)
    trans_mock = MockTransportLayer(alice, bob, alice_net, bob_net, name='MockLinkLayer')

    trans_mock.start()
    ns.sim_run(10*MILLISECOND)
