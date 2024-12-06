
import numpy as np
from components.hardware import program_function, ProgramPriority
from netsquid.components.component import Message
from netsquid.components.instructions import \
    INSTR_INIT, INSTR_H, INSTR_X, INSTR_MEASURE

from .qkd import *
from ..trans import TransportMethod


class BB84Protocol(QKDProtocol):
    MSG_HEADER = 'BB84Protocol'

    REVEAL_BASES = 'REVEAL_BASES'
    REVEAL_TEST_KEY = 'REVEAL_TEST_KEY'

    def __init__(self, node, cport, transport_protocol, partition=None, name=None):
        super().__init__(node, name)
        self.add_subprotocol(transport_protocol, name='transport_protocol')
        self.cport = self.node.ports[cport]
        self.trans_proto = transport_protocol
        self.part = partition

    def run(self):
        self.start_subprotocols()
        return super().run()

    def _generate_qubits(self, req):
        req.total_len = req.length * 2
        trans_req = self.trans_proto.transmit(TransportMethod.PULL, req.total_len)
        [self.bits, self.bases] = np.random.randint(2, size=(2, req.total_len), dtype=np.ubyte)

        for i, (bit, base) in enumerate(zip(self.bits, self.bases)):
            resp = yield from trans_req.await_as(self)
            [q] = self.node.qmemory.allocate(1, self.part)
            yield from self._prepare([q], base, bit)
            resp.transmit(q)
            print(f'Generated qubit #{i+1}/{req.total_len} with base {base} and bit {bit}')

    def _recieve_qubits(self, req):
        req.total_len = req.length * 2
        trans_req = self.trans_proto.recieve()
        self.bits = np.zeros(req.total_len, dtype=int)
        self.bases = np.random.randint(2, size=req.total_len)

        for i, base in enumerate(self.bases):
            resp = yield from trans_req.await_as(self)
            pos = resp.position
            output = yield from self._measure([pos], base)
            [self.bits[i]] = output['bit']
            self.node.qmemory.destroy([pos])
            print(f'Recieved qubit #{i+1}/{req.total_len}, measured {self.bits[i]} in base {base}')

    def _sender_reveal(self, req):
        bases = (yield from self._recieve_msg(BB84Protocol.REVEAL_BASES))['bases']
        same = self.bases == bases
        self._send_msg(BB84Protocol.REVEAL_BASES, dict(same=same))
        same_base = self.bits[same]
        real_key, test_key = self._split_key(same_base)
        other_test_key = (yield from self._recieve_msg(BB84Protocol.REVEAL_TEST_KEY))['test_key']
        test_same = test_key == other_test_key
        self._send_msg(BB84Protocol.REVEAL_TEST_KEY, dict(test_same=test_same))
        # TODO consider packbits
        test_key = test_same.astype(np.ubyte)
        req.answare(key=real_key, test_key=test_key)
    
    def _reciever_reveal(self, req):
        self._send_msg(BB84Protocol.REVEAL_BASES, dict(bases=self.bases))
        same = (yield from self._recieve_msg(BB84Protocol.REVEAL_BASES))['same']
        same_base = self.bits[same]
        real_key, test_key = self._split_key(same_base)
        self._send_msg(BB84Protocol.REVEAL_TEST_KEY, dict(test_key=test_key))
        test_same = (yield from self._recieve_msg(BB84Protocol.REVEAL_TEST_KEY))['test_same']
        # TODO consider packbits
        test_key = test_same.astype(np.ubyte)
        req.answare(key=real_key, test_key=test_key)

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
        #test_key = same_base[::3].copy()
        #real_key = np.delete(same_base, slice(None, None, 3))
        #return real_key, test_key
        return same_base, np.zeros(0)

    @program_function(1, ProgramPriority.HIGH, 'qkd')
    def _prepare(self, prog, qubits, base, bit):
        [q] = qubits
        prog.apply(INSTR_INIT, q)
        if bit == 1:
            prog.apply(INSTR_X, q)
        if base == 1:
            prog.apply(INSTR_H, q)

    @program_function(1, ProgramPriority.HIGH, 'qkd')
    def _measure(self, prog, qubits, base):
        [q] = qubits
        if base == 1:
            prog.apply(INSTR_H, q)
        prog.apply(INSTR_MEASURE, q, output_key='bit')
