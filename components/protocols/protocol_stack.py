
import inspect
from abc import ABCMeta as Abstract, abstractmethod
from netsquid.protocols import NodeProtocol
from enum import Enum

from .util import StatefulProtocolTemplate, statehandler


class PhysicalState(Enum):
    IDLE = 'PhysicalState.IDLE'
    GENERATING = 'PhysicalState.GENERATING'


class PhysicalLayer(
    StatefulProtocolTemplate(NodeProtocol, PhysicalState.IDLE),
    metaclass=Abstract
):
    SUCCESS = 'PhysicalLayer.SUCCESS'
    FAILURE = 'PhysicalLayer.FAILURE'
    _START = 'PhysicalLayer._START'
    _STOP = 'PhysicalLayer._STOP'
    
    def __init__(self, node, name) -> None:
        super().__init__(node, name)
        self.add_signal(PhysicalLayer.SUCCESS)
        self.add_signal(PhysicalLayer.FAILURE)
        self.add_signal(PhysicalLayer._START)
        self.add_signal(PhysicalLayer._STOP)

    @statehandler(PhysicalState.IDLE)
    def _idle(self):
        yield self.await_signal(self, PhysicalLayer._START)
        return PhysicalState.GENERATING
    
    @statehandler(PhysicalState.GENERATING)
    def _generating(self):
        for event in self._start_attempts():
            expr = yield event | self.await_signal(self, PhysicalLayer._STOP)
            if expr.second_term.value:
                return PhysicalState.IDLE
        raise RuntimeError(f'Physical layer {self.name} stopped generating without instruction')

    @abstractmethod
    def _start_attempts(self):
        pass

    def start_generation(self):
        if self.generating:
            raise RuntimeError(f'Tried starting {self.name}, but it is already performing entangling attempts')
        self.send_signal(PhysicalLayer._STOP)

    def stop_generation(self):
        if not self.generating:
            raise RuntimeError(f'Tried stopping {self.name}, but it is not performing entangling attempts')
        self.send_signal(PhysicalLayer._STOP)