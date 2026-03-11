import logging
import threading
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

_T = TypeVar('_T')


class Action(Generic[_T], ABC):
    def __init__(self):
        self.is_interrupted = threading.Event()

        from chunk_backup.mcdr_globals import server
        from chunk_backup.config.config import Config
        self.logger: logging.Logger = server.logger
        self.config: Config = Config.get()

    @abstractmethod
    def run(self) -> _T:
        ...

    def is_interruptable(self) -> bool:
        return False

    def interrupt(self):
        self.is_interrupted.set()
