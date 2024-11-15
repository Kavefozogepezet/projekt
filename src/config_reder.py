
import yaml
import re
import io
from netsquid.util.simtools import \
    MICROSECOND, MILLISECOND, SECOND, NANOSECOND


class ConfigHolder:
    def __init__(self, _level=0, **kwargs):
        self._level = _level
        for key, value in kwargs.items():
            if isinstance(value, dict):
                setattr(self, key, ConfigHolder(_level+1, **value))
            else:
                setattr(self, key, value)

    def __str__(self):
        with io.StringIO() as strio:
            for key, value in self.__dict__.items():
                if key == '_level':
                    continue
                if isinstance(value, ConfigHolder):
                    print(f"{'  '*self._level}{key}:", file=strio)
                    print(value, file=strio, end='')
                else:
                    print(f"{'  '*self._level}{key}: {value}", file=strio)
            return strio.getvalue()


def _translate_time(value, prefix):
    if prefix == '':
        mul = SECOND
    elif prefix == 'm':
        mul = MILLISECOND
    elif prefix == 'u':
        mul = MICROSECOND
    elif prefix == 'n':
        mul = NANOSECOND
    return value * mul


def _transalte_unit(value, unit):
    value = float(value)
    if unit[-1] == 's':
        return _translate_time(value, unit[:-1])


def _transalte_units(config):
    for key, value in config.items():
        if isinstance(value, dict):
            _transalte_units(value)
        else:
            if isinstance(value, str):
                matched = re.match(r"(\d+\.?\d*)(\D+)", value)
                config[key] = _transalte_unit(
                    matched.group(1),
                    matched.group(2)
                )


def read_config(file_name):
    with open(f'{file_name}.yaml', 'r') as file:
        config = yaml.safe_load(file)
    _transalte_units(config)
    return ConfigHolder(**config)


if __name__ == '__main__':
    config = read_config('netconf/simvalues')
    print(config)
