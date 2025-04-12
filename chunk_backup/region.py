import datetime
import json
import os
import re
import math
import shutil
import time
import copy
import traceback

from typing import Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from mcdreforged.api.types import ServerInterface, InfoCommandSource
from chunk_backup.config import cb_config, cb_info, cb_custom_info, sub_slot_info
from chunk_backup.chunk import Chunk as chunk
from chunk_backup.errors import MaxChunkLength, MaxChunkRadius, StaticMore, DynamicMore
from chunk_backup.tools import tr, LazyFileAnalyzer as analyzer


def ignore_specific_files(src_dir, extensions):
    src_dir = os.path.normpath(src_dir)

    def _ignore_func(dir_path, filenames):
        # 如果当前目录不在源目录内，直接忽略所有内容
        if os.path.commonpath([src_dir, dir_path]) != src_dir:
            return filenames

        # 如果是子目录，直接忽略所有内容
        if os.path.normpath(dir_path) != src_dir:
            return filenames

        ignored = []
        for filename in filenames:
            file_path = os.path.join(dir_path, filename)
            # 忽略所有子目录（严格判断类型）
            if os.path.isdir(file_path):
                ignored.append(filename)
            # 忽略不匹配扩展名的文件
            elif not any(filename.endswith(ext) for ext in extensions):
                ignored.append(filename)
        return ignored

    return _ignore_func


