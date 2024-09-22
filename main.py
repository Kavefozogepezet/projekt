
import netsquid as ns
import logging
from netsquid.nodes import Network
from netsquid.nodes import Node
from netsquid.components import QuantumProcessor
from netsquid.qubits.qformalism import QFormalism
from netsquid.util.simtools import MICROSECOND, MILLISECOND
from netsquid.components.models.qerrormodels import T1T2NoiseModel

from components.protocols import log, Clock, SwapWithBSA, BSAProtocol, PhysicalState
from components.hardware import QuantumFibre, ClassicalFibre
from components.nodes import BSANode


def main():
    log.init(logging.INFO)
    ns.set_qstate_formalism(QFormalism.DM)

    net = Network('Quantum Network')
    
    alice = Node(
        name='Alice',
        port_names=['qout', 'cin'],
        qmemory=QuantumProcessor(
            name='alice_memory',
            num_positions=2,
            mem_noise_models=T1T2NoiseModel(T1=1*MILLISECOND, T2=100*MICROSECOND),
            fallback_to_nonphysical=True
        )
    )
    bob = Node(
        name='Bob',
        port_names=['qout', 'cin'],
        qmemory=QuantumProcessor(
            name='bob_memory',
            num_positions=2,
            fallback_to_nonphysical=True
        )
    )
    bsa = BSANode(name='BSA')

    clock = Clock(delta_time=20*MICROSECOND, nodes=[alice, bob, bsa])

    qA2BSA = QuantumFibre('Alice-BSA_quantum', 2)
    qB2BSA = QuantumFibre('Bob-BSA_quantum', 2)

    cA2BSA = ClassicalFibre('Alice-BSA_classical', 2)
    cB2BSA = ClassicalFibre('Bob-BSA_classical', 2)

    net.add_nodes([alice, bob, bsa])
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

    alice_proto = SwapWithBSA(alice, clock)
    bob_proto = SwapWithBSA(bob, clock)
    bsa_proto = BSAProtocol(bsa, clock, detection_offset=9*MICROSECOND, detection_window=1*MICROSECOND)

    alice_proto.set_state(PhysicalState.GENERATING)
    bob_proto.set_state(PhysicalState.GENERATING)

    bsa_proto.start()
    alice_proto.start()
    bob_proto.start()
    clock.start()

    ns.sim_run(200*MICROSECOND)


if __name__ == '__main__':
    main()
