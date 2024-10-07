
import datetime
import logging
import netsquid as ns
from enum import Enum


class log:
    class Layer (Enum):
        NONE = 'x'
        PHYSICAL = 'P'
        LINK = 'L'
        NETWORK = 'N'
        TRANSPORT = 'T'
        APP = 'A'

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
        unit = time_unit.value[0]

        ns.logger.critical(
f'''+--------------------------------------------------------------------------------------------+
| Format:                                                                                    |
| [level][layer] [time] [action] [name]: [message]                                           |
| - level: x (not set), D (debug), I (info), W (warning), E (error), C (critical)            |
| - layer: x (not set), P (physical), L (link), N (network), T (transport), A |(application) |
| - time: elapsed time in simulation in {unit:2}                                                   |
| - action: @ (at the node), > (into the node), < (out of the node)                          |
| - name: name of the reporting object                                                       |
| - message: the logged message                                                              |
+--------------------------------------------------------------------------------------------+'''
        )

    @staticmethod
    def debug(msg, **kwargs):
        if ns.logger.level > logging.DEBUG:
            the_msg = log._construct_message('D', msg, **kwargs)
            ns.logger.debug(the_msg)
    
    @staticmethod
    def info(msg, **kwargs):
        if ns.logger.level > logging.DEBUG:
            the_msg = log._construct_message('I', msg, **kwargs)
            ns.logger.info(the_msg)

    @staticmethod
    def warning(msg, **kwargs):
        if ns.logger.level > logging.DEBUG:        
            the_msg = log._construct_message('W', msg, **kwargs)
            ns.logger.warning(the_msg)

    @staticmethod
    def error(msg, **kwargs):    
        if ns.logger.level > logging.DEBUG:
            the_msg = log._construct_message('E', msg, **kwargs)
            ns.logger.error(the_msg)

    @staticmethod
    def critical(msg, **kwargs):
        if ns.logger.level > logging.DEBUG:
            the_msg = log._construct_message('C', msg, **kwargs)
            ns.logger.critical(the_msg)

    @staticmethod
    def _log_time():
        unit = log._time_unit.value
        time = ns.sim_time() / unit[1]
        time_str = f'{time:03.0f}{unit[0]}'
        ns.logger.debug(f'[{time_str}]', end=' ')

    @staticmethod
    def msg2str(msg) -> str:
        label = msg[0]

        if len(msg) > 1:
            data_str = '{' + ', '.join([
                f'{key}: {value}'
                for key, value in msg[1].items()
            ]) + '}'
        else:
            data_str = ''

        return f'{label}{data_str}'
    
    @staticmethod
    def _construct_message(level, msg, **kwargs):
        if 'at' in kwargs:
            obj = kwargs['at']
            action = '@'
        elif 'into' in kwargs:
            obj = kwargs['into']
            action = '>'
        elif 'outof' in kwargs:
            obj = kwargs['outof']
            action = '<'
        else:
            obj = None

        layer = log.Layer.NONE.value
        prefix = '-' * 12
        if obj:
            name = obj.name[:10]
            prefix = f'{action} {name:10}'
            if hasattr(obj, 'log_layer'):
                layer = obj.log_layer.value
        
        unit = log._time_unit.value
        time = ns.sim_time() / unit[1]
        return f'{level}{layer} {time:5.0f} {prefix}: {msg}'
