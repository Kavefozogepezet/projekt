
from netsquid.components.component import Message

from components.protocols.purify.purification import PurificationProtocol
from .network_layer import NetworkLayer, RoutingRole
from ..util import *

class NetWithPurification (NetworkLayer):
    PURIFY_HEADER = 'NetworkLayerPurification'

    INIT_MSG = 'INIT_MSG'

    def __init__ (
        self, node, cport, purification_protocol, net_protocol, name=None
    ):
        super().__init__(node, name)
        self.add_subprotocol(purification_protocol, name='purification_protocol')
        self.add_subprotocol(net_protocol, name='net_protocol')
        self.purify_proto = purification_protocol
        self.net_proto = net_protocol
        self.cport = self.node.ports[cport]

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def _initiate(self, req):
        if req.req_label == RoutingRole.HEADEND:
            self.net_req = self.net_proto.initiate_sharing()
            msg = [NetWithPurification.INIT_MSG, dict(count=req.count)]
            self.cport.tx_output(Message(msg, header=NetWithPurification.PURIFY_HEADER))
            log.info(log.msg2str(msg), outof=self)
        elif req.req_label == RoutingRole.TAILEND:
            self.net_req = self.net_proto.recieve()
            while True:
                yield self.await_port_input(self.cport)
                msg = self.cport.rx_input(header=NetWithPurification.PURIFY_HEADER)
                if not msg:
                    continue
                req.count = msg.items[1]['count']
                log.info(log.msg2str(msg.items), into=self)
                break
        else:
            raise ValueError(f'Unknown role: {req.req_label}')
        
    def _swap(self, req):
        self.count = 0
        while (
            (req.count is None or self.count < req.count)
            and not req.cancelled
        ):
            net_ev = self.net_req.resp_event(self)
            purify_ev = self.purify_proto.await_signal(
                sender=self.purify_proto,
                signal_label=PurificationProtocol.PURIFICATION_COMPLETE
            )

            expr = yield net_ev | purify_ev
            if expr.first_term.value:
                resp = self.net_req.get_answare(self)
                self.purify_proto.add_pair(resp.qubit)
            else:
                self.count += 1
                qubit = self.purify_proto.get_signal_result(
                    PurificationProtocol.PURIFICATION_COMPLETE, self
                )
                req.answare(
                    qubit=qubit,
                    final=self.count==req.count
                )
        
        self.net_req.cancelled = True
        self.purify_proto.reset()

    def _terminate(self, req):
        pass
