
import datetime
import inspect
import logging
import netsquid as ns
from netsquid.protocols import Protocol, LocalProtocol
from netsquid.components.qprogram import QuantumProgram

from components.hardware import SPEED_OF_LIGHT


def program_function(**program_kwargs):
    def program_function_decorator(prog_func):
        def program_executor(self, *args, **kwargs):
            prog = QuantumProgram(**program_kwargs)
            qindices = prog.get_qubit_indices(program_kwargs['num_qubits'])
            prog_func(self, prog, qindices, *args, **kwargs)
            yield self.node.qmemory.execute_program(prog)
        return program_executor
    return program_function_decorator

class log:
    def __init__(self):
        raise NotImplementedError('This class is not meant to be instantiated.')
    
    @staticmethod
    def init(level):
        current_datetime = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = logging.FileHandler(f"./log/sim_{current_datetime}.log")
        log_file.setLevel(level)

        for handler in ns.logger.handlers:
            ns.logger.removeHandler(handler)
        ns.logger.setLevel(level)
        ns.logger.addHandler(log_file)
    
    @staticmethod
    def info(msg, **kwargs):
        the_msg = log._construct_message('INFO', msg, **kwargs)
        ns.logger.info(the_msg)

    @staticmethod
    def _construct_message(level, msg, **kwargs):
        if 'at' in kwargs:
            name = kwargs['at'].name
            name = f' @@ {name:16}: '
        elif 'into' in kwargs:
            name = kwargs['into'].name
            name = f' >> {name:16}: '
        elif 'outof' in kwargs:
            name = kwargs['outof'].name
            name = f' << {name:16}: '
        else:
            name = ' '
        
        return f'[{level:5} @ {ns.sim_time():8.2f}]{name}{msg}'
    

def statehandler(*states):
    def decorator(func):
        func.__states__ = states
        return func
    return decorator


def StatefulProtocolTemplate(BaseType, initial_state, final_state=None):
    if not issubclass(BaseType, Protocol):
        raise ValueError('BaseType must be a subclass of netsquid.protocols.Protocol')
    
    class StatefulProtocol (BaseType):
        def __init__ (self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._final_state = final_state
            self._StateType = initial_state.__class__
            self._state = None
            self.set_state(initial_state)
            self._state_handlers = {}
            for func_name in dir(self):
                func = getattr(self, func_name)
                if hasattr(func, '__states__'):
                    for state in func.__states__:
                        if state not in self._StateType:
                            raise ValueError(f'Invalid state for handler {state}')
                        if state in self._state_handlers:
                            raise ValueError(f'Duplicate handler for state {state}')
                        self._state_handlers[state] = func
    
        def set_state(self, state):
            if state not in self._StateType:
                raise ValueError(f'Invalid state {state}')
            if self._final_state and self._state == self._final_state:
                raise RuntimeError(f'Cannot change state from final state {self._final_state}')
            if state != self._state:
                self._state = state
                log.info(f'State of {self.name} changed to {state}', at=self.node)
    
        def get_state(self):
            return self._state
        
        def run(self):
            while True:
                handler = self._state_handlers[self._state]
                if not handler:
                    raise RuntimeError(f'No handler for state {self._state}')
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
    
                if self._state == self._final_state:
                    break
                self.set_state(next_state)

    return StatefulProtocol


class Clock (LocalProtocol):
    TICK = 'tick'

    def __init__(self, delta_time, nodes=None, name=None):
        super().__init__(name=name)
        self._delta_time = delta_time
        self.add_signal(Clock.TICK)
        for node in nodes:
            self.nodes[node.name] = node

    def run(self):
        while True:
            self.send_signal(Clock.TICK)
            node_names = ','.join(self.nodes.keys())
            log.info(f'TICK for {node_names}', at=self)
            yield self.await_timer(self._delta_time)

    def delta_time(self):
        return self._delta_time
    
    @staticmethod
    def for_roundtrip(length, refraction_index, answare_delay=0):
        return Clock(
            delta_time=(2 * length / (SPEED_OF_LIGHT / refraction_index) + answare_delay)
        )
