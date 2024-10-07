
import netsquid as ns
from netsquid.protocols import LocalProtocol
from netsquid.qubits.qubitapi import fidelity
from netsquid.qubits import ketstates

from components.protocols.link import LinkLayer, LinkResponseType
from components.protocols.util import ProtocolRequest
from simlog import log


class MockTransportLayer (LocalProtocol):
    def __init__(self, headend, tailend, head_net, tail_net, name=None):
        super().__init__(
            dict(headend=headend, tailend=tailend),
            name
        )
        self.add_subprotocol(head_net, name='head_net')
        self.add_subprotocol(tail_net, name='tail_net')
        self.headend = headend
        self.tailend = tailend

    def run(self):
        self.start_subprotocols()

        head_net = self.subprotocols['head_net']
        tail_net = self.subprotocols['tail_net']

        for _ in range(2):
            head_req = head_net.initiate_sharing(5)
            tail_req = tail_net.recieve()

            count = 0
            while count < 5:
                [head_resp, tail_resp] = (
                    yield from ProtocolRequest.await_all(
                        self, head_req, tail_req)
                )
                count += 1

                head_qubit = head_resp.qubit
                tail_qubit = tail_resp.qubit

                assert head_qubit.id == tail_qubit.id, f'Inconsistent id across ends: {head_qubit.id}, {tail_qubit.id}'
                log.info(f'MOCK_TRANS_LAYER: Succeeded in creating entanglement with id {head_qubit.id}')

                [q1] = self.headend.qmemory.peek([head_qubit.position])
                [q2] = self.tailend.qmemory.peek([tail_qubit.position])

                fid = fidelity([q1, q2], ketstates.b00)
                log.info(f'MOCK_TRANS_LAYER: Fidelity of entanglement: {fid}')

                self.headend.qmemory.deallocate([head_qubit.position])
                self.tailend.qmemory.deallocate([tail_qubit.position])
