
from enum import Enum
import netsquid as ns
from netsquid.components.component import Message
from netsquid.components.instructions import INSTR_CNOT, INSTR_H, INSTR_MEASURE

from ..util import *
from .network_layer import NetworkLayer
from ..link import LinkResponseType
from .swap_with_rep import SwapWithRepeaterProtocol
from components.hardware import program_function, ProgramPriority


class RepeaterProtocol (
    StatefulProtocolTempalte(NodeProtocol),
):
    def __init__(self, node, cport1, link1, cport2, link2, name=None):
        self.log_layer = log.Layer.NETWORK
        super().__init__(node, name)
        self.add_subprotocol(_RepEtgmManagerMinion(node, self, f'{self.name}_MNGR'), name='etgm_minion')
        self.add_subprotocol(link1, name='link1')
        self.add_subprotocol(link2, name='link2')
        self.cport1_name = cport1
        self.cport2_name = cport2

    def create_statemachine(self):
        return RepeaterStatemachine(self)

    def run(self):
        self.start_subprotocols()
        yield from super().run()


class RepeaterState (Enum):
    IDLE = 'IDLE'
    SWAPPING = 'SWAPPING'
    TERMINATING = 'TERMINATING'


class RepeaterStatemachine (ProtocolStateMachine):
    def __init__(self, protocol):
        super().__init__(protocol)

    @protocolstate(RepeaterState.IDLE, initial=True)
    def _idle(self):
        cport1 = self.proto.node.ports[self.proto.cport1_name]
        cport2 = self.proto.node.ports[self.proto.cport2_name]

        set1 = (cport1, self.proto.subprotocols['link1'])
        set2 = (cport2, self.proto.subprotocols['link2'])

        while True:
            ev1 = self.proto.await_port_input(cport1)
            ev2 = self.proto.await_port_input(cport2)

            expr = yield ev1 | ev2
            if expr.first_term.value:
                msg = cport1.rx_input(header=NetworkLayer.MSG_HEADER)
                if not msg:
                    continue
                self.upstream = set1
                self.downstream = set2
            else:
                msg = cport2.rx_input(header=NetworkLayer.MSG_HEADER)
                if not msg:
                    continue
                self.upstream = set2
                self.downstream = set1

            msg_type = msg.items[0]
            if msg_type == SwapWithRepeaterProtocol.INIT_MSG:
                log.info(log.msg2str(msg.items), into=self.proto)
                data = msg.items[1]
                self.session = data['session_id']
                etgm_minion = self.proto.subprotocols['etgm_minion']
                etgm_minion.session = self.session
                etgm_minion.cutoff_time = data['cutoff_time']
                msg_forward = [SwapWithRepeaterProtocol.INIT_MSG, data]
                self.downstream[0].tx_output(Message(
                    msg_forward,
                    header=NetworkLayer.MSG_HEADER
                ))
                log.info(log.msg2str(msg_forward), outof=self.proto)
                break

        return RepeaterState.SWAPPING


    @protocolstate(RepeaterState.SWAPPING)
    def _swapping(self):
        etgm_minion = self.proto.subprotocols['etgm_minion']

        (port_up, link_up) = self.upstream
        (port_down, link_down) = self.downstream

        req_up = link_up.request_entanglement(
            response_type=LinkResponseType.CONSECUTIVE
        )
        req_down = link_down.request_entanglement(
            response_type=LinkResponseType.CONSECUTIVE
        )

        session_alive = True
        while session_alive:
            ev_ans_up = req_up.resp_event(self.proto)
            ev_ans_down = req_down.resp_event(self.proto)
            ev_msg_up = self.proto.await_port_input(port_up)
            ev_msg_down = self.proto.await_port_input(port_down)

            expr = yield (ev_ans_up | ev_ans_down) | (ev_msg_up | ev_msg_down)
            if expr.first_term.value:
                if expr.first_term.first_term.value:
                    resp = req_up.get_answare(self)
                    etgm_minion.register_upstream(resp.qubit)
                else:
                    resp = req_down.get_answare(self)
                    etgm_minion.register_downstream(resp.qubit)
            else:
                if expr.second_term.first_term.value:
                    msg = port_up.rx_input(
                        header=subheader(NetworkLayer.MSG_HEADER, self.session)
                    )
                    if msg:
                        session_alive = self._handle_incoming_messages(msg, port_down, port_up, True)
                else:
                    msg = port_down.rx_input(
                        header=subheader(NetworkLayer.MSG_HEADER, self.session)
                    )
                    if msg:
                        session_alive = self._handle_incoming_messages(msg, port_up, port_down, False)

        req_up.cancelled = True
        req_down.cancelled = True
        return RepeaterState.TERMINATING
    
    @protocolstate(RepeaterState.TERMINATING)
    def _terminating(self):
        (port_up, _) = self.upstream
        (port_down, _) = self.downstream

        ev_msg_up = self.proto.await_port_input(port_up)
        ev_msg_down = self.proto.await_port_input(port_down)

        while True:
            expr = yield ev_msg_up | ev_msg_down
            if expr.first_term.value:
                port_out = port_down
                msg = port_up.rx_input(
                    header=subheader(NetworkLayer.MSG_HEADER, self.session)
                )
            else:
                port_out = port_up
                msg = port_down.rx_input(
                    header=subheader(NetworkLayer.MSG_HEADER, self.session)
                )
            if not msg:
                continue

            if msg.items[0] == SwapWithRepeaterProtocol.COMPLETE_MSG:
                log.info(log.msg2str(msg.items), into=self.proto)
                port_out.tx_output(Message(
                    msg.items,
                    header=subheader(NetworkLayer.MSG_HEADER, self.session)
                ))
                log.info(log.msg2str(msg.items), outof=self.proto)
                break
        return RepeaterState.IDLE


    def _handle_incoming_messages(self, batch_msg, next_hop_port, last_hop_port, track_correction):
        etgm_minion = self.proto.subprotocols['etgm_minion']
        log.info(log.msg2str(batch_msg.items), into=self.proto)

        i = 0
        while i < len(batch_msg.items):
            msg_type = batch_msg.items[i]
            if msg_type == SwapWithRepeaterProtocol.COMPLETE_MSG:
                etgm_minion.reset()
                complete_msg = [SwapWithRepeaterProtocol.COMPLETE_MSG, batch_msg.items[i+1]]
                next_hop_port.tx_output(Message(
                    complete_msg,
                    header=subheader(NetworkLayer.MSG_HEADER, self.session)
                ))
                log.info(log.msg2str(complete_msg), outof=self.proto)
                return False
            elif msg_type == SwapWithRepeaterProtocol.DISCARD_MSG:
                data = batch_msg.items[i + 1]
                etgm_minion.discard(data, next_hop_port)
                i += 1
            elif msg_type == SwapWithRepeaterProtocol.TRACK_MSG:
                data = batch_msg.items[i + 1]
                etgm_minion.track(data, next_hop_port, last_hop_port, track_correction)
                i += 1
            i += 1
        return True


