import functools
from typing import Optional
from chunk_backup.config.command_config import CommandConfig
from chunk_backup.config.server_config import ServerConfig
from chunk_backup.config.backup_config import BackupConfig
from mcdreforged.api.utils import Serializable


class Config(Serializable):
    # ---------- 实例字段 ----------
    server_root: str = './server'
    storage_root: str = './cb_files'
    log_storage: str = 'logs'
    static_storage: str = 'static_storage'
    dynamic_storage: str = 'dynamic_storage'
    overwrite_storage: str = 'overwrite'
    max_workers: int = 4
    config_version: Optional[str] = None  # 从文件读取的版本号
    minecraft_version: Optional[str] = None

    command: CommandConfig = CommandConfig()
    server: ServerConfig = ServerConfig()
    backup: BackupConfig = BackupConfig()

    def upgrade_version(self, plugin_version: str) -> bool:
        """将配置文件版本更新为当前插件版本，返回 True 表示需要保存"""
        if self.config_version != plugin_version:
            self.config_version = plugin_version
            return True
        return False

    # ---------- 单例管理（仅用于向其他模块暴露当前配置）----------
    @classmethod
    @functools.lru_cache
    def __get_default(cls) -> 'Config':
        return cls.get_default()

    @classmethod
    def get(cls) -> 'Config':
        if _config is None:
            return cls.__get_default()
        return _config


_config: Optional[Config] = None


def set_config_instance(cfg: Config):
    global _config
    _config = cfg
