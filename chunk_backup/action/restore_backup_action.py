import datetime
import shutil
import traceback

from chunk_backup.action import Action
from chunk_backup.action.create_backup_action import CreateBackupAction
from chunk_backup.exceptions import FatalError
from chunk_backup.mcdr_globals import server
from chunk_backup.types.backup_info import BackupInfo
from chunk_backup.utils.backup_utils import PlayerDataFolderManager as data_manager, BackupFolderManager
from chunk_backup.utils.mcdr_utils import tr, broadcast_message as broadcast
from chunk_backup.utils.region.region import Region
from chunk_backup.utils.timer import Timer


class RestoreBackupAction(Action):

    def __init__(self, manager: BackupFolderManager, backup_info: BackupInfo):
        super().__init__()
        self.manager = manager
        self.backup_info = backup_info

    # -------------------------------------------------

    def run(self):

        manager = self.manager
        backup_info = self.backup_info
        timer = Timer()

        need_overwrite = manager.backup_slot != self.config.overwrite_storage

        # -------------------------------------------------
        # 回档前自动备份
        # -------------------------------------------------

        if need_overwrite:

            self.logger.info("Creating backup of existing regions before restore")

            try:

                action = CreateBackupAction(
                    backup_info,
                    manager=manager,
                    is_overwrite=True
                )

                action.run()
                if backup_info.player_data:
                    try:
                        uuid_dict = {}
                        for k, v in backup_info.player_data.items():
                            uuid_dict[k] = v["uuid"]
                        _data = data_manager(list(uuid_dict.values()), is_static=self.manager.is_static)
                        _data.backup_player_data(is_overwrite=True)
                    except Exception:
                        shutil.rmtree(_data.storage_root / self.config.overwrite_storage / "players", ignore_errors=True)
                        broadcast(tr("task.backup_create.backup_player_data_error", error=traceback.format_exc()))
                        backup_info.player_data = None

                # 更新 overwrite info
                backup_info.date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                backup_info.comment = tr(
                    "other.ui.overwrite_comment"
                ).to_plain_text()

                backup_info.version_created = str(
                    server.get_self_metadata().version
                )

                backup_info.minecraft_version = (
                    server.get_server_information().version
                )

                backup_info.operator = tr(
                    "other.operator.plugin"
                ).to_plain_text()

                # 保存 overwrite info
                backup_info.save_json(
                    pre_backup=True,
                    is_overwrite=True
                )

                cost_backup = timer.get_and_restart()

            except FatalError as e:

                e.pre_backup = True
                e.need_start = True
                raise

            except Exception as e:

                raise FatalError(
                    pre_backup=True,
                    need_start=True,
                    causes=[e]
                ) from e

        # -------------------------------------------------
        # 开始回档
        # -------------------------------------------------

        self.logger.info(
            f"Restoring to backup {manager.backup_slot}"
        )

        try:

            Region.restore_regions(manager, backup_info)

        except FatalError as e:

            e.need_start = True
            raise

        except Exception as e:

            raise FatalError(
                restore=True,
                need_start=True,
                causes=[e]
            ) from e

        cost_restore = timer.get_and_restart()

        # -------------------------------------------------
        # 日志
        # -------------------------------------------------

        if need_overwrite:

            total_time = cost_backup + cost_restore

        else:

            total_time = cost_restore

        log_msg = (
            f"Restore to backup {manager.backup_slot} done, "
            f"cost {round(total_time, 2)}s"
        )

        if need_overwrite:

            log_msg += (
                f", backup {round(cost_backup, 2)}s"
                f", restore {round(cost_restore, 2)}s"
            )

        log_msg += ", starting the server"

        self.logger.info(log_msg)
