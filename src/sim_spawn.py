
import os
import logging
import netsquid as ns
from multiprocessing import Pool, Manager
from psutil import cpu_count
from itertools import repeat
from netsquid.qubits.qformalism import QFormalism
from simlog import log


def simulation(lock, loglevel=logging.CRITICAL, formalism=QFormalism.DM):
        with lock:
            if not os.path.exists('log'):
                os.makedirs('log')
        log.init(loglevel, log.TimeUnit.MICROSECONDS)
        ns.set_qstate_formalism(formalism)


class SimulationSpawner:
    def __init__(self, task, spare_cores=1):
        self.task = task
        self.spare_cores = spare_cores

    def run(self, *args):
        with Manager() as manager:
            lock = manager.Lock()
            zipargs = zip(repeat(lock), *args)
            with Pool(cpu_count()-self.spare_cores) as pool:
                pool.starmap(self.task, zipargs)

def valami(lock, a, v):
    with lock:
        with open('output.txt', 'a') as f:
            print(a, v, file=f)
