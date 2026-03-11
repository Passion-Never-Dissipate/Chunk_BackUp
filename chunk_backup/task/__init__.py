import enum
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Union

from mcdreforged.api.all import CommandSource, InfoCommandSource, RTextBase, RColor
from chunk_backup.utils import mcdr_utils

_T = TypeVar('_T')


class TaskEvent(enum.Enum):
    plugin_unload = enum.auto()
    world_save_done = enum.auto()
    server_stopped = enum.auto()
    operation_confirmed = enum.auto()
    operation_aborted = enum.auto()


class Task(Generic[_T], mcdr_utils.TranslationContext, ABC):
    def __init__(self, source: Union[CommandSource, InfoCommandSource]):
        super().__init__(f'task.{self.id}')
        from chunk_backup import mcdr_globals
        self.source = source
        self.server = mcdr_globals.server

    def get_name_text(self) -> RTextBase:
        return self.tr('name').set_color(RColor.aqua)

    def is_abort_able(self) -> bool:
        return False

    @property
    @abstractmethod
    def id(self) -> str:
        ...

    @abstractmethod
    def run(self) -> _T:
        ...

    @abstractmethod
    def get_abort_permission(self) -> int:
        ...

    def on_event(self, event: TaskEvent):
        pass
