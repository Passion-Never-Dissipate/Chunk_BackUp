import json
from pathlib import Path
from typing import Optional, Union

from mcdreforged.api.utils import Serializable


# ==============================
# BackupInfo
# ==============================

class BackupInfo(Serializable):

    # ===== 基础信息 =====

    date: str = ''
    type: str = ''
    operator: str = ''
    dimension: list = []
    comment: str = ''
    command: str = ''

    version_created: Optional[str] = None
    minecraft_version: Optional[str] = None

    total_size: int = 0

    # ===== chunk信息 =====

    name: str = ''

    player_position: Optional[dict[str, Union[int, float]]] = None

    top_left: Optional[dict[str, int]] = None
    top_right: Optional[dict[str, int]] = None
    bottom_left: Optional[dict[str, int]] = None
    bottom_right: Optional[dict[str, int]] = None

    uuid_dict: Optional[dict] = None

    sub_backup: Optional[dict[str, "SubBackupInfo"]] = None

    # ===== runtime (不会写入json) =====

    is_static: Optional[bool] = None
    backup_path: Optional[Union[Path, str]] = None
    player_data: Optional[dict] = None
    selector: Optional[dict] = None

    # -------------------------------------------------
    # 子备份
    # -------------------------------------------------

    def add_sub_backup(self, sub_info: "SubBackupInfo") -> None:

        if self.sub_backup is None:
            self.sub_backup = {}

        self.sub_backup[sub_info.name] = sub_info

    # -------------------------------------------------
    # 序列化
    # -------------------------------------------------

    def to_dict(self, *, pre_backup: bool = False, is_overwrite: bool = False) -> dict:
        """
        转换为 JSON 字典
        """
        self.backup_path = str(self.backup_path)
        data = super().serialize()

        # runtime字段删除
        data.pop("backup_path", None)
        data.pop("selector", None)
        data.pop("is_static", None)
        data.pop("player_data", None)

        self._apply_type_filter(data)

        if is_overwrite:
            data.pop("command", None)
            data.pop("player_position", None)

        self._cleanup_none(data)

        return data

    # -------------------------------------------------

    def save_json(self, *, pre_backup: bool = False, is_overwrite: bool = False):

        if self.backup_path is None:
            raise RuntimeError("backup_path not set")

        path = self.backup_path / "info.json"

        data = self.to_dict(
            pre_backup=pre_backup,
            is_overwrite=is_overwrite
        )

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    # -------------------------------------------------
    # 类型过滤
    # -------------------------------------------------

    def _apply_type_filter(self, data: dict):

        t = self.type

        if t == "region":

            self._remove_keys(
                data,
                "name",
                "player_position",
                "top_left",
                "top_right",
                "bottom_left",
                "bottom_right",
                "sub_backup"
            )

        elif t == "chunk":

            self._remove_keys(
                data,
                "name",
                "sub_backup"
            )

        elif t == "custom":

            self._remove_keys(
                data,
                "player_position",
                "top_left",
                "top_right",
                "bottom_left",
                "bottom_right"
            )

    def get_type_key(self):
        if self.type == "region":
            return ["type", "operator", "date", "dimension", "comment", "command", "version_created",
                    "minecraft_version", "total_size", "uuid_dict"]
        elif self.type == "chunk":
            return ["type", "operator", "date", "dimension", "comment", "command", "player_position", "top_left",
                    "top_right", "bottom_left", "bottom_right", "version_created", "minecraft_version", "total_size", "uuid_dict"]
        elif self.type == "custom":
            return ["type", "operator", "date", "dimension", "name", "comment", "command", "sub_backup",
                    "version_created", "minecraft_version", "total_size"]
    # -------------------------------------------------
    # 清理 None
    # -------------------------------------------------

    def _cleanup_none(self, data: dict):

        if data.get("player_position") is None:
            data.pop("player_position", None)

        if data.get("uuid_dict") is None:
            data.pop("uuid_dict", None)

        sub = data.get("sub_backup")

        if isinstance(sub, dict):

            for v in sub.values():

                if v.get("player_position") is None:
                    v.pop("player_position", None)

    # -------------------------------------------------

    @staticmethod
    def _remove_keys(dic: dict, *keys):

        for k in keys:
            dic.pop(k, None)


# ==============================
# SubBackupInfo
# ==============================

class SubBackupInfo(Serializable):

    type: str = ''
    comment: str = ''
    dimension: list = []
    name: str = ''
    slot: int = 0

    player_position: Optional[dict[str, Union[int, float]]] = None

    top_left: Optional[dict[str, int]] = None
    top_right: Optional[dict[str, int]] = None
    bottom_left: Optional[dict[str, int]] = None
    bottom_right: Optional[dict[str, int]] = None

    # -------------------------------------------------

    def serialize(self) -> dict:

        data = super().serialize()

        t = self.type

        if t == "region":

            for key in [
                "player_position",
                "top_left",
                "top_right",
                "bottom_left",
                "bottom_right"
            ]:
                data.pop(key, None)

        return data