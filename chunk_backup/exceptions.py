from chunk_backup.utils.mcdr_utils import tr


class ChunkBackupError(Exception):
    pass


class MaxChunkLength(ChunkBackupError):
    def __init__(self, max_chunk_size: int, width: int, height: int):
        super().__init__()
        self.max_chunk_size = max_chunk_size
        self.width = width
        self.height = height


class MaxChunkRadius(ChunkBackupError):
    def __init__(self, radius: int, current_size: int, max_chunk_size: int):
        super().__init__()
        self.radius = radius
        self.current_size = current_size
        self.max_chunk_size = max_chunk_size


class StaticMore(ChunkBackupError):
    def __init__(self, max_slot: int):
        super().__init__()
        self.msg = tr("task.create_backup.static_more", max_slot=max_slot)


class DynamicMore(ChunkBackupError):
    def __init__(self, max_slot: int, current_slot: int):
        super().__init__()
        self.msg = tr("task.create_backup.dynamic_more", max_slot=max_slot, current_slot=current_slot)


class FatalError(ChunkBackupError):
    def __init__(self, on_done=False, need_start=False, pre_backup=False, restore=False, pre_restore=False, mismatch=False, causes=None):
        super().__init__("Fatal error")
        self.backup = not restore
        self.on_done = on_done
        self.need_start = need_start
        self.pre_backup = pre_backup
        self.restore = restore
        self.pre_restore = pre_restore
        self.mismatch = mismatch
        self.causes = causes or []
