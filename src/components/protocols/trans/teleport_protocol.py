
from netsquid.components.component import Message
from netsquid.components.instructions import \
    INSTR_CNOT, INSTR_H, INSTR_MEASURE, INSTR_X, INSTR_Z

from .transport_layer import TransportLayer
from ..util import *
from components.hardware import program_function, ProgramPriority
import inspect


class TeleportProtocol (TransportLayer):
    MEASUREMENT_RESULTS = 'MEASUREMENT_RESULTS'

    def __init__(self, node, cport, net_protocol, name=None) -> None:
        super().__init__(node, cport, name)
        self.minion = _TeleportMinion(node, self, name='minion')
        self.add_subprotocol(self.minion, name='minion')
        self.add_subprotocol(net_protocol, name='net_proto')
        self.net_proto = net_protocol
        self.cport = self.node.ports[cport]

    def run(self):
        self.start_subprotocols()
        return super().run()
    
    def _transmit(self, req):
        count = req.count
        net_req = self.net_proto.initiate_sharing(count)
        i = 0

        while i < count:
            net_ev = net_req.resp_event(self)
            pos_ev = self.await_signal(
                sender=self,
                signal_label=TransportLayer._POS_SPECIFIED
            )

            expr = yield net_ev | pos_ev
            if expr.first_term.value:
                net_resp = net_req.get_answare(self)
                req.answare(
                    transmit=self._transmit_hook(net_resp.qubit)
                )
            else:
                pos_resp = self.get_signal_result(TransportLayer._POS_SPECIFIED, self)
                self.minion.teleport(pos_resp['qpair'], pos_resp['position'])
                i += 1

    def _recieve(self, req):
        qubits = dict()
        net_req = self.net_proto.recieve()
        net_finished = False

        while len(qubits) > 0 or not net_finished:
            net_etgm = net_req.resp_event(self)
            transmitted = self.await_port_input(self.cport)

            expr = yield net_etgm | transmitted
            if expr.first_term.value:
                net_resp = net_req.get_answare(self)
                qubits[net_resp.qubit.id] = net_resp.qubit.position
                net_finished = net_resp.final
            else:
                trans_msg = self.cport.rx_input(header=TransportLayer.MSG_HEADER)
                if not trans_msg:
                    continue
                log.info(log.msg2str(trans_msg.items), into=self)
                data = trans_msg.items[1]
                id = data['id']
                self.minion.correct(qubits[id], data['cX'], data['cZ'], req)


class _TeleportMinion (QueuedProtocol):
    _TELEPORT = 'TELEPORT'

    TELEPORT_REQ = 'TELEPORT_REQ'
    CORRECT_REQ = 'CORRECT_REQ'

    def __init__(self, node, trans_proto, name=None):
        super().__init__(node, name)
        self.add_signal(_TeleportMinion._TELEPORT)
        self.proto = trans_proto

    def teleport(self, qpair, position):
        self._push_request(
            _TeleportMinion.TELEPORT_REQ, None,
            qpair=qpair, position=position
        )

    def correct(self, position, cX, cZ, req):
        self._push_request(
            _TeleportMinion.CORRECT_REQ, None,
            position=position, cX=cX, cZ=cZ, req=req
        )

    def run(self):
        while True:
            yield from self._await_request()
            for req in self._poll_requests():
                if req.req_label == _TeleportMinion.TELEPORT_REQ:
                    qubits = [req.position, req.qpair.position]
                    output = yield from self._measure(qubits)
                    self.node.qmemory.destroy(qubits)

                    trans_msg = [
                        TeleportProtocol.MEASUREMENT_RESULTS,
                        dict(
                            id=req.qpair.id,
                            cX=output['cX']==[1],
                            cZ=output['cZ']==[1]
                        )
                    ]
                    self.proto.cport.tx_output(Message(
                        trans_msg,
                        header=TransportLayer.MSG_HEADER
                    ))
                    log.info(log.msg2str(trans_msg), outof=self.proto)
                elif req.req_label == _TeleportMinion.CORRECT_REQ:
                    if req.cX or req.cZ:
                        yield from self._correct([req.position], req.cX, req.cZ)
                    req.req.answare(
                        position=req.position
                    )

    @program_function(2, ProgramPriority.HIGH, 'trans')
    def _measure(self, prog, qubits):
        [q1, q2] = qubits
        prog.apply(INSTR_CNOT, [q1, q2])
        prog.apply(INSTR_H, q1)
        prog.apply(INSTR_MEASURE, q1, output_key='cZ')
        prog.apply(INSTR_MEASURE, q2, output_key='cX')

    @program_function(1, ProgramPriority.HIGH, 'trans')
    def _correct(self, prog, qubit, cX, cZ):
        if cX: prog.apply(INSTR_X, qubit)
        if cZ: prog.apply(INSTR_Z, qubit)