
from abc import ABCMeta as Abstract, abstractmethod
from netsquid.protocols import NodeProtocol
from enum import Enum

from ..util import ProtocolStateMachine, protocolstate, StatefulProtocolTempalte


class PhysicalState(Enum):
    IDLE = 'PhysicalState.IDLE'
    GENERATING = 'PhysicalState.GENERATING'


class PhysicalLayer(
    StatefulProtocolTempalte(NodeProtocol),
    metaclass=Abstract
):
    SUCCESS = 'PhysicalLayer.SUCCESS'
    FAILURE = 'PhysicalLayer.FAILURE'
    _START = 'PhysicalLayer.START'
    _STOP = 'PhysicalLayer.STOP'
    
    def __init__(self, node, name) -> None:
        super().__init__(node, name)
        self.add_signal(PhysicalLayer.SUCCESS)
        self.add_signal(PhysicalLayer.FAILURE)
        self.add_signal(PhysicalLayer._START)
        self.add_signal(PhysicalLayer._STOP)

    def create_statemachine(self):
        return PhysicalLayerStatemachine(self)

    @abstractmethod
    def _start_attempts(self):
        pass

    def start_generation(self):
        if self.get_state() == PhysicalState.GENERATING:
            raise RuntimeError(f'Tried starting {self.name}, but it is already performing entangling attempts')
        self.send_signal(PhysicalLayer._START)

    def stop_generation(self):
        if self.get_state() == PhysicalState.IDLE:
            raise RuntimeError(f'Tried stopping {self.name}, but it is not performing entangling attempts')
        self.send_signal(PhysicalLayer._STOP)


class PhysicalLayerStatemachine (ProtocolStateMachine):
    @protocolstate(PhysicalState.IDLE, initial=True)
    def _idle(self):
        yield self.proto.await_signal(
            sender=self.proto,
            signal_label=PhysicalLayer._START
        )
        return PhysicalState.GENERATING
    
    @protocolstate(PhysicalState.GENERATING)
    def _generating(self):
        for event in self.proto._start_attempts():
            stop_signal = self.proto.await_signal(
                sender=self.proto,
                signal_label=PhysicalLayer._STOP
            )
            expr = yield event | stop_signal
            if expr.second_term.value:
                return PhysicalState.IDLE
        raise RuntimeError(f'Physical layer {self.name} stopped generating without instruction')