class Region:
    backup_state = None
    back_state = None

    def __init__(self):
        self.cfg = cb_config
        self.backup_type: str = "chunk"
        self.backup_path: Optional[str] = None
        self.slot: str = "slot1"
        self.coords: Optional[dict] = {}
        self.dimension: Optional[list] = []

    def copy(self):
        time.sleep(0.1)

        # 根据备份类型选择处理方式
        if self.backup_type in ("chunk", "custom"):
            self._parallel_export_regions()
        else:
            self._parallel_copy_directories()

    def _parallel_export_regions(self):
        """多线程处理区块导出"""

        # 准备任务列表
        tasks = []
        swap_dict = Region.swap_dimension_key(self.cfg.dimension_info)
        for dimension in self.dimension:
            world_name = swap_dict[dimension]["world_name"]
            coords = self.coords[dimension]
            for folder in swap_dict[dimension]["region_folder"]:
                source_dir = os.path.join(self.cfg.server_path, world_name, folder)
                target_dir = os.path.join(self.backup_path, self.slot, world_name, folder)
                tasks.append((source_dir, target_dir, coords))

        # 使用线程池并行处理
        with ThreadPoolExecutor(self.cfg.max_workers) as executor:
            futures = []
            for source, target, coord_data in tasks:
                # 确保目标目录存在（主线程中预先创建）
                os.makedirs(target, exist_ok=True)
                # 提交导出任务
                futures.append(
                    executor.submit(
                        chunk.export_grouped_regions,
                        source,
                        target,
                        coord_data
                    )
                )

            # 处理任务结果
            for future in as_completed(futures):
                try:
                    future.result()

                except Exception:
                    ServerInterface.get_instance().broadcast(tr("unknown_error", traceback.format_exc()))

    def _parallel_copy_directories(self):
        """多线程处理目录复制"""

        # 准备任务列表
        tasks = []
        for dimension in self.dimension:
            world_name = self.cfg.dimension_info[dimension]["world_name"]
            region_folder = self.cfg.dimension_info[dimension]["region_folder"]
            for folder in region_folder:
                source = os.path.join(self.cfg.server_path, world_name, folder)
                target = os.path.join(self.backup_path, self.slot, world_name, folder)
                tasks.append((source, target))

        else:
            self.dimension = [self.cfg.dimension_info[d]["dimension"] for d in self.dimension]

        # 使用线程池并行处理
        with ThreadPoolExecutor(self.cfg.max_workers) as executor:
            futures = []
            for source, target in tasks:
                futures.append(
                    executor.submit(
                        self._safe_copytree,
                        source,
                        target,
                        (".mca",)
                    )
                )

            # 处理任务结果
            for future in as_completed(futures):
                try:
                    future.result()

                except Exception:
                    ServerInterface.get_instance().broadcast(tr("unknown_error", traceback.format_exc()))

    @staticmethod
    def _safe_copytree(source, target, extensions):
        """线程安全的目录复制"""
        if os.path.exists(target):
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(
            source,
            target,
            ignore=ignore_specific_files(source, extensions),
            dirs_exist_ok=True
        )

    def back(self):
        overwrite_folder = os.path.join(self.cfg.backup_path, self.cfg.overwrite_backup_folder)
        server_path = self.cfg.server_path
        swap_dict = Region.swap_dimension_key(self.cfg.dimension_info)

        if os.path.exists(overwrite_folder) and self.slot != self.cfg.overwrite_backup_folder:
            shutil.rmtree(overwrite_folder, ignore_errors=True)
            os.makedirs(overwrite_folder, exist_ok=True)

        backup_path = self.backup_path
        with ThreadPoolExecutor(max_workers=self.cfg.max_workers) as executor:
            futures = []

            for dimension in self.dimension:
                world_name = swap_dict[dimension]["world_name"]
                region_folder = swap_dict[dimension]["region_folder"]
                for region_dir in region_folder:
                    # 获取路径参数
                    source_dir = os.path.join(backup_path, self.slot, world_name, region_dir)
                    if not os.path.exists(source_dir):
                        continue
                    target_dir = os.path.join(server_path, world_name, region_dir)
                    overwrite_dir = os.path.join(overwrite_folder, world_name, region_dir) if self.slot != self.cfg.overwrite_backup_folder else None

                    # 提交任务到线程池
                    futures.append(executor.submit(
                        self._process_single_region,
                        dimension,
                        source_dir,
                        target_dir,
                        overwrite_dir
                    ))

            # 等待所有任务完成并处理异常
            for future in as_completed(futures):
                try:
                    future.result()

                except Exception:
                    ServerInterface.get_instance().logger.error(tr("unknown_error", traceback.format_exc()))

    def _process_single_region(self, dimension, source_dir, target_dir, overwrite_dir):
        """单个区域文件的处理逻辑（线程安全）"""
        if getattr(self, "sub_slot_groups", None):
            # 自定义回档逻辑
            if overwrite_dir:
                os.makedirs(overwrite_dir, exist_ok=True)
            chunk.custom_restore_direct(
                source_dir,
                target_dir,
                self.coords[dimension],  # 需要确保线程安全访问
                overwrite_dir
            )
        elif self.backup_type in ("chunk", "custom"):
            self._process_chunk(source_dir, target_dir, overwrite_dir)
        else:
            self._process_region(source_dir, target_dir, overwrite_dir)

    @classmethod
    def _process_chunk(cls, source_dir, target_dir, overwrite_dir=None):
        region = analyzer(source_dir)
        all_ = region.get_file_list(extensions={".region", ".mca"})
        if overwrite_dir:
            os.makedirs(overwrite_dir, exist_ok=True)
        if ".mca" in all_:
            for file in all_[".mca"]:
                source_file = os.path.join(source_dir, file)
                target_file = os.path.join(target_dir, file)

                if overwrite_dir:
                    overwrite_file = os.path.join(overwrite_dir, file)
                    if os.path.exists(target_file):
                        shutil.copy2(target_file, overwrite_file)
                    else:
                        chunk.init_region_file(overwrite_file)

                shutil.copy2(source_file, target_file)

        if ".region" in all_:
            for file in all_[".region"]:
                source_file = os.path.join(source_dir, file)
                target_file = os.path.join(target_dir, file.replace(".region", ".mca"))
                overwrite_file = os.path.join(overwrite_dir, file) if overwrite_dir else overwrite_dir
                chunk.merge_region_file(source_file, target_file, overwrite=True, backup_path=overwrite_file)

        if overwrite_dir:
            with os.scandir(overwrite_dir) as entries:
                for _ in entries:
                    break
                else:
                    os.rmdir(overwrite_dir)

    @classmethod
    def _process_region(cls, source_dir, target_dir, overwrite_dir=None):
        if os.path.exists(target_dir) and overwrite_dir:
            shutil.copytree(
                target_dir,
                overwrite_dir,
                ignore=ignore_specific_files(target_dir, (".mca",)),
                dirs_exist_ok=True
            )
            shutil.rmtree(target_dir, ignore_errors=True)

        shutil.copytree(
            source_dir,
            target_dir,
            ignore=ignore_specific_files(source_dir, (".mca",)),
            dirs_exist_ok=True
        )

        if overwrite_dir:
            with os.scandir(overwrite_dir) as entries:
                has_mca = False

                for entry in entries:
                    if entry.is_file() and entry.name.endswith(".mca"):  # type: ignore
                        has_mca = True
                        break

                # 当没有.mca文件时删除
                if not has_mca:
                    shutil.rmtree(overwrite_dir, ignore_errors=True)

    def organize_slot(self):
        _cfg = self.cfg
        backup_path = self.backup_path

        self._ensure_backup_dirs(_cfg)

        sorted_list = self._get_sorted_slots(backup_path)
        max_slots = _cfg.static_slot if backup_path != _cfg.backup_path else _cfg.slot

        if len(sorted_list) > max_slots:
            raise StaticMore(max_slots, len(sorted_list)) if backup_path != _cfg.backup_path else DynamicMore(max_slots, len(sorted_list))

        if len(sorted_list) == max_slots:
            if backup_path == _cfg.backup_path:
                shutil.rmtree(os.path.join(backup_path, f"slot{max_slots}"), ignore_errors=True)
                sorted_list.pop()
            else:
                raise StaticMore(max_slots, len(sorted_list))

        temp_list = self._rename_slots(backup_path, sorted_list, index=2)
        self._clear_temp(backup_path, temp_list)

        os.makedirs(os.path.join(backup_path, "slot1"), exist_ok=True)

    def save_info_file(self, src: InfoCommandSource = None, comment=None):
        info_path = os.path.join(self.backup_path, self.slot, "info.json")
        if not src: info_path = os.path.join(self.cfg.backup_path, self.cfg.overwrite_backup_folder, "info.json")
        info = cb_info.get_default().serialize()
        info["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        info["command"] = src.get_info().content if src else tr("prompt_msg.comment.nocommand")
        info["user"] = src.get_info().player if src and src.get_info().is_player else tr("prompt_msg.comment.console")
        info["backup_dimension"] = self.dimension
        info["comment"] = comment if comment else tr("prompt_msg.comment.overwrite_comment")
        info["backup_type"] = "chunk" if getattr(self, "custom_back", None) else self.backup_type
        info["minecraft_version"] = ServerInterface.get_instance().get_server_information().version
        if getattr(self, "user_pos", None): info["user_pos"] = getattr(self, "user_pos")

        if getattr(self, "selector_obj", None):
            info["chunk_top_left_pos"] = [i for i in getattr(self, "selector_obj").corner_chunks["top_left"]]
            info["chunk_bottom_right_pos"] = [i for i in getattr(self, "selector_obj").corner_chunks["bottom_right"]]

        with open(info_path, "w", encoding="utf-8") as fp:
            json.dump(info, fp, ensure_ascii=False, indent=4)

    def save_custom_info_file(self, custom_obj: dict, src: InfoCommandSource = None, overwrite=False):
        info_path = os.path.join(self.backup_path, self.slot, "info.json")
        if overwrite: info_path = os.path.join(self.cfg.backup_path, self.cfg.overwrite_backup_folder, "info.json")
        info = cb_custom_info.get_default().serialize()
        info["custom_name"] = custom_obj["custom_name"]
        info["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        info["time_created"] = custom_obj["time_created"]
        info["user"] = src.get_info().player if src and src.get_info().is_player else tr("prompt_msg.comment.console")
        info["user_created"] = custom_obj["user_created"]
        info["version_created"] = custom_obj["version_created"]
        info["backup_dimension"] = self.dimension
        info["minecraft_version"] = ServerInterface.get_instance().get_server_information().version

        sub_slots = custom_obj["sub_slot"]
        for index, sub_slot in enumerate(sub_slots.values(), start=1):
            sub_info = sub_slot_info.get_default().serialize()
            sub_info["time_created"] = sub_slot["time_created"]
            sub_info["user_created"] = sub_slot["user_created"]
            sub_info["backup_type"] = sub_slot["backup_type"]
            if sub_slot.get("user_pos"): sub_info["user_pos"] = sub_slot["user_pos"]
            sub_info["chunk_top_left_pos"] = sub_slot["chunk_top_left_pos"]
            sub_info["chunk_bottom_right_pos"] = sub_slot["chunk_bottom_right_pos"]
            sub_info["backup_dimension"] = sub_slot["backup_dimension"]
            sub_info["command"] = sub_slot["command"]
            sub_info["comment"] = sub_slot["comment"]
            sub_info["version_created"] = sub_slot["version_created"]
            info["sub_slot"][str(index)] = sub_info

        with open(info_path, "w", encoding="utf-8") as fp:
            json.dump(info, fp, ensure_ascii=False, indent=4)

    @classmethod
    def _ensure_backup_dirs(cls, cfg):
        """确保备份目录存在"""
        if not os.path.exists(cfg.backup_path) or not os.path.exists(cfg.static_backup_path):
            os.makedirs(cfg.backup_path, exist_ok=True)
            os.makedirs(cfg.static_backup_path, exist_ok=True)

    @classmethod
    def _get_sorted_slots(cls, backup_path, numeric_only=False):
        """获取排序后的slot列表"""
        pattern = re.compile(r'^slot([1-9]\d*)$')  # 匹配非零开头的自然数
        slot_entries = []
        for dir_name in os.listdir(backup_path):
            dir_path = os.path.join(backup_path, dir_name)
            if os.path.isdir(dir_path) and (match := pattern.match(dir_name)):
                # 根据参数决定存储格式：纯数字或保留slot前缀[1,3]
                slot_entries.append(int(match.group(1)) if numeric_only else dir_name)

        # 按数值排序（无论输出格式如何）[2,4]
        return sorted(slot_entries, key=lambda x: int(re.search(r'\d+', str(x)).group()))

    @classmethod
    def _rename_slots(cls, backup_path, sorted_list, index):
        """执行重命名操作并返回临时目录列表"""
        temp_list = []
        for i, v in zip(range(len(sorted_list) - 1, -1, -1), reversed(sorted_list)):
            new_name = f"slot{i + index}"
            if v == new_name:
                continue

            target_path = os.path.join(backup_path, new_name)
            if i > 0 and os.path.exists(target_path):
                temp_name = f"{new_name}_temp"
                temp_list.append(temp_name)
                os.rename(os.path.join(backup_path, v), os.path.join(backup_path, temp_name))
            else:
                os.rename(os.path.join(backup_path, v), os.path.join(backup_path, new_name))
        return temp_list

    @classmethod
    def _clear_temp(cls, backup_path, temp_list):
        """清理临时目录"""
        for name in temp_list:
            src = os.path.join(backup_path, name)
            dest = os.path.join(backup_path, name.replace("_temp", ""))
            os.rename(src, dest)

    @classmethod
    def get_slot_number(cls, backup_path, cfg):
        cls._ensure_backup_dirs(cfg)

        sorted_list = cls._get_sorted_slots(backup_path)

        temp_list = cls._rename_slots(backup_path, sorted_list, index=1)
        cls._clear_temp(backup_path, temp_list)

        return len(cls._get_sorted_slots(backup_path))

    @classmethod
    def clear(cls):
        cls.backup_state = None
        cls.back_state = None

    @classmethod
    def get_backup_path(cls, cfg, command):
        if len(command.split()) > 2 and command.split()[2] == "-s":
            return cfg.static_backup_path
        return cfg.backup_path

    @classmethod
    def check_dimension(cls, dimension_info):
        dim = set()
        for value in dimension_info.values():
            dimension = value["dimension"]
            if dimension in dim:
                return None  # 发现重复，立即返回
            dim.add(dimension)
        # 无重复时返回所有唯一值（或根据需求调整返回值）
        return True

    @classmethod
    def swap_dimension_key(cls, dimension_info):
        new_dict = {}
        if not cls.check_dimension(dimension_info):
            return None
        for k1, v1 in dimension_info.items():
            v1_new = copy.deepcopy(v1)
            v1_new["dimension"] = k1
            new_dict[v1["dimension"]] = v1_new
        return new_dict


class ChunkSelector:
    """
    Minecraft区块选择器（新增范围限制功能）
    支持两种参数模式：
    1. 两点坐标模式：((x1, z1), (x2, z2)) -> 矩形区域
    2. 中心点+半径模式：((x_center, z_center), radius) -> 正方形区域

    新增参数：
    max_chunk_size：最大允许区块边长（默认51，即51x51的区域）
    ignore_size_limit：是否跳过尺寸检查（默认False）
    """

    def __init__(self, coordinates, max_chunk_size=51, ignore_size_limit=False):
        self.max_chunk_size = max_chunk_size
        self.ignore_size_limit = ignore_size_limit  # 新增控制参数
        self._validate_input(coordinates)
        self._calculate_boundaries()

    def _validate_input(self, coords):
        """增强参数验证（新增尺寸检查开关）"""
        def check_size(width, height):
            # 仅在未忽略检查时触发异常
            if not self.ignore_size_limit and (width > self.max_chunk_size or height > self.max_chunk_size):
                raise MaxChunkLength(self.max_chunk_size, width, height)

        if len(coords) == 2 and isinstance(coords[0], (tuple, list)) and len(coords[0]) == 2:
            self.mode = 'rectangle'
            (x1, z1), (x2, z2) = coords
            self.chunk1 = (math.floor(x1/16), math.floor(z1/16))
            self.chunk2 = (math.floor(x2/16), math.floor(z2/16))

            width = abs(self.chunk1[0]-self.chunk2[0]) + 1
            height = abs(self.chunk1[1]-self.chunk2[1]) + 1
            check_size(width, height)
        else:
            self.mode = 'square'
            (center_x, center_z), radius = coords[0]
            actual_size = 2*radius + 1
            # 增加检查开关判断
            if not self.ignore_size_limit and actual_size > self.max_chunk_size:
                raise MaxChunkRadius(radius, actual_size, self.max_chunk_size)
            center_chunk = (math.floor(center_x/16), math.floor(center_z/16))
            self.chunk1 = (center_chunk[0]-radius, center_chunk[1]-radius)
            self.chunk2 = (center_chunk[0]+radius, center_chunk[1]+radius)

    def _calculate_boundaries(self):
        """计算区块范围并保存边界值"""
        self.min_x = min(self.chunk1[0], self.chunk2[0])
        self.max_x = max(self.chunk1[0], self.chunk2[0])
        self.min_z = min(self.chunk1[1], self.chunk2[1])
        self.max_z = max(self.chunk1[1], self.chunk2[1])

    def _generate_chunks(self):
        """按需生成区块坐标集合（新增方法）"""
        return {
            (x, z)
            for x in range(self.min_x, self.max_x + 1)
            for z in range(self.min_z, self.max_z + 1)
        }

    @property
    def corner_chunks(self):
        """获取四角区块坐标字典"""
        return {
            'top_left': (self.min_x, self.min_z),
            'bottom_left': (self.min_x, self.max_z),
            'top_right': (self.max_x, self.min_z),
            'bottom_right': (self.max_x, self.max_z)
        }

    def intersects(self, other):
        """判断两个区块选择器是否有交集"""

        x_overlap = (self.min_x <= other.max_x) and (self.max_x >= other.min_x)
        z_overlap = (self.min_z <= other.max_z) and (self.max_z >= other.min_z)
        return x_overlap and z_overlap

    @classmethod
    def combine_and_group(cls, selectors):
        """合并多个选区并生成区域分组结果"""
        # 验证输入类型并收集所有区块坐标
        """print(selectors)
        if not all(isinstance(s, ChunkSelector) for s in selectors):
            raise TypeError("所有参数必须是ChunkSelector实例")"""

        combined_chunks = set()
        for selector in selectors:
            combined_chunks.update(selector._generate_chunks())  # 调用各实例的生成方法

        # 复用分组逻辑
        return cls._group_chunks(combined_chunks)

    @classmethod
    def from_chunk_coords(cls, chunk1, chunk2, max_chunk_size=51, ignore_size_limit=False):
        """
        直接通过区块坐标创建选区
        :param chunk1: 区块坐标1，格式 (chunk_x, chunk_z)
        :param chunk2: 区块坐标2，格式 (chunk_x, chunk_z)
        :param max_chunk_size: 最大允许区块边长
        :param ignore_size_limit: 是否跳过尺寸检查
        :return: ChunkSelector 实例
        """

        # 将区块坐标转换为世界坐标中点（如区块0的中心为(8,8)）
        def to_world_center(chunk_coord):
            return chunk_coord[0] * 16 + 8, chunk_coord[1] * 16 + 8

        world_coord1 = to_world_center(chunk1)
        world_coord2 = to_world_center(chunk2)
        return cls(
            coordinates=(world_coord1, world_coord2),
            max_chunk_size=max_chunk_size,
            ignore_size_limit=ignore_size_limit
        )

    @staticmethod
    def _group_chunks(chunk_coords):
        """通用分组逻辑（供实例方法和合并方法共用）"""
        region_map = defaultdict(set)
        for x, z in chunk_coords:
            region_x, region_z = x // 32, z // 32
            region_key = f"r.{region_x}.{region_z}.mca"
            region_map[region_key].add((x, z))

        result = {}
        for region, chunks in region_map.items():
            result[region] = region if len(chunks) == 32 ** 2 else sorted(chunks)
        return result

    def group_by_region(self):
        """更新后的实例方法（复用通用逻辑）"""
        return self._group_chunks(self._generate_chunks())
