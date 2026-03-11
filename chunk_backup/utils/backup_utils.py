import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from mcdreforged.api.types import CommandSource
from chunk_backup.exceptions import StaticMore, DynamicMore
from chunk_backup.config.config import Config
from chunk_backup.mcdr_globals import server
from chunk_backup.utils.mcdr_utils import reply_message as reply, tr


class DimensionChecker:
    """
    维度注册表，管理维度字典的校验和查询。
    """

    def __init__(self, source: CommandSource, dimensions: Dict[str, Dict[str, Any]]):
        """
        初始化注册表，检查每个维度条目：
        - 是否包含必需的四个键：integer_id, world_name, description, region_folder
        - integer_id 是否重复

        :param source: 命令源，用于发送错误消息
        :param dimensions: 维度字典，格式如示例所示
        """
        self.source = source
        self._dimensions = dimensions
        self._id_to_key_cache = None
        self._has_duplicate = False
        self._duplicate_check_done = False  # 新增：标记是否已完成重复检查

    @classmethod
    def create(cls, source, dimensions):
        if not dimensions:
            reply(source, tr('task.create_backup.no_dimension'))
            return None
        checker = cls(source, dimensions)
        if not checker._validate_required_keys():
            return None
        if checker.has_duplicate_integer_id():
            reply(source, tr('task.create_backup.repeat_id'))
            return None
        return checker

    def _validate_required_keys(self):
        for key, info in self._dimensions.items():
            missing = [f for f in ('integer_id', 'world_name', 'description', 'region_folder') if f not in info]

            if missing:
                reply(self.source, tr("task.create_backup.lack_key_word", dimension=key, missing=",".join(missing)))
                return False  # 或抛出异常
        return True

    def _build_id_map(self):
        """构建 integer_id -> key 的映射，同时检查重复 ID"""
        id_map = {}
        has_duplicate = False
        for key, info in self._dimensions.items():
            int_id = info['integer_id']
            if int_id in id_map:
                has_duplicate = True
            else:
                id_map[int_id] = key
        self._id_to_key_cache = id_map
        self._has_duplicate = has_duplicate
        self._duplicate_check_done = True

    # ---------- 公开校验方法 ----------
    def get_integer_ids(self) -> List[int]:
        """
        返回所有维度的 integer_id 列表。

        注意：若存在重复 ID，列表中将包含重复值。
        可以使用 set() 去重，或先调用 has_duplicate_integer_id() 检查。
        """
        return [info['integer_id'] for info in self._dimensions.values()]

    def has_duplicate_integer_id(self) -> bool:
        """
        判断 integer_id 是否存在重复。

        :return: 若有重复返回 True，否则返回 False
        """
        if not self._duplicate_check_done:
            self._build_id_map()
        return self._has_duplicate

    def all_region_folders_non_empty(self) -> bool:
        """
        判断所有 region_folder 列表是否都至少包含一个字符串。

        :return: 全部非空返回 True，否则返回 False
        """
        for key, info in self._dimensions.items():
            folder = info.get('region_folder')
            if not isinstance(folder, list) or len(folder) == 0:
                return False
        return True

    # ---------- 查询方法 ----------
    def get_by_id(self, integer_id: int, is_key=True) -> Optional[Dict[str, Any]]:
        """
        通过 integer_id 获取维度信息。

        注意：若存在重复 ID，则返回第一次出现的 key 对应的信息。
        建议先调用 has_duplicate_integer_id() 确认无重复。

        :param integer_id: 维度的数字 ID
        :return: 包含 key、world_name、description、region_folder 的字典，
                 如果 ID 不存在则返回 None 并发送提示
        """
        if self._id_to_key_cache is None:
            self._build_id_map()
        key = self._id_to_key_cache.get(integer_id)
        if key is None:
            reply(self.source, tr("task.create_backup.lack_integer_id", integer_id=integer_id))
            return None
        info = self._dimensions[key]
        return {
            'key': key,
            'world_name': info['world_name'],
            'description': info['description'],
            'region_folder': info['region_folder']
        } if not is_key else key

    def get_all(self) -> List[Dict[str, Any]]:
        """
        返回所有维度的完整信息列表，每个元素包含：
        key, integer_id, world_name, description, region_folder
        """
        result = []
        for key, info in self._dimensions.items():
            result.append({
                'key': key,
                'integer_id': info['integer_id'],
                'world_name': info['world_name'],
                'description': info['description'],
                'region_folder': info['region_folder']
            })
        return result


