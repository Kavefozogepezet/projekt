
import datetime
import logging
import netsquid as ns
from enum import Enum

class log:
    class TimeUnit (Enum):
        SECONDS = ('s', ns.SECOND)
        MILLISECONDS = ('ms', ns.MILLISECOND)
        MICROSECONDS = ('us', ns.MICROSECOND)
        NANOSECONDS = ('ns', ns.NANOSECOND)

    _time_unit = TimeUnit.NANOSECONDS

    def __init__(self):
        raise NotImplementedError('This class is not meant to be instantiated.')
    
    @staticmethod
    def init(level, time_unit=TimeUnit.NANOSECONDS):
        current_datetime = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = logging.FileHandler(f"./log/sim_{current_datetime}.log")
        log_file.setLevel(level)
        log._time_unit = time_unit

        for handler in ns.logger.handlers:
            ns.logger.removeHandler(handler)
        ns.logger.setLevel(level)
        ns.logger.addHandler(log_file)
    
    @staticmethod
    def info(msg, **kwargs):
        the_msg = log._construct_message('INFO', msg, **kwargs)
        ns.logger.info(the_msg)

    @staticmethod
    def _construct_message(level, msg, **kwargs):
        if 'at' in kwargs:
            name = kwargs['at'].name
            name = f' @@ {name:16}: '
        elif 'into' in kwargs:
            name = kwargs['into'].name
            name = f' >> {name:16}: '
        elif 'outof' in kwargs:
            name = kwargs['outof'].name
            name = f' << {name:16}: '
        else:
            name = ' '
        
        unit = log._time_unit.value
        time = ns.sim_time() / unit[1]
        time_str = f'{time:8.2f} {unit[0]}'
        return f'[{level:5} @ {time_str}]{name}{msg}'
