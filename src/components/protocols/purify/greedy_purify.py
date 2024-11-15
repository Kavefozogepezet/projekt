
from .purification import *
from .dejmps import *


class GreedyPurify(PurificationProtocol):
    def __init__(self, node, cport, iterations, mode, queue_limit=2, log_layer=None, name='GreedyPurify'):
        super().__init__(node, iterations, queue_limit, log_layer, name)
        self.bbpssw = DEJMPSProtocol(node, cport, mode, log_layer=log_layer, name=f"{name}'")
        self.add_subprotocol(self.bbpssw, name='bbpssw')
        self.current = None
        self.current_iters = 0

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def handle_pair(self, qubit):
        self.current_iters += 1
        if self.current_iters == 1:
            self.current = qubit
            log.info(f'Purifying {qubit.id}', at=self)
        else:
            resp = yield from (self.bbpssw
                .purify(self.current, qubit)
                .await_as(self))
            self.node.qmemory.deallocate([qubit.position])
            if resp.keep:
                log.info(f'Iteration #{self.current_iters-1} successful: o -X {qubit.id}', at=self)
                if self.current_iters > self.iterations:
                    log.info(f'Purification complete: {self.current.id}', at=self)
                    self.deliver_pair(self.current)
                    self.current = None
                    self.handle_reset()
            else:
                log.info(f'Iteration #{self.current_iters-1} failed: o -X {qubit.id}', at=self)
                self.handle_reset()


    def handle_reset(self):
        if self.current:
            self.node.qmemory.deallocate([self.current.position])
            self.current = None
        self.current_iters = 0
        self.bbpssw.reset()
