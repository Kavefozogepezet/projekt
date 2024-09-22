from netsquid.components.qprocessor import QuantumProcessor
from netsquid.components.qprogram import QuantumProgram
from netsquid.components.instructions import INSTR_INIT, INSTR_CNOT, INSTR_H, INSTR_X, INSTR_Z, INSTR_MEASURE, INSTR_MEASURE_X
from netsquid.components.models.qerrormodels import DepolarNoiseModel, T1T2NoiseModel
from netsquid.components.models.delaymodels import FibreDelayModel
from netsquid.components.qchannel import QuantumChannel
from netsquid.components.cchannel import ClassicalChannel
from netsquid.nodes.connections import Connection
from netsquid.nodes import Node, Network
from netsquid.protocols import NodeProtocol
import netsquid as ns
import numpy as np
import logging

ns.set_qstate_formalism(ns.QFormalism.DM)


class QuantumFibre (Connection):
    def __init__ (self, name, length, attenuation):
        super().__init__(name)
        qchannel = QuantumChannel(
            f'{name}_qchannel',
            length=length,
            models={
                "quantum_noise_model": DepolarNoiseModel(
                    time_independent=True,
                    depolar_rate=(1 - np.exp(-attenuation*length) )
                ),
                "delay_model": FibreDelayModel()
            }
        )
        self.add_subcomponent(
            qchannel, name="qchannel",
            forward_input=[('A', 'send')],
            forward_output=[('B', 'recv')],
        )


class ClassicalFibre (Connection):
    def __init__ (self, name, length):
        super().__init__(name)
        cchannel = ClassicalChannel(
            f'{name}_channel',
            length=length,
            models={
                "delay_model": FibreDelayModel()
            }
        )
        self.add_subcomponent(
            cchannel, name="cchannel",
            forward_input=[('A', 'send')],
            forward_output=[('B', 'recv')],
        )


class RepeaterProcessor (QuantumProcessor):
    def __init__ (self, name, num_positions, T1, T2):
        super().__init__(
            name,
            num_positions=num_positions,
            mem_noise_models=[T1T2NoiseModel(T1, T2)] * 2,
            fallback_to_nonphysical=True    
        )


class BSMeasureProgram (QuantumProgram):
    def program (self):
        [q1, q2] = self.get_qubit_indices(2)
        self.apply(INSTR_CNOT, [q1, q2])
        self.apply(INSTR_MEASURE_X, q1, output_key="z_control", discard=True)
        self.apply(INSTR_MEASURE, q2, output_key="x_control", discard=True)
        yield self.run()


class InitEntanglementProgram (QuantumProgram):
    def program (self):
        [q1, q2] = self.get_qubit_indices(2)
        self.apply(INSTR_INIT, [q1, q2])
        self.apply(INSTR_H, q1)
        self.apply(INSTR_CNOT, [q1, q2])
        yield self.run()


class ExecuteCorrectionProgram (QuantumProgram):
    def __init__(self, name, x_ctrl=False, z_ctrl=False):
        super().__init__(name)
        self.x_ctrl = x_ctrl
        self.z_ctrl = z_ctrl

    def set_controls (self, msg):
        self.x_ctrl = msg["x_control"] if "x_control" in msg else False
        self.z_ctrl = msg["z_control"] if "z_control" in msg else False

    def program(self):
        [q] = self.get_qubit_indices(1)
        if self.x_ctrl:
            self.apply(INSTR_X, q)
        if self.z_ctrl:
            self.apply(INSTR_Z, q)
        yield self.run()


class EntanglementSwappingProtocol (NodeProtocol):
    def run (self):
        init = InitEntanglementProgram()
        yield self.node.qmemory.execute_program(init)
        [photon] = self.node.qmemory.pop(1)
        print(photon.qstate.qrepr, "->", self.node.name)
        self.node.ports['qout'].tx_output(photon)
        yield self.await_port_input(self.node.ports['cin'])
        print("VALUE", self.node.ports['cin'].rx_input().items[0])


class BSMeasureProtocol (NodeProtocol):
    def run (self):
        program = BSMeasureProgram()
        yield (self.await_port_input(self.node.ports['a_qin']) &
               self.await_port_input(self.node.ports['b_qin']))
        print(self.node.qmemory.peek(0)[0].qstate.qrepr, "->", self.node.name)
        yield self.node.qmemory.execute_program(program)
        [xctrl], [zctrl] = program.output['x_control'], program.output['z_control']
        self.node.ports['a_cout'].tx_output({"x_control": xctrl == 1})
        self.node.ports['b_cout'].tx_output({"z_control": zctrl == 1})


def create_network():
    ns.util.simlog.logger.setLevel(logging.DEBUG)

    net = Network("Quantum Repeater Network")
    alice = Node("Alice",
        port_names=["qout", "cin"],
        qmemory=RepeaterProcessor("alice_processor", 2, 0.001, 0.001),
    )
    bob = Node("Bob",
        port_names=["qout", "cin"],
        qmemory=RepeaterProcessor("alice_processor", 2, 0.001, 0.001),
    )
    bsa = Node("BSA",
        port_names=["a_qin", "b_qin", "a_cout", "b_cout"],
        qmemory=QuantumProcessor("bsa_processor", 2, fallback_to_nonphysical=True),
    )
    bsa.ports['a_qin'].forward_input(bsa.qmemory.ports['qin0'])
    bsa.ports['b_qin'].forward_input(bsa.qmemory.ports['qin1'])
    net.add_nodes([alice, bob, bsa])

    q_alice_bsa = QuantumFibre("q_alice_bsa", 0, 0)
    c_bsa_alice = ClassicalFibre("c_bsa_alice", 0)

    q_bob_bsa = QuantumFibre("q_bob_bsa", 0, 0)
    c_bsa_bob = ClassicalFibre("c_bsa_bob", 0)

    net.add_connection(alice, bsa, q_alice_bsa, port_name_node1="qout", port_name_node2="a_qin")
    net.add_connection(bsa, alice, c_bsa_alice, port_name_node1="a_cout", port_name_node2="cin")
    net.add_connection(bob, bsa, q_bob_bsa, port_name_node1="qout", port_name_node2="b_qin")
    net.add_connection(bsa, bob, c_bsa_bob, port_name_node1="b_cout", port_name_node2="cin")

    prot_a = EntanglementSwappingProtocol(alice)
    prot_b = EntanglementSwappingProtocol(bob)
    prot_bsa = BSMeasureProtocol(bsa)

    prot_a.start()
    prot_b.start()
    prot_bsa.start()

    stats = ns.sim_run()
    print(stats)
    [q1], [q2] = alice.qmemory.peek(0), bob.qmemory.peek(0)
    print(ns.qubits.reduced_dm([q1, q2]))


create_network()
