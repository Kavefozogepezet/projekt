
from netsquid.protocols import NodeProtocol
from enum import Enum

from ..util import *


class LinkLayer (
    StatefulProtocolTempalte(NodeProtocol),
    metaclass=Abstract
):
    
    _REQ_ETGM = 'LinkLayer.REQ_ETGM'

    def __init__(self, node, name):
        super().__init__(node, name)
        self.add_signal(LinkLayer._REQ_ETGM)

    def create_statemachine(self):
        return LinkLayerStatemachine(self)

    @abstractmethod
    def _share_entanglement(self):
        pass

    def request_entanglement(self, count=1):
        if self.get_state() == LinkState.TRYING:
            raise RuntimeError(f'Requested entanglement, but {self.name} is already trying')
        self.send_signal(LinkLayer._REQ_ETGM, count)


class LinkState (Enum):
    IDLE = 'LinkState.IDLE'
    TRYING = 'LinkState.TRYING'


class LinkLayerStatemachine (ProtocolStateMachine):
    @protocolstate(LinkState.IDLE, initial=True)
    def _idle(self):
        yield self.proto.await_signal(
            sender=self.proto,
            signal_label=LinkLayer._REQ_ETGM
        )
        self.count = self.proto.get_signal_result(LinkLayer._REQ_ETGM)
        return LinkState.TRYING
    
    @protocolstate(LinkState.TRYING)
    def _trying(self):
        for i in range(self.count):
            yield from self.proto._share_entanglement()
        return LinkState.IDLE
