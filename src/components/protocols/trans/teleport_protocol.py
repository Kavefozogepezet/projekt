
from netsquid.components.component import Message
from netsquid.components.instructions import \
    INSTR_CNOT, INSTR_H, INSTR_MEASURE, INSTR_X, INSTR_Z

from .transport_layer import TransportLayer
from ..util import *
from components.hardware import program_function, ProgramPriority


class TeleportProtocol (TransportLayer):
    MEASUREMENT_RESULTS = 'MEASUREMENT_RESULTS'

    def __init__(self, node, cport, net_protocol, name=None) -> None:
        super().__init__(node, cport, name)
        self.add_subprotocol(net_protocol, name='net_proto')
        self.net_proto = net_protocol
        self.cport = self.node.ports[cport]

    def run(self):
        self.start_subprotocols()
        return super().run()
    
    def _transmit(self, req):
        count = req.count
        req = self.net_proto.initiate_sharing(count=count)

        for _ in range(count):
            net_resp = yield from req.await_as(self)
            req.answare(
                transmit=self._transmit_hook()
            )
            yield self.await_signal(
                sender=self,
                signal_label=TransportLayer._POS_SPECIFIED
            )
            pos_resp = self.get_signal_result(TransportLayer._POS_SPECIFIED, self)
            qubits = [net_resp.qubit.position, pos_resp.position]
            output = yield from self._measure(qubits)
            self.node.qmemory.destroy([net_resp.qubit.position])

            trans_msg = [
                TransportLayer.MEASUREMENT_RESULTS,
                dict(
                    id=net_resp.qubit.id,
                    cX=output['cX'],
                    cZ=output['cZ']
                )
            ]
            self.cport.tx_output(Message(
                trans_msg,
                header=TransportLayer.MSG_HEADER
            ))


    def _recieve(self, req):
        qubits = dict()
        req = self.net_proto.recieve()
        net_finished = False

        while len(qubits) > 0 and not net_finished:
            net_etgm = req.resp_event(self)
            transmitted = self.await_port_input(self.cport)

            expr = yield net_etgm | transmitted
            if expr.first_term.value:
                net_msg = req.get_answare(self)
                qubits[net_msg.qubit.id] = net_msg.qubit.position
                net_finished = net_msg.finished
            else:
                trans_msg = self.cport.rx_input(header=TransportLayer.MSG_HEADER)
                data = trans_msg.items[1]
                id = data['id']
                yield from self._correct([qubits[id]], data['cX'], data['cZ'])
                req.answare(
                    porition=qubits[id]
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
