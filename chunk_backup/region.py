import datetime
import json
import os
import re
import math
import shutil
import time
import traceback
import copy
from collections import defaultdict
from region_backup import cfg, tr
from region_backup.config import cb_info
from concurrent.futures import ThreadPoolExecutor
from mcdreforged.api.all import *


class Region:
    backup_state = None
    back_state = None

    def __init__(self):
        self.slot = None
        self.backup_path = None

    def save_info_file(self, command=None, comment=None, src=None):
        info_path = os.path.join(self.backup_path, self.slot, "info.json")
        info = cb_info.get_default().serialize()
        info["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        info["backup_dimension"] = getattr(self, "dimension")
        info["user"] = src.get_info().player if src else tr("comment.console")
        info["command"] = command
        info["comment"] = comment

        with open(info_path, "w", encoding="utf-8") as fp:
            json.dump(info, fp, ensure_ascii=False, indent=4)

    @classmethod
    def clear(cls):
        cls.backup_state = None
        cls.back_state = None

    @classmethod
    def save_backup_path_(cls, backup_path):
        cls.__backup_path = backup_path

    @classmethod
    def get_backup_path(cls, command):
        if len(command.split()) > 2 and command.split()[2] == "-s":
            return cfg["config"].static_backup_path
        return cfg["config"].backup_path

    @classmethod
    def get_total_size(cls, folder_paths):
        """计算多个文件夹的总大小（多线程优化）"""
        total_size = 0
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(cls.get_folder_size, folder_path): folder_path for folder_path in folder_paths}
            for future in futures:
                try:
                    total_size += future.result()
                except Exception:
                    folder_path = futures[future]
                    ServerInterface.get_instance().logger.info(
                        f"计算§c{folder_path}§r的大小时出错:§e{traceback.format_exc()}")

        return cls.convert_bytes(total_size), total_size

    @classmethod
    def get_folder_size(cls, folder_path):
        """计算单个文件夹的大小"""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                try:
                    # 解析符号链接
                    real_path = os.path.realpath(file_path)
                    total_size += os.path.getsize(real_path)
                except (FileNotFoundError, PermissionError):
                    # 忽略无法访问的文件
                    continue

        return total_size

    @classmethod
    def convert_bytes(cls, size):
        """将字节数转换为人类可读的格式（如 KB、MB、GB）"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f}{unit}"
            size /= 1024

        return f"{size:.2f}PB"

    @classmethod
    def organize_slot(cls, backup_path=cfg["config"].backup_path, rename=None):
        if not os.path.exists(backup_path):
            os.makedirs(backup_path)
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

                return msg

            if len(sorted_list) == max_slots:
                if backup_path != cfg.backup_path:
                    return tr("backup_error.static_more_than", max_slots, len(sorted_list))
                shutil.rmtree(os.path.join(backup_path, f"slot{max_slots}"), ignore_errors=True)
                sorted_list.pop()

            if slot_list:
                rename_slots(2)
                clear_temp()

            os.makedirs(os.path.join(backup_path, "slot1"), exist_ok=True)
            return

        if slot_list:
            rename_slots()
            clear_temp()

        return len(
            [i for i in os.listdir(backup_path) if os.path.isdir(os.path.join(backup_path, i)) and pattern.match(i)]
        )

    @classmethod
    def coordinate_transfer(cls, raw_coordinate, r=0, command="make"):
        if command == "make":
            x, z = raw_coordinate
            return cls.coordinate_transfer(
                [
                    (int(x // 16 - r) // 32, int(x // 16 + r) // 32), (int(z // 16 + r) // 32, int(z // 16 - r) // 32)
                ],
                command="pos_make"
            )

        elif command == "pos_make":
            coordinate = []
            left = min((raw_coordinate[0]))
            right = max(raw_coordinate[0])
            top = max(raw_coordinate[-1])
            bottom = min(raw_coordinate[-1])

            for x in range(left, right + 1):
                for z in range(bottom, top + 1):
                    coordinate.append((x, z))
            return coordinate

    @staticmethod
    def _copy_files(src_folder, dst_folder, files=None):
        """将指定文件从源文件夹复制到目标文件夹"""
        if not files:
            if os.path.exists(src_folder):
                if os.path.exists(dst_folder):
                    shutil.rmtree(dst_folder, ignore_errors=True)
                shutil.copytree(src_folder, dst_folder)
            return

        for filename in files:
            src_path = os.path.join(src_folder, filename)
            dst_path = os.path.join(dst_folder, filename)
            shutil.copy2(src_path, dst_path)

    @classmethod
    def _process_region(cls, folders, src_base, dst_base, slot_base=None, backup_mode="file"):
        """处理单个区域的文件夹备份和恢复"""
        for folder in folders:
            src_folder = os.path.join(src_base, folder)
            dst_folder = os.path.join(dst_base, folder)

            if slot_base:
                slot_folder = os.path.join(slot_base, folder)
                if backup_mode == "file":
                    os.makedirs(dst_folder, exist_ok=True)
                    slot_files = os.listdir(slot_folder)
                    # 备份源文件夹到覆盖备份路径
                    cls._copy_files(src_folder, dst_folder, slot_files)
                    # 从备份槽复制文件到源文件夹
                    cls._copy_files(slot_folder, src_folder, slot_files)

                else:
                    if os.path.exists(src_folder):
                        if os.path.exists(dst_folder):
                            shutil.rmtree(src_folder, ignore_errors=True)
                        shutil.copytree(src_folder, dst_folder)
                        shutil.rmtree(src_folder, ignore_errors=True)
                        shutil.copytree(slot_folder, src_folder)

            else:
                if backup_mode == "file":
                    slot_files = os.listdir(dst_folder)
                    # 从覆盖备份复制文件到源文件夹
                    cls._copy_files(dst_folder, src_folder, slot_files)
                else:
                    if os.path.exists(dst_folder):
                        shutil.rmtree(src_folder, ignore_errors=True)
                        shutil.copytree(dst_folder, src_folder)

    @classmethod
    def back(cls, region_folder):
        overwrite_folder = os.path.join(cfg.backup_path, cfg.overwrite_backup_folder)
        backup_path = cls.get_backup_path_()
        # 如果覆盖备份文件夹存在且当前备份槽不是覆盖备份文件夹，则清空覆盖备份文件夹
        if os.path.exists(overwrite_folder) and cls.back_slot != cfg.overwrite_backup_folder:
            shutil.rmtree(overwrite_folder)
            os.makedirs(overwrite_folder)

        with open(os.path.join(backup_path, cls.back_slot, "info.json"), "rb") as fp:
            buffer = fp.read()
            content = buffer.decode('utf-8') if buffer[:3] != b'\xef\xbb\xbf' else buffer[3:].decode('utf-8')
            info = json.loads(content)

        backup_mode = "folder" if info["command"].split()[1] == "dim_make" else "file"

        # 如果当前备份槽不是覆盖备份文件夹，则进行备份和恢复操作
        if cls.back_slot != cfg.overwrite_backup_folder:
            for region_info in region_folder.values():
                world_name, folders = region_info[0], region_info[-1]
                region_origin = os.path.join(server_path, world_name)
                region_overwrite = os.path.join(overwrite_folder, world_name)
                region_slot = os.path.join(backup_path, cls.back_slot, world_name)
                cls._process_region(
                    folders, region_origin, region_overwrite, region_slot, backup_mode
                )
            cls.save_info_file(
                list(region_folder.keys()), cfg.backup_path, info["command"], tr("comment.overwrite_comment"),
                cfg.overwrite_backup_folder
            )
        else:
            # 如果当前备份槽是覆盖备份文件夹，则直接从覆盖备份恢复
            for region_info in region_folder.values():
                world_name, folders = region_info[0], region_info[-1]
                region_origin = os.path.join(server_path, world_name)
                region_overwrite = os.path.join(overwrite_folder, world_name)
                cls._process_region(folders, region_origin, region_overwrite, backup_mode=backup_mode)

    @classmethod
    def copy(cls, dimension, backup_path=cfg.backup_path, coordinate=None, slot_="slot1"):
        time.sleep(0.1)

        # 遍历 dimension_info 字典
        for dim_key, info in dimension_info.items():
            # 检查维度键是否匹配（考虑数字字符串和原始字符串）
            if dimension == info["dimension"] or dim_key == dimension:
                region_folder = info["region_folder"]
                world_name = info["world_name"]
                break  # 找到匹配项后退出循环
        else:
            # 如果没有找到匹配项，可以在这里处理（例如，设置默认值或抛出异常）
            region_folder = None  # 或其他默认值
            world_name = None  # 或其他默认值

        if not region_folder or not world_name:
            return 1

        backup_dir = os.path.join(backup_path, slot_, world_name)

        if not coordinate:
            for folder in region_folder:
                if os.path.exists(os.path.join(backup_dir, folder)):
                    shutil.rmtree(os.path.join(backup_dir, folder))

                try:
                    shutil.copytree(
                        os.path.join(server_path, world_name, folder),
                        os.path.join(backup_dir, folder)
                    )

                except FileNotFoundError:
                    continue
            return

        for i, folder in enumerate(region_folder):
            os.makedirs(os.path.join(backup_dir, folder), exist_ok=True)
            for positions in coordinate:
                if not positions:
                    continue
                x, z = positions
                file = f"r.{x}.{z}.mca"
                try:
                    shutil.copy2(
                        os.path.join(server_path, world_name, folder, file),
                        os.path.join(backup_dir, folder, file)
                    )

                except FileNotFoundError:
                    continue

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
            return
        for k1, v1 in dimension_info.items():
            v1_new = copy.deepcopy(v1)
            v1_new["dimension"] = k1
            new_dict[v1["dimesnion"]] = v1_new
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
        if not isinstance(coords, tuple) or len(coords) not in (1, 2):
            raise ValueError("参数必须是包含1或2个元素的元组")

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
            if radius < 0:
                raise ValueError("半径不能为负数")

            # 计算实际区块尺寸（边长 = 2r + 1）
            actual_size = 2 * radius + 1
            if actual_size > self.max_chunk_size:
                raise ValueError(f"半径{radius}导致边长{actual_size}超过最大值{self.max_chunk_size}")

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
            local_x = chunk_x % 32
            local_z = chunk_z % 32
            region_map[region_key].add((local_x, local_z))

        # 第二步：构建结果字典
        result = {}
        for region, chunks in region_map.items():
            # 判断是否覆盖整个区域
            if len(chunks) == 32 * 32:
                result[region] = region
            else:
                # 转换为排序后的元组列表
                sorted_chunks = sorted(chunks, key=lambda c: (c[0], c[1]))
                result[region] = [tuple(c) for c in sorted_chunks]

        return result
