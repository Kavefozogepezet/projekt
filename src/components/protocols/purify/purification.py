
from ..util import *


class PurificationProtocol (QueuedProtocol):
    PURIFICATION_COMPLETE = 'PURIFICATION_COMPLETE'

    _ADD_PAIR = 'ADD_PAIR'
    _RESET = 'RESET'

    def __init__(self, node, iterations, queue_limit=2, log_layer=None, name=None):
        if log_layer:
            self.log_layer = log_layer
        super().__init__(node, name=name)
        self.add_signal(PurificationProtocol.PURIFICATION_COMPLETE)
        self.iterations = iterations
        self.pairs = deque()
        self.queue_limit=queue_limit

    @abstractmethod
    def handle_pair(self, qubit):
        pass

    @abstractmethod
    def handle_reset(self):
        pass

    def run(self):
        while True:
            yield from self._await_request()
            for req in self._poll_requests():
                if req.req_label == PurificationProtocol._ADD_PAIR:
                    if self.iterations == 0:
                        self.deliver_pair(req.qubit)
                    elif len(self._queue) > self.queue_limit:
                        log.info(f'Queue limit exceeded, dropping qubit {req.qubit.id}', at=self)
                        self.node.qmemory.deallocate([req.qubit.position])
                    else:
                        yield from self.handle_pair(req.qubit)
                elif req.req_label == PurificationProtocol._RESET:
                    self.handle_reset()

    def add_pair(self, qubit):
        self._push_request(
            PurificationProtocol._ADD_PAIR,
            None, qubit=qubit
        )

    def reset(self):
        self._push_request(
            PurificationProtocol._RESET,
            None
        )

    def deliver_pair(self, qubit):
        self.send_signal(
            PurificationProtocol.PURIFICATION_COMPLETE,
            qubit
        )
    