
from .purification import *
from .dejmps import *


class MixedPurify(PurificationProtocol):
    def __init__(self, node, cport,
        ladder_iter, greedy_iter,
        mode, queue_limit=2, log_layer=None, name='LadderPurify',
        prog_reason = None
    ):
        iterations = ladder_iter * greedy_iter
        super().__init__(node, iterations, queue_limit, log_layer, name)
        self.dejmps = DEJMPSProtocol(node, cport, mode, log_layer=log_layer, name=f"{name}'", prog_reason=prog_reason)
        self.add_subprotocol(self.dejmps, name='dejmps')
        self.liter = ladder_iter
        self.giter = greedy_iter
        self.ladder = [None] * (ladder_iter+2)
        self.gladder = [0] * (ladder_iter+2)

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def handle_pair(self, qubit):
        if self.ladder[0] is None:
            self.ladder[0] = qubit
            if self.ladder[1] is None:
                return
        elif self.ladder[1] is None:
            self.ladder[1] = qubit
        else:
            raise ValueError('Ladder is full')
        
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

            if resp.keep:
                self.gladder[j] += 1
                if self.gladder[j] < self.giter:
                    break
                elif self.ladder[j+1] is None:
                    self.ladder[j+1] = self.ladder[j]
                    self.ladder[j] = None
                    self.gladder[j] = 0
                else:
                    j += 1
            else:
                self._drop_qubit(j)

        if self.ladder[self.liter+1] is not None:
            id = self.ladder[self.liter+1].id
            log.info(f'Purification complete: {id}', at=self)
            self.deliver_pair(self.ladder[self.liter+1])
            self.ladder[self.liter+1] = None
            self.handle_reset()

    def handle_reset(self):
        qubits = [q.position for q in self.ladder if q is not None]
        self.node.qmemory.deallocate(qubits)
        self.ladder = [None] * (self.liter+2)
        self.gladder = [0] * (self.liter+2)
        self.dejmps.reset()

    def _drop_qubit(self, i):
        self.gladder[i] = 0
        if self.ladder[i] is not None:
            self.node.qmemory.deallocate([self.ladder[i].position])
            self.ladder[i] = None
