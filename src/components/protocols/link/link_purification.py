
from .link_base import *
from ..purify import PurificationProtocol

class LinkWithPurification (LinkBase):
    def __init__ (
        self, node, purification_protocol, link_protocol,
        partition=None, name=None
    ):
        super().__init__(node, partition, name)
        self.add_subprotocol(purification_protocol, name='purification_protocol')
        self.add_subprotocol(link_protocol, name='link_protocol')
        self.purify_proto = purification_protocol
        self.link_proto = link_protocol

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def _fulfill_request(self, req):
        self.link_req = self.link_proto.request_entanglement(
            response_type=LinkResponseType.CONSECUTIVE
        )
        yield from super()._fulfill_request(req)

    def _share_entanglement(self, req):
        tries = 0
        while not req.cancelled:
            link_ev = self.link_req.resp_event(self)
            purify_ev = self.purify_proto.await_signal(
                sender=self.purify_proto,
                signal_label=PurificationProtocol.PURIFICATION_COMPLETE
            )

            expr = yield link_ev | purify_ev
            if expr.first_term.value:
                resp = self.link_req.get_answare(self)
                if resp.result == LinkLayer.OK:
                    tries += resp.tries
                    self.purify_proto.add_pair(resp.qubit)
            else:
                qubit = self.purify_proto.get_signal_result(
                    PurificationProtocol.PURIFICATION_COMPLETE, self
                )
                return qubit, tries
            
        return None, None

    
    def _reset_link(self):
        self.link_req.cancelled = True
        self.purify_proto.reset()