
from ..util import *


class QKDProtocol (
    StatefulProtocolTempalte(QueuedProtocol),
    metaclass=Abstract
):
    def __init__(self, *args, **kwargs):
        self.log_layer = log.Layer.APP
        super().__init__(*args, **kwargs)

    def generate_key(self, length):
        return self._push_request(
            Role.SENDER,
            QKDProtocol.GENERATE_KEY,
            length=length
        )
    
    def recieve_key(self):
        return self._push_request(
            Role.RECEIVER,
            QKDProtocol.RECIEVE_KEY
        )
    
    @abstractmethod
    def _generate_qubits(self, length):
        pass

    @abstractmethod
    def _recieve_qubits(self):
        pass

    @abstractmethod
    def _sender_reveal(self, req):
        pass

    @abstractmethod
    def _reciever_reveal(self, req):
        pass
    

class QKDState (Enum):
    IDLE = 'QKDState.IDLE'
    GENERATING = 'QKDState.GENERATING'
    REVEALING = 'QKDState.REVEALING'


class QKDStatemachine (ProtocolStateMachine):
    @protocolstate(QKDState.IDLE, initial=True)
    def _idle(self):
        yield from self._await_request()
        req = self._peek_request()
        return QKDState.GENERATING

    @protocolstate(QKDState.GENERATING)
    def _generating(self):
        req = self._peek_request()
        if req.req_label == Role.SENDER:
            yield from self.proto._generate_qubits(req)
        elif req.req_label == Role.RECEIVER:
            yield from self.proto._recieve_qubits(req)
        return QKDState.REVEALING

    @protocolstate(QKDState.REVEALING)
    def _revealing(self):
        req = self._poll_request()
        if req.req_label == Role.SENDER:
            yield from self.proto._sender_reveal(req)
        elif req.req_label == Role.RECEIVER:
            yield from self.proto._reciever_reveal(req)
        return QKDState.IDLE
