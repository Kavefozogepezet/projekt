
from netsquid.nodes import Node
from netsquid.components.qmemory import QuantumMemory


class BSANode (Node):
    def __init__ (self, name, ID=None):
        super().__init__(
            name=name,
            ID=ID,
            port_names=['qinA', 'coutA', 'qinB', 'coutB'],
            qmemory=QuantumMemory(
                name=f'{name}_qmemory',
                num_positions=2
            )
        )
        self.ports['qinA'].forward_input(self.qmemory.ports['qin0'])
        self.ports['qinB'].forward_input(self.qmemory.ports['qin1'])
