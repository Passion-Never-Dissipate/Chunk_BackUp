from typing import Optional
from chunk_backup.action import Action
from chunk_backup.types.backup_info import BackupInfo
from chunk_backup.exceptions import StaticMore, DynamicMore
from chunk_backup.utils.backup_utils import BackupFolderManager as Manager
from chunk_backup.utils.region.region import Region
from chunk_backup.utils.mcdr_utils import broadcast_message as broadcast


class CreateBackupAction(Action):
    def __init__(self, backup_info: BackupInfo, manager: Optional[Manager] = None, is_overwrite=False):
        super().__init__()
        self.backup_info = backup_info
        self.manager = manager
        self.is_overwrite = is_overwrite

    def run(self):
        backup_info = self.backup_info
        if not self.manager:
            manager = Manager(is_static=getattr(backup_info, "is_static", False))
        else:
            manager = self.manager

        try:
            manager.organize_region_folder(is_overwrite=self.is_overwrite)

        except (StaticMore, DynamicMore) as e:
            broadcast(e.msg)
            return

        try:

            Region.export_regions(manager, backup_info, is_overwrite=self.is_overwrite)

        except Exception:
            manager.remove_slot()
            raise
