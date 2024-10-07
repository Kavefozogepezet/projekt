
import netsquid as ns
from netsquid.protocols import LocalProtocol

from components.protocols.phys import PhysicalLayer
from components.protocols.util import ProtocolRequest
from simlog import log


class MockLinkLayer(LocalProtocol):
    def __init__(self, node1, node2, phys1, phys2, name=None):
        super().__init__(
            dict(node1=node1, node2=node2),
            name
        )
        self.add_subprotocol(phys1, name='phys1')
        self.add_subprotocol(phys2, name='phys2')

    def run(self):
        self.start_subprotocols()

        phys1 = self.subprotocols['phys1']
        phys2 = self.subprotocols['phys2']
        
        while True:
            req1 = phys1.attempt_entanglement(0)
            req2 = phys2.attempt_entanglement(0)

            [resp1, resp2] = yield from ProtocolRequest.await_all(self, req1, req2)
            print(ns.sim_time(), resp1, resp2, '\n')
            if resp1.result != resp2.result:
                log.error(f'MOCK_LINK_LAYER : BSA responded with different results: {resp1.result} and {resp2.result}')

            if resp1.result == PhysicalLayer.SUCCESS:
                if resp1.etgm_id != resp2.etgm_id:
                    log.error(f'MOCK_LINK_LAYER : BSA assigned diferent entanglement IDs')
                else:
                    log.info(f'MOCK_LINK_LAYER : {self.name} succeeded in creating entanglement with id {resp1.etgm_id}')
            else:
                log.info(f'MOCK_LINK_LAYER : {self.name} failed to create entanglement')
