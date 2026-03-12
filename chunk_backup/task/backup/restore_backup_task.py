import json
import traceback
import candy_tools as ct

from collections import defaultdict
from typing import Union
from mcdreforged.api.types import CommandSource
from mcdreforged.api.rtext import RTextBase
from chunk_backup.task.basic_task import HeavyTask
from chunk_backup.exceptions import FatalError
from chunk_backup.types.operator import Operator
from chunk_backup.action.restore_backup_action import RestoreBackupAction
from chunk_backup.types.backup_info import BackupInfo
from chunk_backup.utils.backup_utils import PlayerDataFolderManager as data_manager, BackupFolderManager as Manager, DimensionChecker
from chunk_backup.utils.mcdr_utils import tr
from chunk_backup.log.log_manager import LogTask
from chunk_backup.log.log_manager import LogManager
from chunk_backup.utils.region.chunk_selector import ChunkSelector


class RestoreBackupTask(HeavyTask[None]):
    def __init__(self, source: CommandSource, context: dict):
        super().__init__(source)
        self.manager = Manager(is_static=True if context.get("static_count") else False)
        self.operator = Operator.of(source)
        self.ctx = context
        self.overwrite = self.config.overwrite_storage
        self.raw_id = f'slot{context["backup_id"]}' if context.get("backup_id") else None
        self.integer_id = self.raw_id.replace("slot", "") if self.raw_id else None
        self.with_data = context.get("data_count", 0) > 0
        self.pre_restore = context.get("pre_restore", 0) > 0
        self.need_confirm = context.get("confirm_count", 0) == 0
        self.__can_abort = False

    @property
    def id(self) -> str:
        return 'restore_backup'

    def is_abort_able(self) -> bool:
        return super().is_abort_able() or self.__can_abort

    def reply(self, msg: Union[str, RTextBase], *, with_prefix: bool = False):
        super().reply(msg, with_prefix=with_prefix)

    def __countdown_and_stop_server(self) -> bool:
        for countdown in range(max(0, self.config.command.restore_countdown_sec), 0, -1):
            self.broadcast(self.get_json_obj("countdown", sec=countdown, prefix=self.config.command.prefix, slot=self.manager.backup_slot.replace("slot", "")))

            if self.aborted_event.wait(1):
                self.broadcast(self.get_aborted_text())
                return False

        self.server.stop()
        self.logger.info('Wait for server to stop')
        self.server.wait_until_stop()
        return True

    def run(self):
        manager = self.manager
        if not self.raw_id and not self.pre_restore:
            manager.backup_slot = manager.get_min_slot_name()
            self.raw_id = f"slot{manager.backup_slot}"
            self.integer_id = self.raw_id.replace("slot", "")
        else:
            manager.backup_slot = self.overwrite if self.pre_restore else self.raw_id
            self.raw_id = manager.backup_slot
            self.integer_id = self.raw_id.replace("slot", "")

        backup_storage = manager.storage_root / (self.overwrite if self.pre_restore else manager.region_storage / manager.backup_slot)

        info_file = backup_storage / "info.json"
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                info = json.load(f)
                backup_info = BackupInfo.deserialize(info)

        except FileNotFoundError:
            self.reply(self.get_json_obj("other.ui.info_empty", without_id=True), with_prefix=True)
            return

        if not DimensionChecker.create(self.source, self.config.backup.dimension): return

        for dimension in backup_info.dimension:
            if dimension not in self.config.backup.dimension:
                self.reply(self.get_json_obj("task.backup_create.lack_dimension", dimension=dimension, without_id=True), with_prefix=True)
                return

        if backup_info.type == "chunk":
            if hasattr(backup_info, "player_position"):
                backup_info.player_position = None
            backup_info.selector = defaultdict(list)
            top_left = (backup_info.top_left["x"], backup_info.top_left["z"])
            bottom_right = (backup_info.bottom_right["x"], backup_info.bottom_right["z"])
            selector = ChunkSelector.from_chunk_coords(top_left, bottom_right, ignore_size_limit=True)
            for dim in backup_info.dimension:
                backup_info.selector[dim].append(selector)

        elif backup_info.type == "region":
            backup_info.selector = defaultdict(list)
            for dim in backup_info.dimension:
                backup_info.selector[dim].append("all")

        elif backup_info.type == "custom":
            ids = self.ctx.get("sub_slot")
            if ids:
                # 过滤子备份
                sub_backup = backup_info.sub_backup
                slot_to_key = {v.slot: k for k, v in sub_backup.items()}
                new_sub_slot = {}
                for _id in ids:
                    if isinstance(_id, int):
                        key = slot_to_key.get(_id)
                        if key:
                            new_sub_slot[key] = sub_backup[key]
                    elif isinstance(_id, str) and _id in sub_backup:
                        new_sub_slot[_id] = sub_backup[_id]
                backup_info.sub_backup = new_sub_slot

            # 构建选择器并收集所有维度
            backup_info.selector = defaultdict(list)
            all_dimensions = []
            for sub in backup_info.sub_backup.values():
                all_dimensions.extend(sub.dimension)
                for dim in sub.dimension:
                    if sub.type == "region":
                        if backup_info.selector[dim]:
                            backup_info.selector[dim] = ["all"]
                            continue
                        backup_info.selector[dim].append("all")
                    elif sub.type == "chunk":
                        if "all" in backup_info.selector[dim]:
                            continue
                        if hasattr(sub, "player_position"):
                            sub.player_position = None
                        top_left = (sub.top_left["x"], sub.top_left["z"])
                        bottom_right = (sub.bottom_right["x"], sub.bottom_right["z"])
                        selector = ChunkSelector.from_chunk_coords(top_left, bottom_right, ignore_size_limit=True)
                        backup_info.selector[dim].append(selector)

            backup_info.dimension = list(set(all_dimensions))

        self.__can_abort = True
        self.broadcast(
            self.tr(
                "title", slot=manager.backup_slot.replace("slot", ""), date=backup_info.date,
                name=tr("other.ui.custom").to_plain_text() if backup_info.type == "custom" else tr("other.ui.comment").to_plain_text(),
                comment=backup_info.comment
            )
        )

        if self.need_confirm:
            if not self.wait_confirm(self.tr('name').to_plain_text()):
                return

        if ct.query_carpet():
            region_dict = ChunkSelector.to_block_rectangles_dict(backup_info.selector)
            origion_dimension = list(backup_info.selector.keys())
            player_data = ct.get_players_data_in_regions(region_dict, origion_dimension)
            if not player_data:
                if player_data is None:
                    self.broadcast(self.get_json_obj("task.create_backup.no_carpet", self.tr("pre_backup.name").to_plain_text(), without_id=True))
                else:
                    self.broadcast(self.get_json_obj("task.create_backup.no_player", self.tr("pre_backup.name").to_plain_text(), without_id=True))
            else:
                backup_info.player_data = player_data
                self.broadcast(self.get_json_obj(
                    "task.create_backup.player_data_completed", total=len(backup_info.player_data),
                    type=self.tr("pre_backup.name").to_plain_text(), without_id=True
                )
            )
        else:
            self.broadcast(self.get_json_obj("task.create_backup.no_carpet", self.tr("pre_backup.name").to_plain_text(), without_id=True))

        if not self.__countdown_and_stop_server():
            return

        self.__can_abort = False

        log_task = LogTask()
        log_task.task = self.id
        log_task.command = self.source.get_info().content
        if manager.backup_slot != self.overwrite:
            log_task.pre_backup_done = False
            log_task.pre_restore_done = None
        log_task.operator = self.operator.name if self.operator.is_player() else tr("other.operator.console").to_plain_text()

        with LogManager().task_logger(log_task):
            action = RestoreBackupAction(manager, backup_info)
            try:
                action.run()
                if hasattr(log_task, "pre_backup_done"):
                    log_task.pre_backup_done = True

                if self.with_data and backup_info.uuid_dict:
                    try:
                        _data = data_manager(list(backup_info.uuid_dict.values()), is_static=self.manager.is_static)
                        _data.backup_slot = manager.backup_slot
                        _data.restore_player_data(is_overwrite=True if manager.backup_slot == self.overwrite else False)
                    except Exception:
                        self.broadcast(tr("task.restore_backup.restore_player_data_error", error=traceback.format_exc()))

                self.server.start()
                return
            except FatalError as fatal:
                if fatal.pre_backup:
                    self.logger.info(tr("other.error.chunk.restore_backup.pre_backup_error").to_plain_text())
                    if fatal.causes:
                        fatal.on_done = True
                    raise  # 原样抛出，让上层处理

                if fatal.restore and manager.backup_slot != self.overwrite:
                    log_task.pre_backup_done = True
                    try:
                        log_task.pre_restore_done = False
                        self.logger.info(tr("other.error.chunk.restore_backup.pre_restore_ready").to_plain_text())
                        with open(backup_info.backup_path, 'r', encoding='utf-8') as f:
                            pre_backup = json.load(f).get("date")
                        if backup_info.date == pre_backup:
                            manager.backup_slot = self.overwrite
                            restore_action = RestoreBackupAction(manager, backup_info)
                            restore_action.run()

                            if self.with_data and backup_info.player_data:
                                try:
                                    uuid_dict = {}
                                    for k, v in backup_info.player_data.items():
                                        uuid_dict[k] = v["uuid"]
                                    _data = data_manager(list(uuid_dict.values()), is_static=self.manager.is_static)
                                    _data.restore_player_data(is_overwrite=True if manager.backup_slot == self.overwrite else False)
                                except Exception:
                                    self.broadcast(tr("task.restore_backup.restore_player_data_error", error=traceback.format_exc()))

                            log_task.pre_restore_done = True
                            # 恢复成功后启动服务器
                            self.logger.info(tr("task.restore_backup.pre_restore_done").to_plain_text())
                            self.server.start()
                            return
                        else:
                            log_task.pre_backup_done = False
                            self.logger.info(tr("other.error.chunk.restore_backup.date_mismatch").to_plain_text())
                            # 日期不匹配，重新抛出 fatal，并标记 mismatch
                            fatal.mismatch = True
                            raise
                    except Exception as restore_err:
                        # 如果已经是 FatalError 且 mismatch 为 True，直接抛出（即日期不匹配情况）
                        if isinstance(restore_err, FatalError) and restore_err.mismatch:
                            raise
                        self.logger.info(tr("other.error.chunk.restore_backup.pre_restore_error").to_plain_text())
                        # 使用 causes 列表保存所有相关异常
                        raise FatalError(
                            pre_restore=True,
                            need_start=True,
                            on_done=True,
                            causes=[fatal, restore_err]
                        ) from restore_err  # 设置 restore_err 为直接原因（可选）
                else:
                    # 不符合恢复条件，重新抛出原始异常
                    self.logger.info(tr("other.error.chunk.restore_backup.pre_restore_error").to_plain_text())
                    if fatal.causes:
                        fatal.on_done = True
                    raise  # 原样抛出，让上层处理
            except Exception as e:
                # 其他未知异常，包装为 FatalError
                raise FatalError(on_done=True, need_start=True, causes=[e]) from e
