import enum
from typing import Union, Optional
from mcdreforged.api.types import CommandSource
from mcdreforged.api.rtext import RTextBase
from chunk_backup.utils.mcdr_utils import get_json_obj
from chunk_backup.config.config import Config
from chunk_backup.task import TaskEvent
from chunk_backup.types.units import Duration
from chunk_backup.utils.mcdr_utils import broadcast_message as broadcast
from chunk_backup.utils.waitable_value import WaitableValue


class ConfirmResult(enum.Enum):
    confirmed = enum.auto()
    cancelled = enum.auto()

    def is_confirmed(self):
        return self == ConfirmResult.confirmed

    def is_cancelled(self):
        return self == ConfirmResult.cancelled


class ConfirmHelper:
    def __init__(self, source: CommandSource):
        self.source = source
        self.__confirm_result: WaitableValue[ConfirmResult] = WaitableValue()

    def wait_confirm(self, confirm_target_text: Optional[Union[RTextBase, str]], time_wait: Duration) -> WaitableValue[ConfirmResult]:
        text = get_json_obj("other.ui.confirm_click", prefix=Config.get().command.prefix, name=confirm_target_text)
        broadcast(text)
        self.__confirm_result.clear()
        self.__confirm_result.wait(time_wait.value)
        return self.__confirm_result

    def on_event(self, event: TaskEvent):
        if event in [TaskEvent.plugin_unload, TaskEvent.operation_aborted]:
            self.__confirm_result.set(ConfirmResult.cancelled)
        elif event == TaskEvent.operation_confirmed:
            self.__confirm_result.set(ConfirmResult.confirmed)
