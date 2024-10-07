
from abc import ABCMeta as Abstract, abstractmethod
from netsquid.protocols import NodeProtocol
from enum import Enum

from ..util import ProtocolStateMachine, protocolstate, StatefulProtocolTempalte, QueuedProtocol
from simlog import log


class PhysicalLayer(
    StatefulProtocolTempalte(QueuedProtocol),
    metaclass=Abstract
):
    MSG_HEADER = 'PhysicalLayer'
    
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'

    ATTEMPT_EG = 'ATTEMPT_EG'
    ATTEMPTED_EG = 'ATTEMPTED_EG'
    
    def __init__(self, node, name=None) -> None:
        self.log_layer = log.Layer.PHYSICAL
        super().__init__(node, name)
        self.add_signal(PhysicalLayer.ATTEMPTED_EG)

    def create_statemachine(self):
        return PhysicalLayerStatemachine(self)

    @abstractmethod
    def _attempt_entanglement(self, req):
        pass

    def attempt_entanglement(self, position, **kwargs):
        return self._push_request(
            PhysicalLayer.ATTEMPT_EG,
            PhysicalLayer.ATTEMPTED_EG,
            position=position,
            **kwargs
        )


class PhysicalState(Enum):
    IDLE = 'IDLE'
    GENERATING = 'GENERATING'
    

class PhysicalLayerStatemachine (ProtocolStateMachine):
    @protocolstate(PhysicalState.IDLE, initial=True)
    def _idle(self):
        yield from self.proto._await_request()
        return PhysicalState.GENERATING
    
    @protocolstate(PhysicalState.GENERATING)
    def _generating(self):
        for req in self.proto._poll_requests():
            yield from self.proto._attempt_entanglement(req)
        
        return PhysicalState.IDLE
