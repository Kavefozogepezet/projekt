
from enum import Enum
from collections import namedtuple
import numpy as np
import netsquid as ns
from netsquid.components.instructions import INSTR_CNOT, INSTR_MEASURE, INSTR_Y, INSTR_ROT_X
from netsquid.components.component import Message

from components.hardware.nvcprocessor import program_function, ProgramPriority
from ..util import *


class _RecordType(Enum):
    MEASURED = 'MEASURED'
    RECIEVED = 'RECIEVED'


_PurificationRecord = namedtuple(
    'PurificationRecord',
    ['type', 'id1', 'id2', 'result', 'req']
)


class DEJMPSProtocol (NodeProtocol):
    PURIFY_QUBITS = 'PURIFY_QUBITS'
    PURIFICATION_COMPLETE = 'PURIFICATION_COMPLETE'

    ITER_MSG = 'ITER_MSG'

    @staticmethod
    def get_header(layer=None):
        if layer is None:
            return 'DEJMPS'
        else:
            return f'DEJMPS({layer})'

    def __init__(self, node, cport, mode, log_layer=None, name=None, prog_reason=None):
        super().__init__(node, name)
        self.add_signal(DEJMPSProtocol.PURIFICATION_COMPLETE)
        if log_layer:
            self.log_layer = log_layer
        self.MSG_HEADER = DEJMPSProtocol.get_header(log_layer)
        self.cport = self.node.ports[cport]
        self.mode = mode
        self.records = dict()
        self.minion = _PurificationMinion(self.node, self)
        self.add_subprotocol(self.minion, name='minion')
        if prog_reason:
            self.prog_reason = prog_reason
            self.minion.prog_reason = prog_reason

    def run(self):
        self.start_subprotocols()
        while True:
            ev_minion = self.await_signal(
                sender=self.minion,
                signal_label=_PurificationMinion.MEASUREMENT_COMPLETED
            )
            ev_input = self.await_port_input(self.cport)

            expr = yield ev_minion | ev_input
            if expr.first_term.value:
                record = self.minion.get_signal_result(
                    _PurificationMinion.MEASUREMENT_COMPLETED, self)
                msgrec = self.records.get((record.id1, record.id2))
                if msgrec is not None:
                    if msgrec.type != _RecordType.RECIEVED:
                        raise ValueError(f'Unexpected record type: {msgrec.type}, tried to purify {(record.id1, record.id2)} twice.')
                    self._announce(record.req, record.result==msgrec.result, record.id1, record.id2)
                else:
                    self.records[(record.id1, record.id2)] = record
            else:
                msg = self.cport.rx_input(header=self.MSG_HEADER)
                if not msg: continue
                log.info(log.msg2str(msg.items), into=self)
                [msg_type, data] = msg.items
                if msg_type == DEJMPSProtocol.ITER_MSG:
                    id1 = data['qubit1']
                    id2 = data['qubit2']
                    result = data['result']
                    localrec = self.records.get((id1, id2))
                    if localrec is not None:
                        if localrec.type != _RecordType.MEASURED:
                            raise ValueError(f'Unexpected record type: {localrec.type}, tried to purify {(id1, id2)} twice.')
                        self._announce(localrec.req, localrec.result==result, id1, id2)
                    else:
                        self.records[(id1, id2)] = _PurificationRecord(
                            _RecordType.RECIEVED, id1, id2, result, None
                        )
                else:
                    raise ValueError(f'Unexpected message type: {msg_type}')

    def purify(self, qubit1, qubit2):
        req = ProtocolRequest(
            self,
            DEJMPSProtocol.PURIFY_QUBITS,
            DEJMPSProtocol.PURIFICATION_COMPLETE
        )
        self.minion.purify(qubit1, qubit2, req)
        return req

    def reset(self):
        self.records.clear()

    def _announce(self, req, keep, id1, id2):
        log.info(f'Iteration result: {keep}, {id1} -X {id2}', at=self)
        req.answare(
            keep=keep,
            qubit1=id1,
            qubit2=id2
        )


class _PurificationMinion (QueuedProtocol):
    PERFORM_PURIFICATION = 'PERFORM_PURIFICATION'
    MEASUREMENT_COMPLETED = 'MEASUREMENT_COMPLETED'


    def __init__(self, node, dejmps, name=None):
        super().__init__(node, name)
        self.add_signal(_PurificationMinion.MEASUREMENT_COMPLETED)
        self.dejmps = dejmps

    def run(self):
        while True:
            yield from self._await_request()
            for req in self._poll_requests():
                log.info(f'Purifying qubits: {req.q1.id} -X {req.q2.id}', at=self.dejmps)
                output = yield from self.perform_purification([req.q1.position, req.q2.position])
                [result] = output['m']

                msg = [
                    DEJMPSProtocol.ITER_MSG,
                    dict(
                        result=result,
                        qubit1=req.q1.id,
                        qubit2=req.q2.id
                    )
                ]
                self.dejmps.cport.tx_output(Message(msg,
                    header=self.dejmps.MSG_HEADER
                ))
                log.info(log.msg2str(msg), outof=self.dejmps)
                self.send_signal(
                    _PurificationMinion.MEASUREMENT_COMPLETED,
                    _PurificationRecord(_RecordType.MEASURED, req.q1.id, req.q2.id, result, req.master_req)
                )


    def purify(self, q1, q2, req):
        self._push_request(
            _PurificationMinion.PERFORM_PURIFICATION,
            _PurificationMinion.MEASUREMENT_COMPLETED,
            q1=q1, q2=q2,
            master_req=req
        )

    @program_function(2, ProgramPriority.REAL_TIME)
    def perform_purification(self, prog, qubits):
        [q1, q2] = qubits
        angle = np.pi/2 if self.dejmps.mode else -np.pi/2
        prog.apply(INSTR_ROT_X, [q1], angle=angle)
        prog.apply(INSTR_ROT_X, [q2], angle=angle)
        prog.apply(INSTR_CNOT, [q1, q2])
        prog.apply(INSTR_MEASURE, q2, output_key='m')
