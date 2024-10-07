
from enum import Enum
from netsquid.nodes import Node
from netsquid.components import QuantumProcessor
from netsquid.components.qmemory import QuantumMemoryError
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from netsquid.components.qprogram import QuantumProgram
from netsquid.protocols import Protocol

from simlog import log


class ProgramPriority (Enum):
    REAL_TIME = 1
    HIGH = 2
    LOW = 3


def program_function(num_qubits, priority):
    def program_function_decorator(prog_func):
        def program_executor(self, qubit_mapping, *args, **kwargs):
            prog = QuantumProgram(num_qubits)
            qindices = prog.get_qubit_indices(num_qubits)
            prog_func(self, prog, qindices, *args, **kwargs)
            # TODO rewrite when OpticalNode is implemented
            yield from self.node.qmemory.schedule_program(prog, priority, qubit_mapping)
            return prog.output
        return program_executor
    return program_function_decorator


class QProcessor (QuantumProcessor):
    def __init__(self, name, size, T1, T2, scheduler_dt=0.1, **kwargs):
        super().__init__(
            name=name,
            num_positions=size+1,
            mem_noise_models=T1T2NoiseModel(T1, T2),
            **kwargs
        )
        self.log_layer = log.Layer.PHYSICAL
        self.scheduler_dt = scheduler_dt
        self.size = size
        for mem in self.mem_positions:
            mem.in_use_event_enabled = True

    def schedule_program(self, program, priority, qubit_mapping):
        while self.busy:
            end_time = self.sequence_end_time
            end_time += self.scheduler_dt * priority.value
            log.info(f'Program execution delayed until {end_time}', at=self)
            yield Protocol().await_timer(end_time=end_time)
        yield self.execute_program(
            program, qubit_mapping=qubit_mapping
        )
        return program.output

    def photon_pos(self):
        return len(self.mem_positions) - 1
    
    def pop_photon(self):
        return self.pop(self.photon_pos())

    def allocate(self, count=1, partition=None):
        if partition: positions = partition
        else: positions = range(self.size)

        if count > len(positions):
            raise QuantumMemoryError('Not enough space in partition.')
        if count == 0:
            return []
        
        allocated = []
        for pos in positions:
            mem = self.mem_positions[pos]
            if not mem.in_use:
                allocated.append(pos)
                mem.in_use = True
                count -= 1
            if count == 0:
                log.info(f'Allocated qubits at positions {allocated}', at=self)
                return allocated
        
        raise QuantumMemoryError('Not enough free space in quantum processor.')
    
    def deallocate(self, qubits):
        for q in qubits:
            self.mem_positions[q].in_use = False
        log.info(f'Deallocated qubits at positions {qubits}', at=self)

    def destroy(self, qubits):
        self.discard(qubits)
        log.info(f'Destroyed qubits at positions {qubits}', at=self)
