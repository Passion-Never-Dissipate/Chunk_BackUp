import json

from typing import Union
from mcdreforged.api.types import CommandSource
from mcdreforged.api.rtext import RTextBase
from chunk_backup.task.basic_task import ImmediateTask
from chunk_backup.types.backup_info import BackupInfo
from chunk_backup.types.units import ByteCount
from chunk_backup.utils.backup_utils import BackupFolderManager as manager


class ShowBackupTask(ImmediateTask[None]):

    def __init__(self, source: CommandSource, context: dict):
        super().__init__(source)
        self.manager = manager(is_static=True if context.get("static_count") else False)
        self.overwrite = self.config.overwrite_storage
        self.raw_id = self.config.overwrite_storage if context.get("pre_backup", 0) > 0 else f'slot{context["backup_id"]}'
        self.integer_id = self.raw_id.replace("slot", "")
        self.pre_backup = context.get("pre_backup", 0) > 0
        self.show_uuid_list = context.get("data_count", 0) > 0
        self.page = context.get('page', 1)
        self.per_page = 10

    @property
    def id(self) -> str:
        return 'show_backup'

    def reply(self, msg: Union[str, RTextBase], *, with_prefix: bool = False):
        super().reply(msg, with_prefix=with_prefix)

    def _show_uuid_list(self, backup_info: BackupInfo):
        if not backup_info.uuid_dict:
            self.reply(self.tr("no_player_data", self.integer_id), with_prefix=True)
            return

        # 将字典转换为列表并排序（按玩家名）
        items = sorted(backup_info.uuid_dict.items())  # [(name, uuid), ...]
        total = len(items)
        total_pages = (total + self.per_page - 1) // self.per_page

        if self.page > total_pages:
            self.reply(self.get_json_obj("other.ui.out_of_index", without_id=True))
            return

        # 计算当前页的数据
        start = (self.page - 1) * self.per_page
        end = min(start + self.per_page, total)
        current_items = items[start:end]

        # 构建显示内容
        content = [self.get_json_obj("uuid_title")]

        for name, uuid in current_items:
            line = self.get_json_obj("common.single_uuid", name=name, uuid=uuid)
            content.append(line)

        # 翻页组件
        page_components = []
        suffix = (" -s" if self.manager.is_static else "")
        base_cmd = f"{self.config.command.prefix} show {self.integer_id}{suffix} -d -p".strip()

        # 上一页
        if self.page > 1:
            prev_page = self.page - 1
            prev_cmd = f"{base_cmd} {prev_page}"
            prev_text = self.get_json_obj(
                "other.ui.prev", without_id=True,
                current=self.page, prev=prev_page, cmd=prev_cmd
            )
            page_components.append(prev_text)

        # 下一页
        if self.page < total_pages:
            next_page = self.page + 1
            next_cmd = f"{base_cmd} {next_page}"
            next_text = self.get_json_obj(
                "other.ui.next", without_id=True,
                current=self.page, next=next_page, cmd=next_cmd
            )
            page_components.append(next_text)

        # 当前页码
        current_text = self.get_json_obj(
            "other.ui.current_page", without_id=True,
            current=self.page, total=total_pages
        )
        page_components.append(current_text)

        # 总数信息
        total_text = self.get_json_obj(
            "other.ui.totals", without_id=True,
            total=total, type=self.tr("show_uuid").to_plain_text()
        )
        page_components.append(total_text)

        # 如果有翻页组件，合并后添加到内容
        if page_components:
            content.append(self.merge_rtext_lists(page_components, separator="  "))

        self.reply(self.merge_rtext_lists(content))

    def run(self):
        self.manager.backup_slot = self.raw_id
        info = self.manager.storage_root / (self.overwrite if self.pre_backup else self.manager.region_storage / self.manager.backup_slot) / "info.json"
        try:
            with open(info, 'r', encoding='utf-8') as f:
                info = json.load(f)
                backup_info = BackupInfo.deserialize(info)

        except FileNotFoundError:
            self.reply(self.get_json_obj("other.ui.info_empty", without_id=True), with_prefix=True)
            return

        if self.show_uuid_list:
            self._show_uuid_list(backup_info)
            return

        content = [self.get_json_obj("title")]

        if backup_info.type in ["chunk", "region"]:
            keys = backup_info.get_type_key()
            for key in keys:
                try:
                    if key == "total_size":
                        value = ByteCount(info[key]).auto_format().to_str().replace("i", "")
                    elif key == "dimension":
                        value = ", ".join(info[key])
                    elif key == "uuid_dict":
                        suffix = (" -s" if self.manager.is_static else "")
                        cmd = f"{self.config.command.prefix} show {self.integer_id}{suffix} -d".strip()
                        value = self.tr("common.uuid_do_click", total=len(backup_info.uuid_dict), cmd=cmd).to_plain_text()
                    elif key in ["player_position", "top_left", "top_right", "bottom_left", "bottom_right"]:
                        if key == "player_position" and "player_position" not in info:
                            continue
                        value = ', '.join(f"{k}: {v}" for k, v in info[key].items())
                    else:
                        value = info.get(key)
                        if not value:
                            continue
                except Exception:
                    continue
                content.append(self.get_json_obj(f"common.{key}", value))

        else:
            self.reply(self.get_json_obj("other.ui.info_empty", without_id=True), with_prefix=True)
            return

        self.reply(
            self.merge_rtext_lists(content) if len(content) > 1 else self.get_json_obj("other.ui.info_empty", without_id=True),
            with_prefix=len(content) <= 1
        )