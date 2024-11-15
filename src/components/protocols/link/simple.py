
from .link_base import *
from ..util import *
from ..phys import PhysicalLayer


# SIMple Protocol for Link level Entanglement ;)
class SimPLE (LinkBase):
    SIMPLE_MSG_HEADER = f'SimPLE({LinkLayer.MSG_HEADER})'

    def __init__(self, node, physical_protocol, partition=None, name=None) -> None:
        super().__init__(node, partition, name)
        self.add_subprotocol(physical_protocol, name='physical_protocol')

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def _share_entanglement(self, req):
        phys_proto = self.subprotocols['physical_protocol']
        [pos] = yield from self._allocate_qubits(1)
        tries = 0
        while not req.cancelled:
            resp = yield from (phys_proto
                .attempt_entanglement(pos)
                .await_as(self)
            )
            tries += 1
            if resp.result == PhysicalLayer.SUCCESS:
                return EntanglementRecord(resp.position, resp.etgm_id), tries
        
        self.node.qmemory.deallocate([pos])
        return None, None
    
    def _reset_link(self):
        pass
