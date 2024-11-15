
import inspect
from collections import deque, namedtuple
from enum import Enum
import netsquid as ns
from netsquid.protocols import LocalProtocol, NodeProtocol
from abc import ABCMeta as Abstract, abstractmethod
from shortuuid import uuid

from components.hardware import SPEED_OF_LIGHT
from simlog import log


class Role (Enum):
    SENDER = 'Role.SENDER'
    RECEIVER = 'Role.RECEIVER'


EntanglementRecord = namedtuple(
    'EntanglementID',
    ['position', 'id']
)


def etgmid(namespace):
    id = uuid()
    return f'{namespace}/{id}'


def subheader(header, *subheaders):
    return '/'.join([header, *subheaders])


def protocolstate(*states, initial=False, final=False):
    def decorator(func):
        func.__states__ = states
        func.__initial__ = initial
        func.__final__ = final
        return func
    return decorator


class QueuedProtocol (NodeProtocol):
    _REQ_ARRIVED = 'RequestQueueProtocol.REQ_ARRIVED'

    def __init__(self, node, name=None):
        super().__init__(node, name)
        self._queue = deque()
        self.add_signal(QueuedProtocol._REQ_ARRIVED)

    def _await_request(self):
        yield self.await_signal(
            sender=self,
            signal_label=QueuedProtocol._REQ_ARRIVED
        )

    def _poll_request(self):
        if len(self._queue) > 0:
            return self._queue.popleft()
        return None

    def _poll_requests(self):
        while len(self._queue) > 0:
            yield self._poll_request()

    def _peek_request(self):
        if len(self._queue) > 0:
            return self._queue[0]
        return None

    def _push_request(self, req_label, ans_label, **kwargs):
        req = ProtocolRequest(self, req_label, ans_label, **kwargs)
        self._queue.append(req)
        self.send_signal(QueuedProtocol._REQ_ARRIVED)
        return req
    

class ProtocolRequest:
    def __init__(self, protocol, req_label, ans_label, **kwargs):
        self.proto = protocol
        self.id = uuid()
        self.req_label = req_label
        self.ans_label = ans_label
        for name, value in kwargs.items():
            setattr(self, name, value)
        
    def await_as(self, awaiting_protocol):
        while True:
            yield self.resp_event(awaiting_protocol)
            resp = self.get_answare(awaiting_protocol)
            if resp.id == self.id:
                return resp
            
    def answare(self, **kwargs):
        resp = ProtocolResponse(self.id, **kwargs)
        self.proto.send_signal(self.ans_label, resp)

    def resp_event(self, awaiting_protocol):
        return awaiting_protocol.await_signal(
            sender=self.proto,
            signal_label=self.ans_label
        )
    
    def get_answare(self, awaiting_protocol):
        return self.proto.get_signal_result(self.ans_label, awaiting_protocol)

    @staticmethod
    def await_all(awaiting_protocol, *reqs):
        evexpr = None
        for req in reqs:
            ev = awaiting_protocol.await_signal(
                sender=req.proto,
                signal_label=req.ans_label
            )
            if evexpr:
                evexpr = ev
            else:
                evexpr = evexpr & ev

        yield evexpr
        results = []
        for req in reqs:
            res = req.proto.get_signal_result(req.ans_label, awaiting_protocol)
            results.append(res)

        return results
        


class ProtocolResponse:
    def __init__(self, id, **kwargs):
        self.id = id
        for name, value in kwargs.items():
            setattr(self, name, value)


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
                    if self._state is None:
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
        if type(marker) is None:
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
            log.info(f'State change -> {state.value}', at=self.proto)
    
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

            if next_state is None:
                raise RuntimeError(f'Handler for state {self._state} in {self.__class__} returned None')
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
