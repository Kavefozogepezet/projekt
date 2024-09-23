
import netsquid as ns
from enum import Enum
from netsquid.protocols import NodeProtocol

from ..util import *
from simlog import log


class BSAState (Enum):
    WAITING_TICK = 'BSAState.WAITING_TICK',
    WAITING_OFFSET = 'BSAState.WAITING_OFFSET',
    WAITING_PHOTON_1 = 'BSAState.WAITING_PHOTON_1'
    WAITING_PHOTON_2 = 'BSAState.WAITING_PHOTON_2'


class BSAProtocol(StatefulProtocolTempalte(NodeProtocol)):
    SUCCESS = 'BSAProtocol.SUCCESS'
    FAILURE = 'BSAProtocol.FAILURE'

    def __init__(self, node, clock, detection_offset, detection_window, name=None):
        super().__init__(node, name)
        if detection_offset + detection_window > clock.delta_time():
            raise ValueError('Detection time exceeds clock period.')
        
        self.detection_offset = detection_offset
        self.detection_window = detection_window
        self.clock = clock

    def create_statemachine(self):
        return BSAProtocolStatemachine(self)

    def run(self):
        sm = BSAProtocolStatemachine(self)
        yield from sm.run()


class BSAProtocolStatemachine (ProtocolStateMachine):
    @protocolstate(BSAState.WAITING_TICK, initial=True)
    def _waiting_tick(self):
        yield self.proto.await_signal(
            sender=self.proto.clock,
            signal_label=Clock.TICK
        )
        return BSAState.WAITING_OFFSET
    
    @protocolstate(BSAState.WAITING_OFFSET)
    def _waiting_offset(self):
        yield self.proto.await_timer(self.proto.detection_offset)
        return BSAState.WAITING_PHOTON_1
    
    @protocolstate(BSAState.WAITING_PHOTON_1, BSAState.WAITING_PHOTON_2)
    def _waiting_photons(self):
        qportA = self.proto.node.ports['qinA']
        qportB = self.proto.node.ports['qinB']

        detection_window_expire = self.proto.await_timer(
            self.proto.detection_window
        )
        photon_arrived = (
            self.proto.await_port_input(qportA)
            | self.proto.await_port_input(qportB)
        )
        event = yield detection_window_expire | photon_arrived

        if event.second_term.value:
            return self._process_photon()
        else:
            log.info(f'BSA detected photon loss', at=self.proto.node)
            self._announce(BSAProtocol.FAILURE)
            return BSAState.WAITING_TICK
        
    def _process_photon(self):
        if self.get_state() == BSAState.WAITING_PHOTON_1:
            return BSAState.WAITING_PHOTON_2
        else:
            mem = self.proto.node.qmemory
            mem.operate(ns.CNOT, [0, 1])
            mem.operate(ns.H, 0)
            [mX, mZ], _ = mem.measure([0, 1])
            if mZ == 0:
                log.info(f'BSA found undistinguishable state', at=self.proto.node)
                self._announce(BSAProtocol.FAILURE)
            else:
                log.info(f'BSA conducted successful measurement', at=self.proto.node)
                self._announce(
                    BSAProtocol.SUCCESS,
                    { 'cX': mZ, 'cZ': mX },
                    { 'cX': 0, 'cZ': 0 }
                )
            return BSAState.WAITING_TICK

    def _announce(self, result, A=None, B=None):
        cportA = self.proto.node.ports['coutA']
        cportB = self.proto.node.ports['coutB']
        cportA.tx_output((result, A))
        log.info(f'BSA message to A -> result: {result}, msg: {A}', outof=self.proto.node)
        cportB.tx_output((result, B))
        log.info(f'BSA message to B -> result: {result}, msg: {B}', outof=self.proto.node)