class BackupFolderManager:
    # 预编译正则，避免重复编译
    _slot_pattern = re.compile(r'^slot([1-9]\d*)$')

    def __init__(self, is_static=False):
        self.config = Config.get()
        self.is_static = is_static
        self.backup_slot = "slot1"
        self.server_root = Path(self.config.server_root)
        self.storage_root = Path(self.config.storage_root)
        self.region_storage = Path(self.config.dynamic_storage) if not self.is_static else Path(self.config.static_storage)

    def check_region_folder(self):
        _region_storage = self.storage_root / self.region_storage
        _region_storage.mkdir(parents=True, exist_ok=True)

    def _get_slot_items(self, storage_path):
        """返回 (数字, 名称) 的列表，按数字升序排序"""
        items = []
        for item in storage_path.iterdir():
            if not item.is_dir():
                continue
            match = self._slot_pattern.match(item.name)
            if match:
                num = int(match.group(1))
                items.append((num, item.name))
        items.sort(key=lambda x: x[0])
        return items

    def _clean_temp_dirs(self, storage_path):
        """删除所有以 _temp 结尾的目录"""
        for item in storage_path.iterdir():
            if item.is_dir() and item.name.endswith('_temp'):
                shutil.rmtree(item)

    def _rename_to_temp(self, items, storage_path):
        """
        将 items 中的每个目录重命名为 原名称_temp
        items: [(num, name)] 列表，顺序任意
        """
        for num, name in items:
            old_path = storage_path / name
            temp_name = f"{name}_temp"
            temp_path = storage_path / temp_name
            old_path.rename(temp_path)

    def _rename_from_temp(self, items, storage_path, start_from):
        """
        将 items 中对应的临时目录重命名为 slot{start_from}, slot{start_from+1}, ...
        items: [(num, name)] 列表，顺序即最终顺序
        """
        for idx, (num, name) in enumerate(items, start=start_from):
            temp_name = f"{name}_temp"
            temp_path = storage_path / temp_name
            new_name = f"slot{idx}"
            new_path = storage_path / new_name
            temp_path.rename(new_path)

    def _rename_continuous(self, items, storage_path, start_from=1):
        """连续重命名 items 列表中的目录为 slot{start_from} 开始"""
        self._clean_temp_dirs(storage_path)
        self._rename_to_temp(items, storage_path)
        self._rename_from_temp(items, storage_path, start_from)

    def remove_slot(self, path: Path = None):
        if not path:
            shutil.rmtree(self.storage_root / self.region_storage / "slot1", ignore_errors=True)
            return
        shutil.rmtree(Path, ignore_errors=True)

    def organize_region_folder(self, only_sort=False, is_overwrite=False):
        """
        整理 region 备份文件夹中的槽位。

        :param only_sort: 如果为 True，仅对现有槽位进行重命名使其连续（从1开始），不进行删除/创建操作，
                         返回重命名后的槽位列表（按数字从大到小排序）。
                         如果为 False，则根据备份类型和当前数量执行完整整理（可能删除/创建槽位），
                         然后重命名所有剩余槽位，返回从小到大排序的列表。
        :return: 排序后的槽位名称列表。
        :raises ValueError: 当操作非法时抛出异常。
        """
        if is_overwrite:
            overwrite_storage = self.storage_root / self.config.overwrite_storage
            if overwrite_storage.exists():
                shutil.rmtree(overwrite_storage)

            overwrite_storage.mkdir(parents=True)
            return

        self.check_region_folder()
        _region_storage = self.storage_root / self.region_storage
        max_slot = self.config.backup.max_static_slot if self.is_static else self.config.backup.max_dynamic_slot

        # 获取所有槽位并按数字升序排序
        items = self._get_slot_items(_region_storage)  # [(num, name)]

        # ----- 仅排序模式：重命名现有槽位为连续（不删除/创建）-----
        if only_sort:
            self._rename_continuous(items, _region_storage, start_from=1)
            # 返回从大到小排序的名称列表（即数字降序）
            return [name for num, name in reversed(items)]

        # ----- 正常整理模式 -----
        current_count = len(items)

        # 情况1：当前数量小于上限
        if current_count < max_slot:
            to_keep = items  # 保留所有

        # 情况2：当前数量等于上限
        elif current_count == max_slot:
            if self.is_static:
                raise StaticMore(max_slot)
            else:
                # 动态备份：删除最大槽位（列表最后一项）
                max_num, max_name = items[-1]
                max_slot_path = _region_storage / max_name
                shutil.rmtree(max_slot_path)
                to_keep = items[:-1]  # 移除最后一项

        # 情况3：当前数量大于上限
        else:
            raise DynamicMore(max_slot, current_count)

        # 清理所有残留的 *_temp 目录
        self._clean_temp_dirs(_region_storage)

        # 将保留的旧槽位重命名为临时名称
        self._rename_to_temp(to_keep, _region_storage)

        # 创建全新的空 slot1（如果已存在则先删除）
        slot1_path = _region_storage / "slot1"
        if slot1_path.exists():
            if slot1_path.is_dir():
                shutil.rmtree(slot1_path)
            else:
                slot1_path.unlink()
        slot1_path.mkdir(parents=True, exist_ok=False)

        # 将临时名称重命名为 slot2, slot3, ...
        self._rename_from_temp(to_keep, _region_storage, start_from=2)

    def get_slot_range(self, start: int, end: int):
        """
        获取 region_storage 文件夹内按数字从小到大排序后，第 start 到第 end 个槽位目录（包含两端）。
        不修改任何槽位名称，仅根据现有目录的数字排序返回对应路径。

        :param start: 起始位置（正整数，从1开始）
        :param end: 结束位置（正整数，且 >= start）
        :return: 路径列表 (list of Path)，如果范围内无槽位则返回空列表
        """
        region_storage_path = self.storage_root / self.region_storage
        if not region_storage_path.exists():
            return []
        # 获取所有槽位，按数字升序
        items = self._get_slot_items(region_storage_path)  # [(num, name)]

        # 计算切片范围（列表索引从0开始）
        start_idx = start - 1
        end_idx = end  # 切片时，[start_idx:end_idx] 会取到 end_idx-1 为止
        selected = items[start_idx:end_idx]

        return [region_storage_path / name for num, name in selected]

    def count_slots(self) -> int:
        """
        返回 region_storage 文件夹内当前存在的槽位数量。
        不会对文件夹进行任何整理或修改。
        """
        region_storage_path = self.storage_root / self.region_storage
        if not region_storage_path.exists():
            return 0
        items = self._get_slot_items(region_storage_path)
        return len(items)

    def get_min_slot_name(self) -> Optional[str]:
        """
        返回 region_storage 文件夹中数字最小的槽位目录名称（如 'slot1'）。
        如果没有槽位，返回 None。
        """
        region_storage_path = self.storage_root / self.region_storage
        if not region_storage_path.exists():
            return None
        items = self._get_slot_items(region_storage_path)  # 已按数字升序排序
        if items:
            return items[0][1]  # 返回最小槽位的名称
        return None

    def get_all_slot_name(self, integer=False) -> List[Union[str, int]]:
        """
        返回 region_storage 文件夹内所有槽位的目录名称列表（按数字升序排序）。
        如果文件夹不存在或没有槽位，返回空列表。
        """
        region_storage_path = self.storage_root / self.region_storage
        if not region_storage_path.exists():
            return []
        items = self._get_slot_items(region_storage_path)
        if integer:
            return [num for num, name in items]
        else:
            return [name for num, name in items]


