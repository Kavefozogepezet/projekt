
from enum import Enum
import inspect

from ..util import *


class RoutingRole (Enum):
    HEADEND = 'HEADEND'
    TAILEND = 'TAILEND'


class NetworkLayer (
    StatefulProtocolTempalte(QueuedProtocol),
    metaclass=Abstract
):
    MSG_HEADER = 'NetworkLayer'
    ETGM_READY = 'ETGM_READY'

    def __init__(self, node, name=None):
        self.log_layer = log.Layer.NETWORK
        super().__init__(node, name)
        self.add_signal(NetworkLayer.ETGM_READY)

    def create_statemachine(self):
        return NetworkStatemachine(self)
    
    def initiate_sharing(self, count=None, **kwargs):
        return self._push_request(
            RoutingRole.HEADEND,
            NetworkLayer.ETGM_READY,
            count=count,
            cancelled=False,
            **kwargs
        )
        
    # TODO consider count as parameter,
    # later check consistency during initiation
    def recieve(self, **kwargs):
        return self._push_request(
            RoutingRole.TAILEND,
            NetworkLayer.ETGM_READY,
            cancelled=False,
            **kwargs
        )
        
    @abstractmethod
    def _initiate(self, req):
        pass

    @abstractmethod
    def _swap(self, req):
        pass

    @abstractmethod
    def _terminate(self, req):
        pass


class NetworkState (Enum):
    IDLE = 'IDLE'
    INITIATING = 'INITIATING'
    SWAPPING = 'SWAPPING'
    TERMINATING = 'TERMINATING'

class NetworkStatemachine (ProtocolStateMachine):
    @protocolstate(NetworkState.IDLE, initial=True)
    def _idle(self):
        yield from self.proto._await_request()
        return NetworkState.INITIATING
    
    @protocolstate(NetworkState.INITIATING)
    def _initiating(self):
        req = self.proto._peek_request()
        if inspect.isgeneratorfunction(self.proto._initiate):
            yield from self.proto._initiate(req)
        else:
            self.proto._initiate(req)
        return NetworkState.SWAPPING

    @protocolstate(NetworkState.SWAPPING)
    def _swapping(self):
        req = self.proto._peek_request()
        yield from self.proto._swap(req)
        return NetworkState.TERMINATING
    
    @protocolstate(NetworkState.TERMINATING)
    def _terminating(self):
        req = self.proto._poll_request()
        if inspect.isgeneratorfunction(self.proto._terminate):
            yield from self.proto._terminate(req)
        else:
            self.proto._terminate(req)
            
        if self.proto._peek_request():
            return NetworkState.INITIATING
        else:
            return NetworkState.IDLE
