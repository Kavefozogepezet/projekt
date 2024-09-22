from .quantum_fibre import QuantumFibre
from .classical_fibre import ClassicalFibre

SPEED_OF_LIGHT = 299792  # km/s
C = SPEED_OF_LIGHT

__all__ = [
    'SPEED_OF_LIGHT',
    'C',

    'QuantumFibre',
    'ClassicalFibre'
]