class PlayerDataFolderManager:
    def __init__(self, uuid: Union[str, list], is_static=None):
        self.config = Config.get()
        self.uuid = uuid if isinstance(uuid, list) else [uuid]
        self.is_static = is_static
        self.backup_slot = "slot1"
        self.server_root = Path(self.config.server_root)
        self.storage_root = Path(self.config.storage_root)
        self.region_storage = Path(self.config.dynamic_storage) if not self.is_static else Path(self.config.static_storage)

    def _get_backup_root(self, is_overwrite: bool = False) -> Path:
        """
        获取玩家数据备份的根目录。
        如果 is_overwrite=True，则使用 overwrite 槽位，否则使用常规槽位（动态/静态）。
        """
        if is_overwrite:
            return self.storage_root / self.config.overwrite_storage / "players"
        else:
            return self.storage_root / self.region_storage / self.backup_slot / "players"

    def _ensure_backup_structure(self, backup_root: Path):
        """确保备份目录存在"""
        backup_root.mkdir(parents=True, exist_ok=True)

    def backup_player_data(self, is_overwrite: bool = False):
        """
        将世界文件夹中指定 UUID 的玩家数据备份到备份槽位。
        忽略不存在的文件，仅输出警告。
        """
        player_data_cfg = self.config.backup.player_data
        if not player_data_cfg:
            server.logger.warning("No player_data configuration found, skipping backup")
            return

        world_root = self.server_root
        backup_root = self._get_backup_root(is_overwrite)
        self._ensure_backup_structure(backup_root)

        for uuid in self.uuid:
            for ext, folders in player_data_cfg.items():
                for folder in folders:
                    src = world_root / folder / f"{uuid}{ext}"
                    if src.exists():
                        dst = backup_root / folder / f"{uuid}{ext}"
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        server.logger.debug(f"Backed up {src} -> {dst}")
                    else:
                        # 文件不存在，忽略并警告
                        server.logger.warning(tr("other.warn.player_data_not_found", uuid=uuid, path=str(src)))

    def restore_player_data(self, is_overwrite: bool = False):
        """
        从备份槽位将指定 UUID 的玩家数据恢复到世界文件夹。
        忽略不存在的文件，仅输出警告。
        """
        player_data_cfg = self.config.backup.player_data
        if not player_data_cfg:
            server.logger.warning("No player_data configuration found, skipping restore")
            return

        world_root = self.server_root
        backup_root = self._get_backup_root(is_overwrite)

        if not backup_root.exists():
            server.logger.warning(f"Backup root not found: {backup_root}")
            return

        for uuid in self.uuid:
            for ext, folders in player_data_cfg.items():
                for folder in folders:
                    src = backup_root / folder / f"{uuid}{ext}"
                    if src.exists():
                        dst = world_root / folder / f"{uuid}{ext}"
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        server.logger.debug(f"Restored {src} -> {dst}")
                    else:
                        server.logger.warning(tr("task.backup_restore.player_data_not_found_backup", uuid=uuid, path=str(src)))
