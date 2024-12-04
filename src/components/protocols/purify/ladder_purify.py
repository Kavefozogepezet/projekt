

from .purification import *
from .dejmps import *


class LadderPurify(PurificationProtocol):
    def __init__(self, node, cport, iterations, mode, queue_limit=2, log_layer=None, name='LadderPurify'):
        super().__init__(node, iterations, queue_limit, log_layer, name)
        self.dejmps = DEJMPSProtocol(node, cport, mode, log_layer=log_layer, name=f"{name}'")
        self.add_subprotocol(self.dejmps, name='dejmps')
        self.iterations = iterations
        self.ladder = [None] * (iterations+2)

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def handle_pair(self, qubit):
        if self.ladder[0] is None:
            self.ladder[0] = qubit
            return
        
        self.ladder[1] = qubit
        j = 1
        while j <= self.iterations and self.ladder[j] is not None:
            resp = yield from (self.dejmps
                .purify(self.ladder[j], self.ladder[j-1])
                .await_as(self))
            
            if resp.keep:
                id1 = self.ladder[j].id
                id2 = self.ladder[j-1].id
                log.info(f'Successful iteration #{j}: {id1} -X {id2}', at=self)
            self._drop_qubit(j-1)

            if resp.keep and self.ladder[j+1] is None:
                self.ladder[j+1] = self.ladder[j]
                self.ladder[j] = None
            elif resp.keep:
                j += 1
            else:
                self._drop_qubit(j)

        if self.ladder[self.iterations+1] is not None:
            id = self.ladder[self.iterations+1].id
            log.info(f'Purification complete: {id}', at=self)
            self.deliver_pair(self.ladder[self.iterations+1])
            self.ladder[self.iterations+1] = None
            self.handle_reset()

    def handle_reset(self):
        qubits = [q.position for q in self.ladder if q is not None]
        self.node.qmemory.deallocate(qubits)
        self.ladder = [None] * (self.iterations+2)
        self.dejmps.reset()

    def _drop_qubit(self, i):
        if self.ladder[i] is not None:
            self.node.qmemory.deallocate([self.ladder[i].position])
            self.ladder[i] = None
