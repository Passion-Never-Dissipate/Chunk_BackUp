from typing import Optional
from chunk_backup.utils.mc_version import is_version_ge_26_1
from mcdreforged.api.utils import Serializable


class BackupConfig(Serializable):
    dimension: Optional[dict[str, dict]] = None
    player_data: Optional[dict] = None
    max_dynamic_slot: int = 10
    max_static_slot: int = 50
    max_chunk_length: int = 320

    @staticmethod
    def _build_dimension_structure(version_tag: str) -> dict:
        """根据版本标识('ver_1'/'ver_2')生成默认的 dimension 字典"""
        from chunk_backup.utils.mcdr_utils import tr
        return {
            "minecraft:overworld": {
                "integer_id": 0,
                "world_name": "world",
                "description": tr("other.dimension.overworld").to_plain_text(),
                "region_folder": [
                    "poi" if version_tag == "ver_1" else "dimensions/minecraft/overworld/poi",
                    "entities" if version_tag == "ver_1" else "dimensions/minecraft/overworld/entities",
                    "region" if version_tag == "ver_1" else "dimensions/minecraft/overworld/region"
                ]
            },
            "minecraft:the_nether": {
                "integer_id": -1,
                "world_name": "world",
                "description": tr("other.dimension.the_nether").to_plain_text(),
                "region_folder": [
                    "DIM-1/poi" if version_tag == "ver_1" else "dimensions/minecraft/the_nether/poi",
                    "DIM-1/entities" if version_tag == "ver_1" else "dimensions/minecraft/the_nether/poi",
                    "DIM-1/region" if version_tag == "ver_1" else "dimensions/minecraft/the_nether/poi"
                ]
            },
            "minecraft:the_end": {
                "integer_id": 1,
                "world_name": "world",
                "description": tr("other.dimension.the_end").to_plain_text(),
                "region_folder": [
                    "DIM1/poi" if version_tag == "ver_1" else "dimensions/minecraft/the_end/poi",
                    "DIM1/entities" if version_tag == "ver_1" else "dimensions/minecraft/the_end/poi",
                    "DIM1/region" if version_tag == "ver_1" else "dimensions/minecraft/the_end/poi"
                ]
            }
        }

    @classmethod
    def _build_player_data_structure(cls, version_tag: str) -> dict:
        """根据版本标签('ver_1'/'ver_2')生成默认的 player_data 字典"""
        if version_tag == "ver_2":
            # Minecraft 26.1 及以后版本
            return {
                ".json": [
                    "world/players/advancements",
                    "world/players/stats"
                ],
                ".dat": [
                    "world/players/playerdata"
                ]
            }
        else:
            # 旧版本 (26.1 之前)
            return {
                ".json": [
                    "world/advancements",
                    "world/stats"
                ],
                ".dat": [
                    "world/playerdata"
                ]
            }

    @classmethod
    def upgrade_all(cls, config, minecraft_version: Optional[str]) -> bool:
        """
        统一升级配置：版本号、维度结构、玩家数据路径。
        返回 True 表示任一配置被修改，需要保存。
        """
        target_tag = "ver_2" if is_version_ge_26_1(minecraft_version) else "ver_1"

        modified = False

        # ----- 1. 升级维度结构 -----
        if config.backup.dimension is None:
            config.backup.dimension = cls._build_dimension_structure(target_tag)
            config.minecraft_version = minecraft_version
            modified = True
        else:
            current_interval_is_ver2 = False
            if config.minecraft_version is not None:
                current_interval_is_ver2 = is_version_ge_26_1(config.minecraft_version)
            target_interval_is_ver2 = is_version_ge_26_1(minecraft_version)

            if current_interval_is_ver2 != target_interval_is_ver2:
                config.backup.dimension = cls._build_dimension_structure(target_tag)
                config.minecraft_version = minecraft_version
                modified = True
            elif config.minecraft_version != minecraft_version:
                config.minecraft_version = minecraft_version
                modified = True

        # ----- 2. 升级玩家数据路径 -----
        if config.backup.player_data is None:
            config.backup.player_data = cls._build_player_data_structure(target_tag)
            config.minecraft_version = minecraft_version
            modified = True
        else:
            current_interval_is_ver2_player = False
            if config.minecraft_version is not None:
                current_interval_is_ver2_player = is_version_ge_26_1(config.minecraft_version)
            target_interval_is_ver2_player = is_version_ge_26_1(minecraft_version)

            if current_interval_is_ver2_player != target_interval_is_ver2_player:
                config.backup.player_data = cls._build_player_data_structure(target_tag)
                config.minecraft_version = minecraft_version
                modified = True
            elif config.minecraft_version != minecraft_version:
                config.minecraft_version = minecraft_version
                modified = True

        return modified
