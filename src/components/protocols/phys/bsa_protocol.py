
import numpy as np
import netsquid as ns
from enum import Enum
from netsquid.protocols import NodeProtocol
from netsquid.components.component import Message

from ..util import *
from components.protocols.phys import PhysicalLayer
from simlog import log


class BSAState (Enum):
    WAITING_TICK = 'WAITING_TICK'
    WAITING_OFFSET = 'WAITING_OFFSET'
    WAITING_PHOTON_1 = 'WAITING_PHOTON_1'
    WAITING_PHOTON_2 = 'WAITING_PHOTON_2'


class BSAProtocol(StatefulProtocolTempalte(NodeProtocol)):
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'

    def __init__(self, node, clock, detection_offset, detection_window, detector_efficiency=1, name=None):
        self.log_layer = log.Layer.PHYSICAL
        super().__init__(node, name)
        if detection_offset + detection_window > clock.delta_time():
            raise ValueError('Detection time exceeds clock period.')
        
        self.detection_offset = detection_offset
        self.detection_window = detection_window
        self.detector_eff = detector_efficiency
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
            log.info(f'Unsuccessful Bell-state measurement: photon loss', at=self.proto)
            self._announce(BSAProtocol.FAILURE)
            return BSAState.WAITING_TICK
        
    def _process_photon(self):
        if self.get_state() == BSAState.WAITING_PHOTON_1:
            return BSAState.WAITING_PHOTON_2
        else:
            detected = np.random.rand() <= self.proto.detector_eff**2
            if not detected:
                log.info(f'Unsuccessful Bell-state measurement: a detector did not work', at=self.proto)
                self._announce(BSAProtocol.FAILURE)
                return BSAState.WAITING_TICK

            mem = self.proto.node.qmemory
            mem.operate(ns.CNOT, [0, 1])
            mem.operate(ns.H, 0)
            [mX, mZ], _ = mem.measure([0, 1])
            if mZ == 0:
                log.info(f'Unsuccessful Bell-state measurement: undistinguishable state', at=self.proto)
                self._announce(BSAProtocol.FAILURE)
            else:
                id = etgmid('link')
                log.info(f'Successful Bell-state measurement, assigned id: {id}', at=self.proto)
                self._announce(
                    BSAProtocol.SUCCESS,
                    dict(id=id, cX=mZ==1, cZ=mX==1),
                    dict(id=id, cX=False, cZ=False)
                )
            return BSAState.WAITING_TICK

    def _announce(self, result, A=None, B=None):
        cportA = self.proto.node.ports['coutA']
        cportB = self.proto.node.ports['coutB']
        msgA = [result, A] if A else [result]
        msgB = [result, B] if B else [result]

        cportA.tx_output(Message(msgA, header=PhysicalLayer.MSG_HEADER))
        log.info(f'To A: {log.msg2str(msgA)}', outof=self.proto)
        cportB.tx_output(Message(msgB, header=PhysicalLayer.MSG_HEADER))
        log.info(f'To B: {log.msg2str(msgB)}', outof=self.proto)
