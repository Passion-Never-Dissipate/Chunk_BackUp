import json
import math

from typing import Union
from mcdreforged.api.types import CommandSource
from mcdreforged.api.rtext import RTextBase
from chunk_backup.task.basic_task import ImmediateTask
from chunk_backup.log.log_manager import LogManager
from chunk_backup.types.backup_info import BackupInfo
from chunk_backup.types.units import ByteCount
from chunk_backup.utils.backup_utils import BackupFolderManager as manager
from chunk_backup.utils.mcdr_utils import tr


class ListBackupTask(ImmediateTask[None]):

    def __init__(self, source: CommandSource, context: dict):
        super().__init__(source)
        self.manager = manager(is_static=True if context.get("static_count") else False)
        self.page = context.get("page", 1)
        self.per_page = context.get("per_page", 10)
        self.hide_ui = context.get("hide_count")

    @property
    def id(self) -> str:
        return 'list_backup'

    def reply(self, msg: Union[str, RTextBase], *, with_prefix: bool = False):
        super().reply(msg, with_prefix=with_prefix)

    def run(self):
        total_slots = self.manager.count_slots()
        total_pages = math.ceil(total_slots / self.per_page)
        if self.page > total_pages:
            if self.hide_ui:
                return
            if not total_pages:
                self.reply(self.get_json_obj("other.ui.list_empty", without_id=True), with_prefix=True)
                return
            self.reply(tr("other.ui.out_of_index"), with_prefix=True)
            return
        start = self.per_page * (self.page - 1) + 1
        end = min(total_slots, self.per_page * self.page)
        range_slots = self.manager.get_slot_range(start, end)
        content = [self.get_json_obj("title_st" if self.manager.is_static else "title_dy")]

        if not range_slots:
            content.append(self.get_json_obj("other.ui.list_empty", without_id=True))
            self.reply(self.merge_rtext_lists(content))
            return

        for slot in range_slots:
            info_file = slot / "info.json"
            if not info_file.exists():
                slot_display = self.get_json_obj("other.ui.slot_display", slot=slot.name.replace("slot", ""), without_id=True)
                info_empty = self.get_json_obj("other.ui.info_empty", without_id=True)
                content.append(self.merge_rtext_lists(slot_display, info_empty, separator=" "))
                continue

            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    backup_info: BackupInfo = BackupInfo.deserialize(json.load(f))

                dimension = ", ".join(backup_info.dimension)
                operator = backup_info.operator
                command = backup_info.command
                slot_integer = slot.name.replace("slot", "")
                prefix = self.config.command.prefix
                is_static = " -s" if self.manager.is_static else ""
                size = ByteCount(backup_info.total_size).auto_format().to_str().replace("i", "")
                date = backup_info.date
                name = tr("other.ui.custom").to_plain_text() if backup_info.type == "custom" else tr("other.ui.comment").to_plain_text()
                comment = backup_info.comment

                cmd_show = f"{prefix} show {slot_integer}{is_static}"
                cmd_back = f"{prefix} back {slot_integer}{is_static}"
                cmd_del = f"{prefix} del {slot_integer}{is_static}"

                content.append(
                    self.get_json_obj(
                        "single_slot", dimension=dimension, operator=operator, command=command,
                        size=size, date=date, name=name, comment=comment, slot=slot_integer,
                        cmd_show=cmd_show, cmd_back=cmd_back, cmd_del=cmd_del
                    )
                )
            except Exception:
                slot_display = self.get_json_obj("other.ui.slot_display", slot=slot.name.replace("slot", ""), without_id=True)
                info_empty = self.get_json_obj("other.ui.info_empty", without_id=True)
                content.append(self.merge_rtext_lists(slot_display, info_empty, separator=" "))

        if not self.hide_ui:
            page_components = []
            suffix = " -s" if self.manager.is_static else ""
            base_cmd = f"{self.config.command.prefix} list{suffix}".strip()

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
                total=total_slots, type=tr("other.ui.backup").to_plain_text()
            )
            page_components.append(total_text)

            content.append(self.merge_rtext_lists(page_components, separator="  "))

        if self.hide_ui:
            log_manager = LogManager()
            if log := log_manager.get_latest_log_by_task("restore_backup"):
                try:
                    with open(log, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    cmd = f"{self.config.command.prefix} log show {log.name}"
                    content.append(
                        self.get_json_obj(
                            "other.ui.latest_restore", without_id=True, cmd=cmd,
                            success=tr(f"other.ui.{'success' if data['task_done'] else 'fail'}"),
                            date=data["date"], operator=data["operator"]
                        )
                    )
                except Exception:
                    pass

        self.reply(self.merge_rtext_lists(content))
