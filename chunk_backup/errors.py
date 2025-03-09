from chunk_backup.tools import tr


class ChunkBackUpError(Exception):
    pass


class Timeout(ChunkBackUpError):
    """超时异常"""
    pass


class SavaoffTimeout(Timeout):
    pass


class SaveallTimeout(Timeout):
    pass


class GetPlayerDataTimeout(Timeout):
    pass


class BackupError(ChunkBackUpError):
    """备份操作基类异常"""
    pass


class BackError(ChunkBackUpError):
    """回档操作基类异常"""
    pass


class InvalidInput(BackupError):
    def __init__(self):
        super().__init__(tr("prompt_msg.invalid_input"))


class UnidentifiedDimension(BackupError):
    def __init__(self, *arg):
        super().__init__(tr("prompt_msg.unidentified_dimension", *arg))


class NoPlayer(BackupError):
    def __init__(self):
        super().__init__(tr("prompt_msg.backup.no_player"))


class MaxChunkLength(BackupError):
    def __init__(self, *args):
        super().__init__(tr("prompt_msg.backup.max_chunk_length", *args))


class MaxChunkRadius(BackupError):
    def __init__(self, *args):
        super().__init__(tr("prompt_msg.backup.max_chunk_radius", *args))


class InputDimRepeat(BackupError):
    def __init__(self):
        super().__init__(tr("prompt_msg.backup.input_dim_repeat"))


class InputDimError(BackupError):
    def __init__(self):
        super().__init__(tr("prompt_msg.backup.input_dim_error"))


class NoNumberKey(BackupError):
    def __init__(self):
        super().__init__(tr("prompt_msg.backup.no_number_key"))


class BackupTimeout(BackupError):
    def __init__(self, *args):
        super().__init__(tr("prompt_msg.backup.timeout", *args))


class DynamicMore(BackupError):
    def __init__(self, *args):
        super().__init__(tr("prompt_msg.backup.dynamic_more", *args))


class StaticMore(BackupError):
    def __init__(self, *args):
        super().__init__(tr("prompt_msg.backup.static_more", *args))


class NoBackable(BackError):
    def __init__(self):
        super().__init__(tr("prompt_msg.no_backable"))


class BackAbort(BackError):
    def __init__(self):
        super().__init__(tr("prompt_msg.back.abort"))


class LackInfoFile(BackError):
    def __init__(self):
        super().__init__(tr("prompt_msg.back.lack_info_file"))


class LackRegionFile(BackError):
    def __init__(self):
        super().__init__(tr("prompt_msg.back.lack_region_file"))


class BackTimeout(BackError):
    def __init__(self):
        super().__init__(tr("prompt_msg.back.timeout"))


class InvalidInfoDimension(BackError):
    def __init__(self, *args):
        super().__init__(tr("prompt_msg.invalid_info_dimension", *args))
