
from enum import Enum

from ..util import *


class TransportMethod (Enum):
    PUSH = 'TransportMethod.PUSH'
    PULL = 'TransportMethod.PULL'


class TransportLayer (
    StatefulProtocolTempalte(QueuedProtocol),
    metaclass=Abstract
):
    MSG_HEADER = 'TransportLayer'

    READY_TO_TRANSMIT = 'READY_TO_TRANSMIT'
    RECIEVED = 'RECIEVED'

    _POS_SPECIFIED = '_POS_SPECIFIED'

    def __init__(self, node, cport, name=None):
        self.log_layer = log.Layer.TRANSPORT
        super().__init__(node, name)
        self.add_signal(TransportLayer.READY_TO_TRANSMIT)
        self.add_signal(TransportLayer.RECIEVED)
        self.add_signal(TransportLayer._POS_SPECIFIED)
        self.cport_name = cport

    def create_statemachine(self):
        return TransportStatemachine(self)
    
    def transmit(self, method, count):
        return self._push_request(
            Role.SENDER,
            TransportLayer.READY_TO_TRANSMIT,
            method=method,
            count=count
        )
    
    def recieve(self):
        return self._push_request(
            Role.RECEIVER,
            TransportLayer.RECIEVED
        )
    
    @abstractmethod
    def _transmit(self, req):
        pass

    @abstractmethod
    def _recieve(self, req):
        pass

    def _transmit_hook(self, qpair):
        def _hook(position):
            self.send_signal(
                TransportLayer._POS_SPECIFIED,
                dict(position=position, qpair=qpair)
            )
        return _hook
    

class TransportState (Enum):
    IDLE = 'IDLE'
    TRANSMITTING = 'TRANSMITTING'


class TransportStatemachine (ProtocolStateMachine):
    @protocolstate(TransportState.IDLE, initial=True)
    def _idle(self):
        yield from self.proto._await_request()
        return TransportState.TRANSMITTING

    @protocolstate(TransportState.TRANSMITTING)
    def _transmitting(self):
        for req in self.proto._poll_requests():
            if req.req_label == Role.SENDER:
                yield from self.proto._transmit(req)
            else:
                yield from self.proto._recieve(req)
        return TransportState.IDLE
