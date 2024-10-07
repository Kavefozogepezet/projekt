
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
    TRANSMITTED = 'TRANSMITTED'

    _POS_SPECIFIED = '_POS_SPECIFIED'

    def __init__(self, node, cport, name=None):
        self.log_layer = log.Layer.TRANSPORT
        super().__init__(node, name)
        self.cport_name = cport

    def create_statemachine(self):
        return TransportStatemachine(self)
    
    def transmit(self, method, count):
        return self._push_request(
            Role.SENDER,
            TransportLayer.MSG_HEADER,
            method=method,
            count=count
        )
    
    def recieve(self):
        return self._push_request(
            Role.RECEIVER,
            TransportLayer.TRANSMITTED
        )
    
    @abstractmethod
    def _transmit(self, req):
        pass

    @abstractmethod
    def _recieve(self, req):
        pass

    def _transmit_hook(self):
        def _hook(position):
            self.send_signal(
                TransportLayer._POS_SPECIFIED,
                position=position
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
        req = yield from self.proto._await_request()
        if req.req_label == Role.SENDER:
            yield from self.proto._transmit(req)
        else:
            yield from self.proto._recieve(req)
        return TransportState.RECIEVING
