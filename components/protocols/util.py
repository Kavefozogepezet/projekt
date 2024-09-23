
import inspect
from netsquid.protocols import LocalProtocol
from netsquid.components.qprogram import QuantumProgram
from abc import ABCMeta as Abstract, abstractmethod

from components.hardware import SPEED_OF_LIGHT
from simlog import log


def program_function(**program_kwargs):
    class ProgExecutor:
        def __init__(self, node, prog):
            self.prog = prog
            self.node = node
            self.mapping = None

        def on(self, mapping):
            self.mapping = mapping
            yield self.node.qmemory.execute_program(
                self.prog, qubit_mapping=self.mapping
            )

    def program_function_decorator(prog_func):
        def program_executor(self, *args, **kwargs):
            prog = QuantumProgram(**program_kwargs)
            qindices = prog.get_qubit_indices(program_kwargs['num_qubits'])
            prog_func(self, prog, qindices, *args, **kwargs)
            return ProgExecutor(self.node, prog)
        return program_executor
    return program_function_decorator


def protocolstate(*states, initial=False, final=False):
    def decorator(func):
        func.__states__ = states
        func.__initial__ = initial
        func.__final__ = final
        return func
    return decorator


def StatefulProtocolTempalte(BaseType):
    class StatefulProtocol (BaseType, metaclass=Abstract):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._sm = self.create_statemachine()

        @abstractmethod
        def create_statemachine(self):
            pass

        def run(self):
            yield from self._sm.run()

        def set_state(self, state):
            self._sm.set_state(state)

        def get_state(self):
            return self._sm.get_state()
        
    return StatefulProtocol


class ProtocolStateMachine:
    def __init__(self, protocol):
        self._state_handlers = dict()
        self._state = None
        self._final_states = []
        self.proto = protocol

        for func_name in dir(self):
            func = getattr(self, func_name)
            if hasattr(func, '__states__'):
                initial = func.__initial__
                final = func.__final__
                states = func.__states__

                init_state = self._deduce_special_state(initial, states, 'initial')
                if init_state:
                    if self._state == None:
                        self.set_state(init_state)
                    else:
                        raise ValueError(f'Cannot have multiple initial states for {self.__class__}')
                    
                final_state = self._deduce_special_state(final, states, 'final')
                if final_state:
                    self._final_states.append(final_state)

                for state in func.__states__:
                    if state in self._state_handlers:
                        raise ValueError(f'Duplicate handler for state {state}')
                    self._state_handlers[state] = func

    def _deduce_special_state(self, marker, states, name):
        if type(marker) == None:
            return None
        elif type(marker) == bool:
            if marker: return states[0]
            else: return None
        elif type(marker) == int:
            return states[marker]
        else:
            raise ValueError(f'The {name} state can be marked with a boolean or an integer, {marker} is neither')
    
    def set_state(self, state):
        if state != self._state:
            if self._final_states and self._state in self._final_states:
                raise RuntimeError(f'Cannot change state from final state {self._state}')
            self._state = state
            log.info(f'State of {self.proto.name} changed to {state}', at=self.proto.node)
    
    def get_state(self):
        return self._state
    
    def run(self):
        if not self._state:
            raise RuntimeError(f'No initial state defined for {self.__class__}, define it using @protocolstate(..., initial=<value>) or manually using set_state(<state>)')

        while True:
            handler = self._state_handlers[self._state]
            if not handler:
                raise RuntimeError(f'No handler for state {self._state} in {self.__class__}')
            next_state = None
            handler_gen = handler()
            if inspect.isgenerator(handler_gen):
                try:
                    result = None
                    while True:
                        result = yield handler_gen.send(result)
                except StopIteration as e:
                    next_state = e.value
            else:
                next_state = handler_gen

            if self._state in self._final_states:
                break
            self.set_state(next_state)


class Clock (LocalProtocol):
    TICK = 'tick'

    def __init__(self, delta_time, nodes=None, name=None):
        super().__init__(name=name)
        self._delta_time = delta_time
        self._tick_count = 0
        self.add_signal(Clock.TICK)
        for node in nodes:
            self.nodes[node.name] = node

    def run(self):
        while True:
            self._tick_count += 1
            self.send_signal(Clock.TICK)
            node_names = ','.join(self.nodes.keys())
            log.info(f'TICK for {node_names}', at=self)
            yield self.await_timer(self._delta_time)

    def delta_time(self):
        return self._delta_time
    
    def tick_count(self):
        return self._tick_count
    
    @staticmethod
    def for_roundtrip(length, refraction_index, answare_delay=0):
        return Clock(
            delta_time=(2 * length / (SPEED_OF_LIGHT / refraction_index) + answare_delay)
        )
