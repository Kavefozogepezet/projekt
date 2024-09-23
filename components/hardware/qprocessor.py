
from netsquid.nodes import Node
from netsquid.components import QuantumProcessor
from netsquid.components.qmemory import QuantumMemoryError
from netsquid.components.models.qerrormodels import T1T2NoiseModel

from simlog import log


class QProcessor (QuantumProcessor):
    def __init__(self, name, size, T1, T2, **kwargs):
        super().__init__(
            name=name,
            num_positions=size,
            mem_noise_models=T1T2NoiseModel(T1, T2),
            **kwargs
        )
        self.size = size
        self.qubits = [None] * size

    def photon_pos(self):
        return len(self.mem_positions) - 1
    
    def pop_photon(self):
        return self.pop(self.photon_pos())

    def allocate(self, count):
        if count > self.size:
            raise ValueError('Not enough space in quantum processor.')
        if count == 0:
            return []
        
        allocated = []
        for i, mem in enumerate(self.mem_positions[:-1]):
            if not mem.in_use:
                allocated.append(i)
                mem.in_use = True
                count -= 1
            if count == 0:
                log.info(f'Allocated qubits at positions {allocated}', at=self)
                return allocated
        
        raise QuantumMemoryError('Not enough space in quantum processor.')
    
    def deallocate(self, qubits):
        for q in qubits:
            self.mem_positions[q].in_use = False
        log.info(f'Deallocated qubits at positions {qubits}', at=self)

    def destroy(self, qubits):
        self.discard(qubits)
        log.info(f'Destroyed qubits at positions {qubits}', at=self)
