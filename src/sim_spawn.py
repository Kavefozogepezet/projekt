
from abc import abstractmethod
from multiprocessing import Pool, Lock, Manager
from filelock import FileLock
from functools import partial
from psutil import cpu_count
from itertools import repeat

class SimulationSpawner:
    def __init__(self, task):
        self.task = task

    def run(self, *args):
        with Manager() as manager:
            lock = manager.Lock()
            zipargs = zip(repeat(lock), *args)
            with Pool(cpu_count()-1) as pool:
                pool.starmap(self.task, zipargs)

def valami(lock, a, v):
    with lock:
        with open('output.txt', 'a') as f:
            print(a, v, file=f)
