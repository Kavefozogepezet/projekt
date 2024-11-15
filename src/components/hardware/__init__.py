from .quantum_fibre import *
from .classical_fibre import *
from .nvcprocessor import *

SPEED_OF_LIGHT = 299792  # km/s
C = SPEED_OF_LIGHT

__all__ = [
    'SPEED_OF_LIGHT',
    'C',

    'QuantumFibre',
    'ClassicalFibre',
    'NVCProcessor',
    'program_function',
    'ProgramPriority'
]