class _LinkRecord:
    def __init__(self, qubit, cutoff_time):
        self.qubit = qubit
        self.time = ns.sim_time() + cutoff_time

    def until_cutoff(self):
        return self.time - ns.sim_time()
    

class _TrackRecord:
    def __init__(self, data, next_hop_port, last_hop_port, track_correction):
        self.data = data
        self.next_hop_port = next_hop_port
        self.last_hop_port = last_hop_port
        self.track_correction = track_correction


class _SwapRecord:
    def __init__(self, id1, id2, cX, cZ):
        self.id1 = id1
        self.id2 = id2
        self.cX = cX
        self.cZ = cZ
        self.time = ns.sim_time()
        self.tracks = 0


class _DiscardRecord:
    def __init__(self, id):
        self.id = id
        self.time = ns.sim_time()


class _RepEtgmManagerMinion (NodeProtocol):
    _LINK_READY = 'LINK_READY'
    _RESET = 'RESET'

    def __init__(self, node, rep_proto, name=None):
        super().__init__(node, name)
        self.add_signal(_RepEtgmManagerMinion._LINK_READY)
        self.add_signal(_RepEtgmManagerMinion._RESET)
        self.reset(init=True)
        self.rep_proto = rep_proto

    def reset(self, init=False):
        if not init:
            log.info(f'{self._upstream}, {self._downstream}')
            for link_rec in self._upstream:
                self.node.qmemory.destroy([link_rec.qubit.position])
            for link_rec in self._downstream:
                self.node.qmemory.destroy([link_rec.qubit.position])
        
        self._upstream = []
        self._downstream = []
        self._track_queue = []
        self._swap_records = []
        self._discard_records = []
        self.send_signal(_RepEtgmManagerMinion._RESET)

    def run(self):
        while True:
            link_ready = self.await_signal(
                sender=self,
                signal_label=_RepEtgmManagerMinion._LINK_READY
            )
            reset_ev = self.await_signal(
                sender=self,
                signal_label=_RepEtgmManagerMinion._RESET
            )
            next_cutoff = None
            if len(self._upstream) > 0:
                next_cutoff = self._upstream[0].time
            elif len(self._downstream) > 0:
                next_cutoff = self._downstream[0].time

            if next_cutoff is not None:
                next_cutoff = max(next_cutoff, ns.sim_time())
                qubit_expired = self.await_timer(end_time=next_cutoff)
                expr = yield link_ready | (qubit_expired | reset_ev)
                if expr.first_term.value:
                    yield from self._attempt_swap()
                elif expr.second_term.first_term.value:
                    self._handle_expired_qubit()
            else:
                expr = yield link_ready | reset_ev
                if expr.first_term.value:
                    yield from self._attempt_swap()

    def register_upstream(self, qubit):
        self._upstream.append(_LinkRecord(qubit, self.cutoff_time))
        self.send_signal(_RepEtgmManagerMinion._LINK_READY)

    def register_downstream(self, qubit):
        self._downstream.append(_LinkRecord(qubit, self.cutoff_time))
        self.send_signal(_RepEtgmManagerMinion._LINK_READY)

    def discard(self, data, next_hop_port):
        for i in range(len(self._swap_records)):
            rec = self._swap_records[i]
            rec_found = False

            if rec.id1 == data['id']:
                rec_found = True
                data['id'] = rec.id2
            elif rec.id2 == data['id']:
                rec_found = True
                data['id'] = rec.id1

            if rec_found:
                self._swap_records.remove(rec)
                disc_msg = [SwapWithRepeaterProtocol.DISCARD_MSG, data]
                next_hop_port.tx_output(Message(
                    disc_msg,
                    header=subheader(NetworkLayer.MSG_HEADER, self.session)
                ))
                log.info(log.msg2str(disc_msg), outof=self.rep_proto)
                return

    def track(self, data, next_hop_port, last_hop_port, track_correction):
        track_rec = _TrackRecord(data, next_hop_port, last_hop_port, track_correction)

        for i in range(len(self._swap_records)):
            rec = self._swap_records[i]
            sent = self._track_and_swap(track_rec, rec)
            if sent:
                self._tracked(i)
                return
                
        for rec in self._discard_records:
            sent = self._track_and_discard(track_rec, rec)
            if sent:
                self._discard_records.remove(rec)
                return

        in_up = any(data['id'] == rec.qubit.id for rec in self._upstream)
        in_down = any(data['id'] == rec.qubit.id for rec in self._downstream)

        #if in_up or in_down:
        self._track_queue.append(_TrackRecord(
            data, next_hop_port, last_hop_port, track_correction))
        log.info(f'Queued: {log.msg2str([SwapWithRepeaterProtocol.TRACK_MSG, data])}', at=self.rep_proto)
        #else:
        #    id = data['id']
        #    raise ValueError(f'Recieved track message for unknown qubit: {id}')
        
    def _track_and_swap(self, track_rec, swap_rec):
        data = track_rec.data
        rec_found = False

        if swap_rec.id1 == data['id']:
            rec_found = True
            data['id'] = swap_rec.id2
        elif swap_rec.id2 == data['id']:
            rec_found = True
            data['id'] = swap_rec.id1

        if rec_found:
            if track_rec.track_correction:
                if swap_rec.cX: data['cX'] = not data['cX']
                if swap_rec.cZ: data['cZ'] = not data['cZ']
            track_msg = [SwapWithRepeaterProtocol.TRACK_MSG, data]
            track_rec.next_hop_port.tx_output(Message(
                track_msg,
                header=subheader(NetworkLayer.MSG_HEADER, self.session)
            ))
            log.info(log.msg2str(track_msg), outof=self.rep_proto)
        return rec_found
    
    def _track_and_discard(self, track_rec, discard_rec):
        data = track_rec.data
        if discard_rec.id == data['id']:
            disc_msg = [SwapWithRepeaterProtocol.DISCARD_MSG, data]
            track_rec.last_hop_port.tx_output(Message(
                disc_msg,
                header=subheader(NetworkLayer.MSG_HEADER, self.session)
            ))
            log.info(log.msg2str(disc_msg), outof=self.rep_proto)
            return True
        return False

    def _tracked(self, index):
        rec = self._swap_records[index]
        rec.tracks += 1
        if rec.tracks == 2:
            self._swap_records = self._swap_records[index+1:]
            if len(self._discard_records) > 0: 
                di = next(i for i, drec in enumerate(self._discard_records) if drec.time >= rec.time)
                self._discard_records = self._discard_records[di:]

    def _attempt_swap(self):
        if len(self._upstream) > 0 and len(self._downstream) > 0:
            q_up = self._upstream.pop(0).qubit
            q_down = self._downstream.pop(0).qubit
            log.info(f'Attempting swap: {q_up.id}, {q_down.id}', at=self.rep_proto)
            output = yield from self.swap([q_up.position, q_down.position])
            log.info(f'PROGRAM OUTPUT: {output}', at=self.rep_proto)
            self.node.qmemory.destroy([q_up.position, q_down.position])
            rec = _SwapRecord(
                q_up.id, q_down.id,
                output['cX']==[1], output['cZ']==[1]
            )
            log.info(f'Swapped qubits {q_up.id}, {q_down.id}, cX: {rec.cX}, cZ: {rec.cZ}', at=self.rep_proto)

            to_remove = []
            for track in self._track_queue:
                sent = self._track_and_swap(track, rec)
                if sent:
                    to_remove.append(track)
                    #self._track_queue.remove(track)
            for track in to_remove:
                self._track_queue.remove(track)
            self._swap_records.append(rec)
                
    def _handle_expired_qubit(self):
        if len(self._upstream) > 0:
            rec = self._upstream.pop(0)
        else:
            rec = self._downstream.pop(0)
        discard_rec = _DiscardRecord(rec.qubit.id)
        self.node.qmemory.destroy([rec.qubit.position])
        log.info(f'Qubit expired: {rec.qubit.id}', at=self.rep_proto)
        for track in self._track_queue:
            sent = self._track_and_discard(track, discard_rec)
            if sent:
                self._track_queue.remove(track)
                return
        self._discard_records.append(discard_rec)

    @program_function(2, ProgramPriority.HIGH, 'swap')
    def swap(self, prog, qubits):
        [q1, q2] = qubits
        prog.apply(INSTR_CNOT, [q1, q2])
        prog.apply(INSTR_H, q1)
        prog.apply(INSTR_MEASURE, q1, output_key='cZ')
        prog.apply(INSTR_MEASURE, q2, output_key='cX')
