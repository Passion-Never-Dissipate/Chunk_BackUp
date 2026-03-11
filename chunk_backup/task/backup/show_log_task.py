import json
from typing import Union

from mcdreforged.api.types import CommandSource
from mcdreforged.api.rtext import RTextBase

from chunk_backup.log.log_manager import LogManager
from chunk_backup.utils.mcdr_utils import tr
from chunk_backup.task.basic_task import ImmediateTask


class ShowLogTask(ImmediateTask[None]):

    def __init__(self, source: CommandSource, context: dict):
        super().__init__(source)
        self.manager = LogManager()
        self.name = context.get("name", self.manager.get_latest_log().name)

    @property
    def id(self) -> str:
        return 'show_log'

    def reply(self, msg: Union[str, RTextBase], *, with_prefix: bool = False):
        super().reply(msg, with_prefix=with_prefix)

    def run(self):
        count = self.manager.count_log_files()
        if not count:
            self.reply(tr("other.ui.log_empty"), with_prefix=True)
            return

        if not self.manager.is_valid_log_file(self.name):
            self.reply_tr("no_log", with_prefix=True)
            return

        content = [self.get_json_obj("title")]

        try:
            with open(self.manager.log_storage / self.name, 'r', encoding='utf-8') as f:
                info = json.load(f)

            for key, value in info.items():
                if key == "task":
                    value = tr(f"task.{value}.name").to_plain_text()

                if key in ["pre_backup_done", "pre_restore_done", "task_done"]:
                    if value:
                        value = tr(f"other.ui.success").to_plain_text()
                    else:
                        value = tr(f"other.ui.fail").to_plain_text()

                content.append(self.get_json_obj(f"{key}", value))

        except Exception:
            self.reply_tr("no_log", with_prefix=True)
            return

        self.reply(self.merge_rtext_lists(content))
