
from enum import Enum
from netsquid.components.qmemory import QuantumMemoryError

from ..util import *


class LinkResponseType (Enum):
    ATOMIC = 'LinkResponseType.ATOMIC'
    CONSECUTIVE = 'LinkResponseType.CONSECUTIVE'


class LinkLayer (
    StatefulProtocolTempalte(QueuedProtocol),
    metaclass=Abstract
):
    MSG_HEADER = 'LinkLayer'

    OK = 'OK'
    TIMEOUT = 'TIMEOUT'

    ETGM_READY = 'ETGM_READY'
    REQ_ETGM = 'REQ_ETGM'
    STOP_ETGM = 'STOP_ETGM'

    def __init__(self, node, partition=None, name=None):
        self.log_layer = log.Layer.LINK
        super().__init__(node, name)
        self.add_signal(LinkLayer.ETGM_READY)
        self.partition = partition

    def create_statemachine(self):
        return LinkLayerStatemachine(self)

    @abstractmethod
    def _fulfill_request(self, req):
        pass

    def request_entanglement(
        self,
        count=None,
        response_type=LinkResponseType.ATOMIC,
        timeout=None,
        **kwargs
    ):
        if count is None and response_type == LinkResponseType.ATOMIC:
            raise ValueError('An atomic request must specify the number of qubits to allocate (count)')

        return self._push_request(
            LinkLayer.REQ_ETGM,
            LinkLayer.ETGM_READY,
            count=count,
            response_type=response_type,
            timeout=timeout,
            cancelled=False,
            **kwargs
        )


class LinkState (Enum):
    IDLE = 'IDLE'
    SHARING = 'SHARING'


class LinkLayerStatemachine (ProtocolStateMachine):
    @protocolstate(LinkState.IDLE, initial=True)
    def _idle(self):
        yield from self.proto._await_request()
        return LinkState.SHARING
    
    @protocolstate(LinkState.SHARING)
    def _sharing(self):
        for req in self.proto._poll_requests():
            yield from self.proto._fulfill_request(req)
        return LinkState.IDLE
