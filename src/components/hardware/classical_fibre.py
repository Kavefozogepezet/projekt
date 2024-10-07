from netsquid.nodes.connections import Connection
from netsquid.components.cchannel import ClassicalChannel
from netsquid.components.models.delaymodels import FibreDelayModel


class ClassicalFibre (Connection):
    def __init__(self, name, length, refractive_index=1.45):
        super().__init__(name)

        if refractive_index < 1:
            raise ValueError('Refractive index must be greater than 1')

        A2B_channel_name = f'{name}_A2B'
        A2B_channel = self._prepare_channel(
            A2B_channel_name, length, refractive_index)
        
        B2A_channel_name = f'{name}_B2A'
        B2A_channel = self._prepare_channel(
            B2A_channel_name, length, refractive_index)
        
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
    

    def _prepare_channel(self, name, length, refractive_index):
        channel = ClassicalChannel(
            name=name,
            length=length,
            models={
                'delay_model': FibreDelayModel(c=299792/refractive_index)
            }
        )
        return channel
