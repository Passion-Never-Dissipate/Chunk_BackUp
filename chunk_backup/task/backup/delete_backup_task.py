import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from mcdreforged.api.types import InfoCommandSource
from chunk_backup.utils.backup_utils import BackupFolderManager as Manager
from chunk_backup.task.basic_task import HeavyTask
from chunk_backup.utils.mcdr_utils import tr
from chunk_backup.log.log_manager import LogTask
from chunk_backup.log.log_manager import LogManager
from chunk_backup.types.operator import Operator


class DeleteBackupTask(HeavyTask[None]):
    def __init__(self, source: InfoCommandSource, context: dict, manager: Manager, operator: Optional[Operator] = None):
        super().__init__(source)
        self.manager = manager
        if operator is None:
            operator = Operator.of(source)
        self.operator = operator
        self.slots = context.get("slot_range")

    @property
    def id(self) -> str:
        return 'delete_backup'

    def is_abort_able(self) -> bool:
        return True

    def run(self):
        if not self.wait_confirm(self.tr('name').to_plain_text()):
            return

        region_storage = self.manager.storage_root / self.manager.region_storage

        try:
            max_workers = self.config.max_workers if self.config.max_workers > 0 else 4
        except Exception:
            max_workers = 4

        log_task = LogTask()
        log_task.task = self.id
        log_task.command = self.source.get_info().content
        log_task.operator = self.operator.name if self.operator.is_player() else tr("other.operator.console").to_plain_text()

        with LogManager().task_logger(log_task):
            future_to_path = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for slot in self.slots:
                    path = region_storage / f"slot{slot}"
                    future = executor.submit(shutil.rmtree, path)
                    future_to_path[future] = path

                for future in as_completed(future_to_path):
                    future.result()  # 触发异常（如果有）

        self.reply_tr("completed", amount=len(self.slots))
