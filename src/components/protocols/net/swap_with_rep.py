
from enum import Enum
from .network_layer import NetworkLayer, RoutingRole
from netsquid.components.component import Message
from netsquid.components.instructions import INSTR_X, INSTR_Z

from ..link.link_layer import LinkResponseType
from ..util import *
from components.hardware import program_function, ProgramPriority


class SwapWithRepeaterProtocol (NetworkLayer):
    Record = namedtuple('Record', ['position', 'net_id'])

    INIT_MSG = 'INIT_MSG'
    TRACK_MSG = 'TRACK_MSG'
    DISCARD_MSG = 'DISCARD_MSG'
    COMPLETE_MSG = 'COMPLETE_MSG'

    def __init__(self, node, cport, link_protocol, cutoff_time=None, name=None):
        super().__init__(node, cport, name)
        self.add_subprotocol(link_protocol, name='link_protocol')
        self.add_subprotocol(_SWRCorrectionMinion(node, self), name='minion')
        self.cutoff_time = cutoff_time
        self.records = dict()

    def run(self):
        self.start_subprotocols()
        yield from super().run()

    def _initiate(self, req):
        cport = self.node.ports[self.cport_name]

        if req.req_label == RoutingRole.HEADEND:
            req.session_id = uuid()
            msg = [
                SwapWithRepeaterProtocol.INIT_MSG,
                dict(
                    session_id=req.session_id,
                    count=req.count,
                    cutoff_time=self.cutoff_time
                )
            ]
            cport.tx_output(Message(msg,
                header=NetworkLayer.MSG_HEADER
            ))
            log.info(log.msg2str(msg), outof=self)
        elif req.req_label == RoutingRole.TAILEND:
            while True:
                yield self.await_port_input(cport)
                msg = cport.rx_input(header=NetworkLayer.MSG_HEADER)
                if not msg:
                    continue

                msg_type = msg.items[0]
                if msg_type != SwapWithRepeaterProtocol.INIT_MSG:
                    raise ValueError(f'Unexpected message type: {msg_type}, expected: {SwapWithRepeaterProtocol.INIT_MSG}')
                
                data = msg.items[1]
                req.count = data['count']
                req.session_id = data['session_id']
                log.info(log.msg2str(msg.items), into=self)
                break
        else:
            raise ValueError(f'Unknown role: {req.req_label}')

    def _swap(self, req):
        cport = self.node.ports[self.cport_name]
        link_proto = self.subprotocols['link_protocol']
        self.count = 0
        link_req = link_proto.request_entanglement(
            response_type=LinkResponseType.CONSECUTIVE
        )

        while self.count < req.count:
            resp_event = link_req.resp_event(self)
            msg_event = self.await_port_input(cport)

            expr = yield resp_event | msg_event
            if expr.first_term.value:
                self._handle_new_link_pair(req, link_req)
            else:
                self._handle_incoming_meassage(req)
    
        link_req.cancelled = True
        for rec in self.records.values():
            self.node.qmemory.destroy([rec.position])
        self.rec = dict()

    def _terminate(self, req):
        if req.req_label == RoutingRole.HEADEND:
            self._send_complete(req)
            yield from self._await_complete(req)
        else:
            yield from self._await_complete(req)
            self._send_complete(req)

    def _handle_new_link_pair(self, req, link_req):
        cport = self.node.ports[self.cport_name]
        resp = link_req.get_answare(self)

        if req.req_label == RoutingRole.HEADEND: net_id = etgmid('net')
        else: net_id = None

        self.records[resp.qubit.id] = self.Record(
            position=resp.qubit.position,
            net_id=net_id
        )
        msg = [
                SwapWithRepeaterProtocol.TRACK_MSG,
                dict(
                    id=resp.qubit.id,
                    net_id=net_id,
                    cX=False,
                    cZ=False
                )
            ]
        cport.tx_output(Message(msg,
            header=subheader(NetworkLayer.MSG_HEADER, req.session_id)
        ))
        log.info(f'Link ready -> {log.msg2str(msg)}', outof=self)

    def _handle_incoming_meassage(self, req):
        cport = self.node.ports[self.cport_name]
        msg = cport.rx_input(header=subheader(NetworkLayer.MSG_HEADER, req.session_id))
        if not msg:
            return

        [msg_type, data] = msg.items
        minion = self.subprotocols['minion']

        if msg_type == SwapWithRepeaterProtocol.TRACK_MSG:
            id = data['id']
            rec = self.records.pop(id)
            
            if req.req_label == RoutingRole.HEADEND: net_id = rec.net_id
            else: net_id = data['net_id']

            self.count += 1
            minion.correct(
                net_req=req,
                net_id=net_id,
                position=rec.position,
                cX=data['cX'],
                cZ=data['cZ'],
                final=self.count==req.count
            )
            log.info(f'Success #{self.count}: {log.msg2str(msg.items)}', into=self)
        elif msg_type == SwapWithRepeaterProtocol.DISCARD_MSG:
            id = data['id']
            rec = self.records.pop(id)
            self.node.qmemory.destroy([rec.position])
            log.info(f'Failed: {log.msg2str(msg.items)}', into=self)
        else:
            raise ValueError(f'Unexpected message type: {msg_type}')
        
    def _send_complete(self, req):
        cport = self.node.ports[self.cport_name]
        msg = [
            SwapWithRepeaterProtocol.COMPLETE_MSG,
            dict(session_id=req.session_id)
        ]
        cport.tx_output(Message(msg,
            header=subheader(NetworkLayer.MSG_HEADER, req.session_id),
        ))
        log.info(log.msg2str(msg), outof=self)

    def _await_complete(self, req):
        cport = self.node.ports[self.cport_name]
        log.info('Waiting for COMPLETE_MSG', at=self)
        while True:
            yield self.await_port_input(cport)
            msg = cport.rx_input(header=subheader(NetworkLayer.MSG_HEADER, req.session_id))
            if not msg:
                continue

            msg_type = msg.items[0]
            if (
                msg_type == SwapWithRepeaterProtocol.COMPLETE_MSG
                and msg.items[1]['session_id'] == req.session_id
            ):
                log.info(f'Recieved: {log.msg2str(msg.items)}', into=self)
                break


class _SWRCorrectionMinion (QueuedProtocol):
    def __init__(self, node, net_protocol, name=None):
        super().__init__(node, name)
        self.net_proto = net_protocol

    def run(self):
        while True:
            yield from self._await_request()
            for req in self._poll_requests():
                log.info(f'Correcting qubit with: cX: {req.cX}, cZ: {req.cZ}', at=self.net_proto)
                yield from self._correct([req.position], req.cX, req.cZ)
                req.net_req.answare(
                    qubit=EntanglementRecord(
                        position=req.position,
                        id=req.net_id
                    ),
                    final=req.final
                )
                log.info(f'Pair delivered with id {req.net_id}', at=self.net_proto)

    def correct(self, net_req, net_id, position, cX, cZ, final):
        self._push_request(
            None, None,
            net_req=net_req,
            net_id=net_id,
            position=position,
            cX=cX, cZ=cZ,
            final=final
        )

    @program_function(1, ProgramPriority.HIGH)
    def _correct(self, prog, qubits, cX, cZ):
        if cX: prog.apply(INSTR_X, qubits)
        if cZ: prog.apply(INSTR_Z, qubits)
