
import numpy as np
from components.hardware import program_function, ProgramPriority
from netsquid.components.component import Message
from netsquid.components.instructions import \
    INSTR_INIT, INSTR_H, INSTR_X, INSTR_MEASURE

from .qkd import *


class BB84Protocol(QKDProtocol):
    MSG_HEADER = 'BB84Protocol'

    REVEAL_BASES = 'REVEAL_BASES'
    REVEAL_TEST_KEY = 'REVEAL_TEST_KEY'

    def __init__(self, node, cport, transport_protocol, name=None):
        super().__init__(node, name)
        self.add_subprotocol(transport_protocol, name='transport_protocol')
        self.cport = self.node.ports[cport]
        self.trans_proto = transport_protocol

    def _generate_qubits(self, req):
        req.total_len = req.length * 3
        trans_req = self.trans_proto.transmit(req.total_len)
        [self.bits, self.bases] = np.random.randint(2, size=(2, req.total_len))

        for bit, base in zip(self.bits, self.bases):
            resp = yield from trans_req.await_as(self)
            q = self.node.qmemory.allocate(1)
            yield from self._prepare(q, base, bit)
            resp.transmit(q)

    def _recieve_qubits(self, req):
        req.total_len = req.length * 3
        trans_req = self.trans_proto.recieve()
        self.bits = np.zeros(req.length, dtype=int)
        self.bases = np.random.randint(2, size=req.length)

        for i, base in enumerate(self.bases):
            resp = yield from trans_req.await_as(self)
            pos = resp.position
            output = yield from self._measure(pos, base)
            self.bits[i] = output['bit']

    def _sender_reveal(self, req):
        bases = self._recieve_msg(BB84Protocol.REVEAL_BASES)['bases']
        same = self.bases == bases
        self._send_msg(BB84Protocol.REVEAL_BASES, dict(same=same))
        same_base = self.bits[same]
        real_key, test_key = self._split_key(same_base)
        other_test_key = self._recieve_msg(BB84Protocol.REVEAL_TEST_KEY)['test_key']
        test_same = test_key == other_test_key
        self._send_msg(BB84Protocol.REVEAL_TEST_KEY, dict(test_same=test_same))
        # TODO consider packbits
        req.answare(key=real_key, test_key=test_same)
    
    def _reciever_reveal(self, req):
        self._send_msg(BB84Protocol.REVEAL_BASES, dict(bases=self.bases))
        same = self._recieve_msg(BB84Protocol.REVEAL_BASES)['same']
        same_base = self.bits[same]
        real_key, test_key = self._split_key(same_base)
        self._send_msg(BB84Protocol.REVEAL_TEST_KEY, dict(test_key=test_key))
        test_same = self._recieve_msg(BB84Protocol.REVEAL_TEST_KEY)['test_same']
        # TODO consider packbits
        req.answare(key=real_key, test_key=test_same)

    def _send_msg(self, label, data):
        msg = [label, data]
        self.cport.tx_output(Message(
            msg, header=BB84Protocol.MSG_HEADER
        ))
        log.info(log.msg2str(msg), outof=self)

    def _recieve_msg(self, label):
        while True:
            yield self.await_port_input(self.cport)
            msg = self.cport.rx_input(header=BB84Protocol.MSG_HEADER)
            if not msg: continue

            if msg.items[0] == label:
                log.info(log.msg2str(msg.items), into=self)
                return msg.items[1]

    def _split_key(self, same_base):
        test_key = same_base[::3].copy()
        real_key = np.delete(same_base, slice(None, None, 3))
        return real_key, test_key

    @program_function(1, ProgramPriority.HIGH)
    def _prepare(self, prog, qubits, base, bit):
        [q] = qubits
        prog.apply(INSTR_INIT, q)
        if base == 1:
            prog.apply(INSTR_H, q)
        if bit == 1:
            prog.apply(INSTR_X, q)

    @program_function(1, ProgramPriority.HIGH)
    def _prepare(self, prog, qubits, base):
        [q] = qubits
        if base == 1:
            prog.apply(INSTR_H, q)
        prog.apply(INSTR_MEASURE, q, output_key='bit')
