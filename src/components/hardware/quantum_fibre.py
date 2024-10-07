
from netsquid.nodes.connections import Connection
from netsquid.components.qchannel import QuantumChannel
from netsquid.components.models.delaymodels import FibreDelayModel
from netsquid.components.models.qerrormodels import DepolarNoiseModel, FibreLossModel
import numpy as np


class QuantumFibre (Connection):
    def __init__ (self, name, length, attenuation=0.2, refractive_index=1.45):
        super().__init__(name)

        if refractive_index < 1:
            raise ValueError('Refractive index must be greater than 1')
        
        A2B_channel_name = f'{name}_A2B'
        A2B_channel = self._prepare_channel(
            A2B_channel_name, length, attenuation, refractive_index)
        
        B2A_channel_name = f'{name}_B2A'
        B2A_channel = self._prepare_channel(
            B2A_channel_name, length, attenuation, refractive_index)
        
        self.add_subcomponent(
            A2B_channel, name=A2B_channel_name,
            forward_input=[('A', 'send')],
            forward_output=[('B', 'recv')],
        )
        self.add_subcomponent(
            B2A_channel, name=B2A_channel_name,
            forward_input=[('B', 'send')],
            forward_output=[('A', 'recv')],
        )

    def _prepare_channel(self, name, length, attenuation, refractive_index):
        return QuantumChannel(
            name=name,
            length=length,
            models={
                'quantum_noise_model': DepolarNoiseModel(
                    time_independent=True,
                    depolar_rate=(1 - np.exp(-attenuation*length/4))
                ),
                'delay_model': FibreDelayModel(c=299792/refractive_index),
                'quantum_loss_model': FibreLossModel(
                    p_loss_init=0, # TODO
                    p_loss_length=attenuation
                )
            }
        )