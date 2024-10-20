
import netsquid as ns
from netsquid.protocols import LocalProtocol
from netsquid.qubits.qubitapi import fidelity
from netsquid.qubits import ketstates

from components.protocols.link import LinkLayer, LinkResponseType
from components.protocols.util import ProtocolRequest
from simlog import log


class MockNetLayer (LocalProtocol):
    def __init__(self, node1, node2, link1, link2, name=None):
        super().__init__(
            dict(node1=node1, node2=node2),
            name
        )
        self.add_subprotocol(link1, name='link1')
        self.add_subprotocol(link2, name='link2')
        self.node1 = node1
        self.node2 = node2

    def run(self):
        self.start_subprotocols()

        link1 = self.subprotocols['link1']
        link2 = self.subprotocols['link2']
        
        while True:
            req1 = link1.request_entanglement(3, LinkResponseType.CONSECUTIVE)
            req2 = link2.request_entanglement(3, LinkResponseType.CONSECUTIVE)

            count = 0
            while True:
                [resp1, resp2] = yield from ProtocolRequest.await_all(self, req1, req2)
                count += 1
                assert resp1.result == resp2.result, f'Link layer result inconsistent across nodes: {resp1.result} and {resp2.result}'

                if resp1.result == LinkLayer.OK:
                    assert resp1.qubit.id == resp2.qubit.id, f'Insonsistent id across nodes: {resp1.qubit.id}, {resp2.qubit.id}'
                    log.info(f'MOCK_NET_LAYER : Succeeded in creating entanglement with id {resp1.qubit.id}')

                [q1] = self.node1.qmemory.peek([resp1.qubit.position])
                [q2] = self.node2.qmemory.peek([resp2.qubit.position])

                fid = fidelity([q1, q2], ketstates.b00)
                log.info(f'MOCK_TRANS_LAYER: Fidelity of entanglement: {fid}')
                ns.logger.info(f'{q1.qstate.dm}')

                self.node1.qmemory.deallocate([resp1.qubit.position])
                self.node2.qmemory.deallocate([resp2.qubit.position])

                if resp1.final:
                    assert resp2.final, f'Link layer final state inconsistent across nodes'
                    break

            assert count == 3, f'Link layer provided incorrect number of entanglements: {count}'
            log.info(f'MOCK_NET_LAYER : LinkLayer successfully created 3 entanglements')
