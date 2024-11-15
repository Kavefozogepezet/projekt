
from .link_layer import *


class LinkBase (LinkLayer):
    @abstractmethod
    def _share_entanglement(self, req):
        pass

    def _reset_link(self):
        pass

    def _fulfill_request(self, req):
        if req.response_type == LinkResponseType.ATOMIC:
            gen = self._handle_atomic_request(req)
        elif req.response_type == LinkResponseType.CONSECUTIVE:
            if req.count is None:
                gen = self._handle_infinite_consecutive_request(req)
            else:
                gen = self._handle_consecutive_request(req)

        if req.timeout:
            gen = self._timeout_generator(gen, req.timeout)
        
        yield from gen
        self._reset_link()


    def _handle_atomic_request(self, req):
        qubits = []
        count = req.count
        tries = []
        while count > 0 and not req.cancelled:
            qubit, tries = yield from self._share_entanglement(req)
            if not req.cancelled:
                qubits.append(qubit)
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
            qubit, tries = yield from self._share_entanglement(req)
            if not req.cancelled:
                req.answare(
                    result=LinkLayer.OK,
                    response_type=LinkResponseType.CONSECUTIVE,
                    final=count==1,
                    qubit=qubit,
                    tries=tries
                )
                if count == 1:
                    log.info(f'Link delivered qubit #{count} (last): {qubit.id}', at=self)
                else:
                    log.info(f'Link delivered qubit #{count}: {qubit.id}', at=self)
                count -= 1

    def _handle_infinite_consecutive_request(self, req):
        while not req.cancelled:
            qubit, tries = yield from self._share_entanglement(req)
            if not req.cancelled:
                req.answare(
                    result=LinkLayer.OK,
                    response_type=LinkResponseType.CONSECUTIVE,
                    qubit=qubit,
                    tries=tries
                )
                log.info(f'Link delivered qubit: {qubit}', at=self)

    def _timeout_generator(self, req, gen, timeout):
        timeout_expr = self.await_timer(timeout)
        for expr in gen:
            result = yield expr | timeout_expr
            if result.second_term.value:
                req.answare(result=LinkLayer.TIMEOUT)
            else:
                gen.send(result.first_term)

    def _allocate_qubits(self, count):
        while True:
            try:
                return self.node.qmemory.allocate(count, self.partition)
            except QuantumMemoryError:
                if self.partition: poss = self.partition
                else: poss = self.node.qmemory.memory_positions()
                yield self.await_mempos_in_use_toggle(
                    qmemory=self.node.qmemory,
                    positions=list(poss)
                )