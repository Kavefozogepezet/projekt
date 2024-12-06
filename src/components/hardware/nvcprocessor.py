
import numpy as np
from enum import Enum
import netsquid as ns
from netsquid.nodes import Node
from netsquid.components import QuantumProcessor
from netsquid.components.qmemory import QuantumMemoryError
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from netsquid.components.qprogram import QuantumProgram
from netsquid.protocols import Protocol
from netsquid.components.instructions import *
from netsquid.components.qprocessor import PhysicalInstruction
from netsquid.components.models.qerrormodels import DepolarNoiseModel, QuantumErrorModel
from netsquid.qubits import qubitapi as qapi
from netsquid.qubits.operators import X as X_op
from collections import defaultdict, deque


from simlog import log


class ProgramPriority (Enum):
    REAL_TIME = 1
    HIGH = 2
    LOW = 3


def program_function(num_qubits, priority, reason=None):
    def program_function_decorator(prog_func):
        def program_executor(self, qubit_mapping, *args, **kwargs):
            _reason = (
                reason if reason is not None
                else self.prog_reason if hasattr(self, 'prog_reason')
                else 'other'
            )
            prog = QuantumProgram(num_qubits)
            qindices = prog.get_qubit_indices(num_qubits)
            prog_func(self, prog, qindices, *args, **kwargs)
            yield from self.node.qmemory.schedule_program(prog, priority, qubit_mapping, _reason)
            return prog.output
        return program_executor
    return program_function_decorator


class BitFlipNoise (QuantumErrorModel):
    def __init__(self, error_rate):
        super().__init__()
        self.error_rate = error_rate

    def error_operation(self, qubits, delta_time=None, **_):
        for q in qubits:
            qapi.apply_pauli_noise(q, (1-self.error_rate, self.error_rate, 0, 0))


class NVCProcessor (QuantumProcessor):
    def __init__(self,
        T1, T2, num_in_centre,
        t_gate, t_CX, t_init, t_readout,
        F_gate=1, F_CX=1, F_init=1, F_readout=1,
        centre_count=1, F_iCX=None, t_iCX=None,
        scheduler_dt=0.1, name=None, **kwargs
    ):
        num_qubits = centre_count * (num_in_centre + 1)
        num_mem = centre_count * num_in_centre

        gate_model = (
            None if F_gate == 1
            else DepolarNoiseModel(
                time_independent=True,
                depolar_rate=1-F_gate
            )
        )
        instr = [
            # PHOTON
            PhysicalInstruction(
                INSTR_INIT, duration=0, parallel=True,
                topology=list(range(num_mem, num_qubits))
            ),
            PhysicalInstruction(
                INSTR_CNOT, duration=0, parallel=True,
                topology=[
                    (i*num_in_centre+q, num_mem+i)
                    for i in range(centre_count)
                    for q in range(num_in_centre)
                ]
            ),
            # INTRA CENTRE
            PhysicalInstruction(
                INSTR_INIT, duration=t_init, parallel=False,
                topology=list(range(num_mem)),
                quantum_noise_model=
                    None if F_init == 1
                    else DepolarNoiseModel(
                        time_independent=True,
                        depolar_rate=1-F_init
                    )
            )
        ] + [
            PhysicalInstruction(
                gate, duration=t_gate, parallel=False,
                topology=list(range(num_mem)),
                quantum_noise_model=gate_model
            )
            for gate in [
                INSTR_X, INSTR_Y, INSTR_Z, INSTR_H,
                INSTR_ROT_X, INSTR_ROT_Y, INSTR_ROT_Z, INSTR_ROT
            ]
        ] + [
            PhysicalInstruction(
                INSTR_CNOT, duration=t_CX, parallel=False,
                topology=[
                    (c*num_in_centre+i, c*num_in_centre+j)
                    for c in range(centre_count)
                    for i in range(num_in_centre)
                    for j in range(num_in_centre)
                    if i != j
                ],
                quantum_noise_model=
                    None if F_CX == 1
                    else DepolarNoiseModel(
                        time_independent=True,
                        depolar_rate=1-F_CX
                    )
            ),
            PhysicalInstruction(
                INSTR_MEASURE, duration=t_readout, parallel=False,
                topology=list(range(num_mem)),
                quantum_noise_model=BitFlipNoise(1-F_readout),
                apply_q_noise_after=False,
            ),
            # INTER CENTRE
            PhysicalInstruction(
                INSTR_CNOT, duration=t_iCX, parallel=False,
                topology=[
                    (c1*num_in_centre+i, c2*num_in_centre+j)
                    for c1 in range(centre_count)
                    for c2 in range(centre_count)
                    if c1 != c2
                    for i in range(num_in_centre)
                    for j in range(num_in_centre)
                ],
                quantum_noise_model=
                    None if F_iCX == 1
                    else DepolarNoiseModel(
                        time_independent=True,
                        depolar_rate=1-F_iCX
                    )
            )
        ]

        super().__init__(
            name=name,
            num_positions=centre_count*(num_in_centre+1),
            mem_noise_models=T1T2NoiseModel(T1, T2),
            phys_instructions=instr,
            #fallback_to_nonphysical=True,
            **kwargs
        )
        self.log_layer = log.Layer.PHYSICAL
        self.scheduler_dt = scheduler_dt
        self.size = num_in_centre * centre_count
        self.num_in_centre = num_in_centre
        self.centre_count = centre_count
        self.busy_subscribers = []
        self.usage_info = defaultdict(int)
        self.usage_timeline = deque()
        for mem in self.mem_positions:
            mem.in_use_event_enabled = True

    def add_busy_subscriber(self, callback):
        self.busy_subscribers.append(callback)

    def remove_busy_subscriber(self, callback):
        self.busy_subscribers.remove(callback)

    def schedule_program(self, program, priority, qubit_mapping, reason):
        while self.busy:
            end_time = self.sequence_end_time
            end_time += self.scheduler_dt * priority.value
            log.info(f'Program execution delayed until {end_time}', at=self)
            yield Protocol().await_timer(end_time=end_time)
        prog_ev = self.execute_program(
            program, qubit_mapping=qubit_mapping
        )
        self.register_usage(
            reason, ns.sim_time(),
            self.sequence_end_time - ns.sim_time()
        )
        for callback in self.busy_subscribers:
            callback()
        yield prog_ev
        return program.output
    
    def register_usage(self, reason, start, duration):
        pass
        self.usage_info[reason] += duration
        self.usage_timeline.append((start, duration, reason))

    def photon_pos(self, centre=0):
        return self.num_in_centre * self.centre_count + centre
    
    def centre_partition(self, centre=0):
        return list(range(
            centre*self.num_in_centre,
            (centre+1)*self.num_in_centre
        ))
    
    def memory_positions(self):
        return list(range(self.size))
    
    def pop_photon(self, centre=0):
        return self.pop(self.photon_pos(centre))

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
        if not qubits:
            return
        for q in qubits:
            self.mem_positions[q].in_use = False
        log.info(f'Deallocated qubits at positions {qubits}', at=self)

    def destroy(self, qubits):
        if not qubits:
            return
        self.discard(qubits)
        log.info(f'Destroyed qubits at positions {qubits}', at=self)
