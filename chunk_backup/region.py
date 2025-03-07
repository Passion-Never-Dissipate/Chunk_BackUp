import datetime
import json
import os
import re
import math
import shutil
import time
import copy

from typing import Optional
from collections import defaultdict

from chunk_backup.config import cb_config, cb_info
from chunk_backup.chunk import Chunk as chunk
from chunk_backup.tools import tr, FileStatsAnalyzer as analyzer
from mcdreforged.api.types import InfoCommandSource


def ignore_specific_files(src_dir, extensions):
    src_dir = os.path.normpath(src_dir)

    def _ignore_func(dir_path, filenames):
        # 如果当前目录不在源目录内，直接忽略所有内容（安全防护）
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
        self.src: Optional[InfoCommandSource] = None
        self.backup_type: str = "chunk"
        self.backup_path: Optional[str] = None
        self.slot: str = "slot1"
        self.coords: Optional[dict] = None
        self.dimension: Optional[str, list] = []
        self.world_name: Optional[str, list] = []
        self.region_folder: Optional[list] = None

    def copy(self):
        time.sleep(0.1)

        if self.backup_type == "chunk":

            source_dir = [os.path.join(self.cfg.server_path, self.world_name, folder) for folder in self.region_folder]
            target_dir = [os.path.join(self.backup_path, self.slot, self.world_name, folder) for folder in
                          self.region_folder]

            for source in source_dir:
                for folder in self.coords:
                    if not os.path.exists(os.path.join(source, folder.replace("region", "mca"))):
                        self.src.get_server().broadcast("区块备份范围内有区块对应的区域文件尚未在世界上生成,请调整备份范围")
                        return

            for source, target in zip(source_dir, target_dir):
                os.makedirs(target, exist_ok=True)
                chunk.export_grouped_regions(source, target, self.coords)

        else:
            server_path = self.cfg.server_path
            diemsnion_info = self.cfg.dimension_info
            for dimension in self.dimension:
                world_name = diemsnion_info[dimension]["world_name"]
                self.world_name.append(world_name)
                region_folder = diemsnion_info[dimension]["region_folder"]
                source_dir = [os.path.join(server_path, world_name, folder) for folder in region_folder]
                target_dir = [os.path.join(self.backup_path, self.slot, world_name, folder) for folder in region_folder]
                extensions = (".mca",)
                for source, target in zip(source_dir, target_dir):
                    if os.path.exists(target):
                        shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(
                        source,
                        target,
                        ignore=ignore_specific_files(source, extensions),
                        dirs_exist_ok=True
                    )
            self.dimension = [diemsnion_info[d]["dimension"] for d in self.dimension]

        return True

    def back(self):
        overwrite_folder = os.path.join(self.cfg.backup_path, self.cfg.overwrite_backup_folder)
        server_path = self.cfg.server_path
        swap_dict = Region.swap_dimension_key(self.cfg.dimension_info)

        if os.path.exists(overwrite_folder) and self.slot != self.cfg.overwrite_backup_folder:
            shutil.rmtree(overwrite_folder)
            os.makedirs(overwrite_folder)

        backup_path = self.backup_path
        if self.slot != self.cfg.overwrite_backup_folder:
            for dimension in self.dimension:
                world_name = swap_dict[dimension]["world_name"]
                region_folder = swap_dict[dimension]["region_folder"]
                for region_dir in region_folder:
                    source_dir = os.path.join(backup_path, self.slot, world_name, region_dir)
                    target_dir = os.path.join(server_path, world_name, region_dir)
                    overwrite_dir = os.path.join(overwrite_folder, world_name, region_dir)
                    if self.backup_type == "chunk":
                        Region._process_chunk(source_dir, target_dir, overwrite_dir)
                    else:
                        Region._process_region(source_dir, target_dir, overwrite_dir)

        else:
            for dimension in self.dimension:
                world_name = swap_dict[dimension]["world_name"]
                region_folder = swap_dict[dimension]["region_folder"]
                for region_dir in region_folder:
                    source_dir = os.path.join(backup_path, self.slot, world_name, region_dir)
                    target_dir = os.path.join(server_path, world_name, region_dir)
                    if self.backup_type == "chunk":
                        Region._process_chunk(source_dir, target_dir)
                    else:
                        Region._process_region(source_dir, target_dir)

    @classmethod
    def _process_chunk(cls, source_dir, target_dir, overwrite_dir=None):
        ext = [".region", ".mca"]
        region = analyzer(source_dir)
        region.scan_by_extension(ext)
        all_ = region.get_ext_report()
        if overwrite_dir:
            os.makedirs(overwrite_dir, exist_ok=True)
        if ".mca" in all_:
            for file in all_[".mca"]["files"]:
                source_file = os.path.join(source_dir, file)
                target_file = os.path.join(target_dir, file)
                if os.path.exists(target_file) and overwrite_dir:
                    overwrite_file = os.path.join(overwrite_dir, file)
                    shutil.copy2(target_file, overwrite_file)
                shutil.copy2(source_file, target_file)

        if ".region" in all_:
            for file in all_[".region"]["files"]:
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
                    shutil.rmtree(overwrite_dir)

    def save_info_file(self, src: InfoCommandSource = None, comment=None):
        info_path = os.path.join(self.backup_path, self.slot, "info.json")
        info = cb_info.get_default().serialize()
        info["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        info["command"] = src.get_info().content if src and src.get_info().is_player else tr("comment.console")
        info["user"] = src.get_info().player if src and src.get_info().is_player else tr("comment.console")
        info["backup_dimension"] = self.dimension
        info["comment"] = comment if comment else tr("comment.empty_comment")
        info["backup_type"] = self.backup_type
        info["world_name"] = self.world_name

        with open(info_path, "w", encoding="utf-8") as fp:
            json.dump(info, fp, ensure_ascii=False, indent=4)

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
    def organize_slot(cls, src: InfoCommandSource = None, backup_path=None, cfg=cb_config, rename=False):
        if not os.path.exists(cfg.backup_path) or not os.path.exists(cfg.static_backup_path):
            os.makedirs(cfg.backup_path, exist_ok=True)
            os.makedirs(cfg.static_backup_path, exist_ok=True)
        pattern = re.compile(r'^slot([1-9]\d*)$')
        slot_list = [
            i for i in os.listdir(backup_path) if os.path.isdir(os.path.join(backup_path, i)) and pattern.match(i)
        ]
        sorted_list = sorted(slot_list, key=lambda x: int(re.search(r'\d+', x).group()))
        temp = []

        def clear_temp():
            """清除临时文件夹的标记"""
            for i in temp:
                os.rename(os.path.join(backup_path, i), os.path.join(backup_path, i.strip("_temp")))

        def rename_slots(index=1):
            """重命名文件夹"""
            for i, v in zip(range(len(sorted_list) - 1, -1, -1), reversed(sorted_list)):
                new_name = f"slot{i + index}"
                if v == new_name:
                    continue

                if i > 0 and new_name in sorted_list:
                    temp.append(f"{new_name}_temp")
                    os.rename(os.path.join(backup_path, v), os.path.join(backup_path, f"{new_name}_temp"))
                else:
                    os.rename(os.path.join(backup_path, v), os.path.join(backup_path, new_name))

        if rename:
            max_slots = cfg.static_slot if backup_path != cfg.backup_path else cfg.slot

            if len(sorted_list) > max_slots:
                msg = tr(
                    "backup_error.static_more_than", max_slots, len(sorted_list)
                ) if backup_path != cfg.backup_path else tr(
                    "backup_error.dynamic_more_than", max_slots, len(sorted_list)
                )

                src.get_server().broadcast(msg)
                return

            if len(sorted_list) == max_slots:
                if backup_path != cfg.backup_path:
                    return tr("backup_error.static_more_than", max_slots, len(sorted_list))
                shutil.rmtree(os.path.join(backup_path, f"slot{max_slots}"), ignore_errors=True)
                sorted_list.pop()

            if slot_list:
                rename_slots(2)
                clear_temp()

            os.makedirs(os.path.join(backup_path, "slot1"), exist_ok=True)
            return True

        if slot_list:
            rename_slots()
            clear_temp()

        return len(
            [i for i in os.listdir(backup_path) if os.path.isdir(os.path.join(backup_path, i)) and pattern.match(i)]
        )

    @classmethod
    def check_dimension(cls, dimension_info):
        dim = set()
        for value in dimension_info.values():
            dimension = value["dimension"]  # 假设 "dimension" 键必然存在
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
    """

    def __init__(self, coordinates, max_chunk_size=51):
        self.max_chunk_size = max_chunk_size
        self._validate_input(coordinates)
        self.chunk_coords = self._calculate_chunks()

    def _validate_input(self, coords):
        """增强参数验证（新增范围限制检查）"""

        # 公共验证逻辑
        def check_size(width, height):
            if width > self.max_chunk_size or height > self.max_chunk_size:
                raise ValueError(f"区块范围不得超过{self.max_chunk_size}x{self.max_chunk_size}（当前尺寸：{width}x{height}）")

        # 两点坐标模式
        if len(coords) == 2:
            self.mode = 'rectangle'
            (x1, z1), (x2, z2) = coords
            self.chunk1 = (math.floor(x1 / 16), math.floor(z1 / 16))
            self.chunk2 = (math.floor(x2 / 16), math.floor(z2 / 16))

            # 计算实际区块尺寸
            width = abs(self.chunk1[0] - self.chunk2[0]) + 1
            height = abs(self.chunk1[1] - self.chunk2[1]) + 1
            check_size(width, height)

        # 中心点+半径模式
        else:
            self.mode = 'square'
            (center_x, center_z), radius = coords[0]
            print(center_x, center_z, radius)
            # 计算实际区块尺寸（边长 = 2r + 1）
            actual_size = 2 * radius + 1
            if actual_size > self.max_chunk_size:
                raise ValueError(f"给定区块半径{radius}导致区块边长{actual_size}超过最大值{self.max_chunk_size}")

            # 计算区块范围
            center_chunk = (math.floor(center_x / 16), math.floor(center_z / 16))
            self.chunk1 = (center_chunk[0] - radius, center_chunk[1] - radius)
            self.chunk2 = (center_chunk[0] + radius, center_chunk[1] + radius)

    def _calculate_chunks(self):
        """计算所选区域内的所有区块坐标"""
        min_x = min(self.chunk1[0], self.chunk2[0])
        max_x = max(self.chunk1[0], self.chunk2[0])
        min_z = min(self.chunk1[1], self.chunk2[1])
        max_z = max(self.chunk1[1], self.chunk2[1])

        return {
            (x, z)
            for x in range(min_x, max_x + 1)
            for z in range(min_z, max_z + 1)
        }

    def group_by_region(self):
        """将区块按区域文件分组，返回指定格式的字典"""
        region_map = defaultdict(set)

        # 第一步：分组到区域
        for chunk_x, chunk_z in self.chunk_coords:
            region_x = chunk_x // 32
            region_z = chunk_z // 32
            region_key = f"r.{region_x}.{region_z}.mca"
            """local_x = chunk_x % 32
            local_z = chunk_z % 32"""
            region_map[region_key].add((chunk_x, chunk_z))

        # 第二步：构建结果字典
        result = {}
        for _region, chunks in region_map.items():
            # 判断是否覆盖整个区域
            if len(chunks) == 32 * 32:
                result[_region] = _region
            else:
                # 转换为排序后的元组列表
                sorted_chunks = sorted(chunks, key=lambda c: (c[0], c[1]))
                result[_region] = [tuple(c) for c in sorted_chunks]

        return result
