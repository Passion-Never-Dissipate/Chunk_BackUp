import json
import math
from typing import Union

from mcdreforged.api.types import CommandSource
from mcdreforged.api.rtext import RTextBase
from chunk_backup.log.log_manager import LogManager
from chunk_backup.task.basic_task import ImmediateTask
from chunk_backup.utils.mcdr_utils import tr


class ListLogTask(ImmediateTask[None]):

    def __init__(self, source: CommandSource, context: dict):
        super().__init__(source)
        self.manager = LogManager()
        self.per_page = context.get("per_page", 10)
        self.page = context.get("page", 1)

    @property
    def id(self) -> str:
        return 'list_log'

    def reply(self, msg: Union[str, RTextBase], *, with_prefix: bool = False):
        super().reply(msg, with_prefix=with_prefix)

    def run(self):
        per_page = self.per_page
        page = self.page
        total_logs = self.manager.count_log_files()
        total_pages = math.ceil(total_logs / per_page)
        if page > total_pages:
            if not total_logs:
                self.reply(tr("other.ui.log_empty"), with_prefix=True)
                return
            self.reply(tr("other.ui.out_of_index"), with_prefix=True)
            return
        start = self.per_page * (self.page - 1) + 1
        end = min(total_logs, self.per_page * self.page)
        range_logs = self.manager.get_log_files(start, end)
        content = [self.get_json_obj("title")]
        if not range_logs:
            content.append(self.get_json_obj("other.ui.log_empty", without_id=True))
            self.reply(self.merge_rtext_lists(content))
            return
        base_cmd = f"{self.config.command.prefix} log show"
        for log in range_logs:
            log_file = self.manager.log_storage / log
            cmd = base_cmd + log
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)

                task = info["task"]
                success = info["task_done"]
                operator = info["operator"]
                date = info["date"]
                content.append(
                    self.get_json_obj(
                        "single_log", task=tr(f"task.{task}.name"), operator=operator, date=date,
                        success=tr(f"other.ui.{'success' if success else 'fail'}"), cmd=cmd
                    )
                )
                continue

            except Exception:
                continue

        if len(content) == 1:
            content.append(self.get_json_obj("other.ui.log_empty", without_id=True))
            self.reply(self.merge_rtext_lists(content))
            return

        page_components = []
        base_cmd = f"{self.config.command.prefix} log list"

        # 上一页
        if self.page > 1:
            prev_cmd = f"{base_cmd} {self.page - 1}"
            prev_text = self.get_json_obj(
                "other.ui.prev", without_id=True,
                current=self.page, prev=self.page - 1, cmd=prev_cmd
            )
            page_components.append(prev_text)

        # 下一页
        if self.page < total_pages:
            next_cmd = f"{base_cmd} {self.page + 1}"
            next_text = self.get_json_obj(
                "other.ui.next", without_id=True,
                current=self.page, next=self.page + 1, cmd=next_cmd
            )
            page_components.append(next_text)

        # 当前页码
        current_page = self.get_json_obj(
            "other.ui.current_page", without_id=True,
            current=self.page, total=total_pages
        )
        page_components.append(current_page)

        # 总槽数
        total_text = self.get_json_obj(
            "other.ui.totals", without_id=True,
            total=total_logs, type=tr("other.ui.logs").to_plain_text()
        )
        page_components.append(total_text)

        content.append(self.merge_rtext_lists(page_components, separator="  "))

        self.reply(self.merge_rtext_lists(content))
