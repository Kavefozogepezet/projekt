
from .link_layer import *
from ..util import *
from ..phys import PhysicalLayer


# SIMple Protocol for Link level Entanglement ;)
class SimPLE (LinkLayer):
    SIMPLE_MSG_HEADER = f'SimPLE({LinkLayer.MSG_HEADER})'

    def __init__(self, node, physical_protocol, partition=None, name=None) -> None:
        super().__init__(node, partition, name)
        self.add_subprotocol(physical_protocol, name='physical_protocol')

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def _share_entanglement(self, req):
        if req.response_type == LinkResponseType.ATOMIC:
            gen = self._handle_atomic_request(req)
        elif req.response_type == LinkResponseType.CONSECUTIVE:
            if req.count == None:
                gen = self._handle_infinite_consecutive_request(req)
            else:
                gen = self._handle_consecutive_request(req)

        if req.timeout:
            gen = self._timeout_generator(gen, req.timeout)
        
        yield from gen


    def _handle_atomic_request(self, req):
        qubits = []
        count = req.count
        tries = []
        while count > 0 and not req.cancelled:
            resp, tries = yield from self._attempt_until_success(req)
            if not req.cancelled:
                qubits.append(EntanglementRecord(
                    position=resp.position,
                    id=resp.etgm_id
                ))
                tries.append(tries)
                count -= 1

        if not req.cancelled:
            req.answare(
                result=LinkLayer.OK,
                response_type=LinkResponseType.ATOMIC,
                qubits=qubits,
                tries=tries
            )
            log.info(f'Link delivered {count} qubits', at=self)

    def _handle_consecutive_request(self, req):
        count = req.count
        while count > 0 and not req.cancelled:
            resp, tries = yield from self._attempt_until_success(req)
            if not req.cancelled:
                req.answare(
                    result=LinkLayer.OK,
                    response_type=LinkResponseType.CONSECUTIVE,
                    final=count==1,
                    qubit=EntanglementRecord(
                        position=resp.position,
                        id=resp.etgm_id
                    ),
                    tries=tries
                )
                if count == 1:
                    log.info(f'Link delivered qubit #{count} (last): {resp.etgm_id}', at=self)
                else:
                    log.info(f'Link delivered qubit #{count}: {resp.etgm_id}', at=self)
                count -= 1

    def _handle_infinite_consecutive_request(self, req):
        # TODO untested
        while not req.cancelled:
            resp, tries = yield from self._attempt_until_success(req)
            if not req.cancelled:
                req.answare(
                    result=LinkLayer.OK,
                    response_type=LinkResponseType.CONSECUTIVE,
                    qubit=EntanglementRecord(
                        position=resp.position,
                        id=resp.etgm_id
                    ),
                    tries=tries
                )
                log.info(f'Link delivered qubit: {resp.etgm_id}', at=self)

    def _attempt_until_success(self, req):
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
                return resp, tries
        
        self.node.qmemory.deallocate([pos])
        return None

    def _timeout_generator(self, req, gen, timeout):
        timeout_expr = self.await_timer(timeout)
        for expr in gen:
            result = yield expr | timeout_expr
            if result.second_term.value:
                req.answare(result=LinkLayer.TIMEOUT)
            else:
                gen.send(result.first_term)
