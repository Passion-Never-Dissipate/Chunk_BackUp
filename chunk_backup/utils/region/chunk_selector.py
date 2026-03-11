import math
from collections import defaultdict

from chunk_backup.exceptions import MaxChunkLength, MaxChunkRadius


class ChunkSelector:
    """
    Minecraft区块选择器（支持多个不相连矩形）
    创建方式：
    1. 两点坐标模式：传入 Points 对象（包含 p1, p2 两个 Point2D 对象）
    2. 中心点+半径模式：传入 Point2D 对象，并指定 radius 参数
    3. 通过加法合并多个选择器
    4. 通过 from_index 从索引文件创建

    参数：
    point : Point2D 或 Points 对象
    radius : int，当 point 为 Point2D 时必须提供，表示半径（区块个数）
    max_chunk_size : 最大允许区块边长（默认51，即51x51的区域）
    ignore_size_limit : 是否跳过尺寸检查（默认False）
    """

    def __init__(self, point, radius=None, max_chunk_size=51, ignore_size_limit=False):
        self.max_chunk_size = max_chunk_size
        self.ignore_size_limit = ignore_size_limit
        self.radius = radius
        self._rectangles = []  # 存储矩形列表，每个矩形为 (min_x, min_z, max_x, max_z)
        self._validate_input(point)
        self._update_bounds()

    def __add__(self, other):
        if not isinstance(other, ChunkSelector):
            return NotImplemented
        new_rects = self._rectangles + other._rectangles
        return self._from_rectangles(new_rects, self.max_chunk_size, self.ignore_size_limit)

    __radd__ = __add__

    def _validate_input(self, point):
        """验证输入并生成矩形列表（单个矩形）"""

        def check_size(width, height):
            if not self.ignore_size_limit and (width > self.max_chunk_size or height > self.max_chunk_size):
                raise MaxChunkLength(self.max_chunk_size, width, height)

        # 判断为 Point2D-like 对象（有 x, z 属性且没有 p1 属性）
        if hasattr(point, 'x') and hasattr(point, 'z') and not hasattr(point, 'p1'):
            # 半径模式
            if self.radius is None:
                raise ValueError("当 point 为 Point2D 时，必须提供 radius 参数")
            self.mode = 'square'
            center_x, center_z = point.x, point.z
            actual_size = 2 * self.radius + 1
            if not self.ignore_size_limit and actual_size > self.max_chunk_size:
                raise MaxChunkRadius(self.radius, actual_size, self.max_chunk_size)
            center_chunk = (math.floor(center_x / 16), math.floor(center_z / 16))
            min_x = center_chunk[0] - self.radius
            max_x = center_chunk[0] + self.radius
            min_z = center_chunk[1] - self.radius
            max_z = center_chunk[1] + self.radius
            self._rectangles = [(min_x, min_z, max_x, max_z)]

        # 判断为 Points-like 对象（有 p1, p2 属性）
        elif hasattr(point, 'p1') and hasattr(point, 'p2'):
            self.mode = 'rectangle'
            p1, p2 = point.p1, point.p2
            x1, z1 = p1.x, p1.z
            x2, z2 = p2.x, p2.z
            chunk1 = (math.floor(x1 / 16), math.floor(z1 / 16))
            chunk2 = (math.floor(x2 / 16), math.floor(z2 / 16))
            min_x = min(chunk1[0], chunk2[0])
            max_x = max(chunk1[0], chunk2[0])
            min_z = min(chunk1[1], chunk2[1])
            max_z = max(chunk1[1], chunk2[1])
            width = max_x - min_x + 1
            height = max_z - min_z + 1
            check_size(width, height)
            self._rectangles = [(min_x, min_z, max_x, max_z)]

        else:
            raise TypeError("point 必须是 Point2D 或 Points 对象")

    def _update_bounds(self):
        """根据当前矩形列表更新总边界（用于兼容旧属性）"""
        if not self._rectangles:
            self.min_x = self.max_x = self.min_z = self.max_z = 0
        else:
            self.min_x = min(r[0] for r in self._rectangles)
            self.max_x = max(r[2] for r in self._rectangles)
            self.min_z = min(r[1] for r in self._rectangles)
            self.max_z = max(r[3] for r in self._rectangles)

    @classmethod
    def _from_rectangles(cls, rectangles, max_chunk_size, ignore_size_limit):
        """从矩形列表创建新对象（跳过正常初始化）"""
        obj = cls.__new__(cls)
        obj.max_chunk_size = max_chunk_size
        obj.ignore_size_limit = ignore_size_limit
        obj.radius = None
        obj.mode = 'multi'
        obj._rectangles = rectangles
        obj._update_bounds()
        return obj

    def _iter_chunks(self):
        """生成器，依次产生选区内的所有区块坐标 (x, z)"""
        for min_x, min_z, max_x, max_z in self._rectangles:
            for x in range(min_x, max_x + 1):
                for z in range(min_z, max_z + 1):
                    yield x, z

    def _generate_chunks(self):
        """返回所有区块坐标的集合（去重）"""
        return set(self._iter_chunks())

    @classmethod
    def from_chunk_coords(cls, chunk1, chunk2, max_chunk_size=51, ignore_size_limit=False):
        """直接通过区块坐标创建选区（两点模式）"""
        from chunk_backup.types.point import Point2D, Points

        def to_world_center(chunk_coord):
            return chunk_coord[0] * 16 + 8, chunk_coord[1] * 16 + 8

        x1, z1 = to_world_center(chunk1)
        x2, z2 = to_world_center(chunk2)
        p1 = Point2D(x1, z1)
        p2 = Point2D(x2, z2)
        points = Points(p1, p2)
        return cls(points, max_chunk_size=max_chunk_size, ignore_size_limit=ignore_size_limit)

    def to_index(self):
        """将当前选区转换为按区域分组的索引字典"""

        # 按区域收集子矩形
        region_rects = defaultdict(list)  # 键: 区域文件名, 值: 子矩形列表

        for (min_x, min_z, max_x, max_z) in self._rectangles:
            # 计算矩形覆盖的区域范围
            r_min_x = min_x // 32
            r_max_x = max_x // 32
            r_min_z = min_z // 32
            r_max_z = max_z // 32

            for rx in range(r_min_x, r_max_x + 1):
                for rz in range(r_min_z, r_max_z + 1):
                    # 计算该矩形在当前区域内的子矩形
                    sub_min_x = max(min_x, rx * 32)
                    sub_max_x = min(max_x, rx * 32 + 31)
                    sub_min_z = max(min_z, rz * 32)
                    sub_max_z = min(max_z, rz * 32 + 31)

                    if sub_min_x <= sub_max_x and sub_min_z <= sub_max_z:
                        region_key = f"r.{rx}.{rz}.mca"
                        region_rects[region_key].append((sub_min_x, sub_min_z, sub_max_x, sub_max_z))

        result = {}
        for region_key, rects in region_rects.items():
            # 检查该区域是否被完全覆盖（即所有区块都被选中）
            if self._is_region_fully_covered(rects):
                result[region_key] = {"rectangles": region_key}
            else:
                rect_list = [(sx, sz, ex, ez) for (sx, sz, ex, ez) in rects]  # 直接使用元组列表
                result[region_key] = {"rectangles": rect_list}

        return result

    @classmethod
    def _split_rectangle_to_regions(cls, rect):
        """
        将一个矩形 (min_x, min_z, max_x, max_z) 拆分为覆盖的各区域内的子矩形。
        返回一个列表，元素为 (区域文件名, 子矩形) 的元组。
        """
        min_x, min_z, max_x, max_z = rect
        r_min_x = min_x // 32
        r_max_x = max_x // 32
        r_min_z = min_z // 32
        r_max_z = max_z // 32
        result = []
        for rx in range(r_min_x, r_max_x + 1):
            for rz in range(r_min_z, r_max_z + 1):
                sub_min_x = max(min_x, rx * 32)
                sub_max_x = min(max_x, rx * 32 + 31)
                sub_min_z = max(min_z, rz * 32)
                sub_max_z = min(max_z, rz * 32 + 31)
                if sub_min_x <= sub_max_x and sub_min_z <= sub_max_z:
                    region_key = f"r.{rx}.{rz}.mca"
                    result.append((region_key, (sub_min_x, sub_min_z, sub_max_x, sub_max_z)))
        return result

    @classmethod
    def combine_and_group(cls, selectors):
        """
        合并多个选区，返回按区域分组的矩形信息。
        返回值格式：{区域文件名: 矩形列表 或 区域文件名}
        """
        region_rects = defaultdict(list)  # 区域 -> 矩形列表
        for sel in selectors:
            for rect in sel._rectangles:
                for region_key, sub_rect in cls._split_rectangle_to_regions(rect):
                    region_rects[region_key].append(sub_rect)

        # 合并每个区域内的矩形并判断是否全覆盖
        result = {}
        for region_key, rects in region_rects.items():
            # 计算该区域内所有被覆盖的区块总数
            if cls._is_region_fully_covered(rects):
                result[region_key] = region_key
            else:
                result[region_key] = rects  # 保持原样（矩形列表）
        return result

    @classmethod
    def get_all_chunks_in_region(cls, region_x, region_z):
        """
        返回指定区域内所有1024个区块的坐标列表。
        :param region_x: 区域X坐标
        :param region_z: 区域Z坐标
        :return: 包含 (x, z) 的列表，x 和 z 均为全局区块坐标
        """
        min_x = region_x * 32
        min_z = region_z * 32
        max_x = min_x + 31
        max_z = min_z + 31
        return [(x, z) for x in range(min_x, max_x + 1) for z in range(min_z, max_z + 1)]

    @classmethod
    def to_block_rectangles_dict(cls, input_dict):
        """
        将维度选择器字典转换为合并后的方块坐标字典。

        输入格式：
        {
            "minecraft:overworld": [selector1, selector2, 'all'],
            "minecraft:the_end": [selector3],
            "twilightforest:twilight_forest": ['all']
        }

        输出格式：
        {
            "overworld": [
                {"x1": -30000000, "x2": 30000000, "z1": -30000000, "z2": 30000000}
            ],
            "the_end": [
                {"x1": 100, "x2": 200, "z1": -50, "z2": 150}
            ],
            "twilightforest:twilight_forest": [
                {"x1": -30000000, "x2": 30000000, "z1": -30000000, "z2": 30000000}
            ]
        }
        """
        MAX_COORD = 30000000
        MIN_COORD = -30000000
        result = {}

        for dim_key, selectors in input_dict.items():
            # 处理命名空间前缀
            if dim_key.startswith("minecraft:"):
                dim_name = dim_key[10:]  # 去掉 "minecraft:"
            else:
                dim_name = dim_key

            # 如果包含 'all'，直接输出全维度矩形
            if 'all' in selectors:
                result[dim_name] = [{
                    'x1': MIN_COORD,
                    'x2': MAX_COORD,
                    'z1': MIN_COORD,
                    'z2': MAX_COORD
                }]
                continue

            # 收集所有选择器的矩形（转换为方块坐标）
            block_rects = []
            for sel in selectors:
                if not isinstance(sel, cls):
                    continue  # 忽略非选择器对象
                for min_x, min_z, max_x, max_z in sel._rectangles:
                    x1 = min_x * 16
                    x2 = max_x * 16 + 15
                    z1 = min_z * 16
                    z2 = max_z * 16 + 15
                    block_rects.append((x1, x2, z1, z2))

            # 合并矩形
            merged = cls._merge_block_rectangles(block_rects)
            result[dim_name] = merged

        return result

    @staticmethod
    def _merge_block_rectangles(rects):
        """合并重叠或相邻的轴对齐矩形（方块坐标）。一次扫描合并，无需多次迭代。"""
        if not rects:
            return []
        # 按 x1 排序
        rects.sort(key=lambda r: (r[0], r[1]))
        merged = []
        cur = list(rects[0])  # 当前合并中的矩形
        for r in rects[1:]:
            # 检查是否可合并：x 方向重叠或相邻，且 z 方向重叠或相邻
            if (cur[1] >= r[0] - 1 and cur[0] <= r[1] + 1) and (max(cur[2], r[2]) <= min(cur[3], r[3]) + 1):
                # 合并
                cur[0] = min(cur[0], r[0])
                cur[1] = max(cur[1], r[1])
                cur[2] = min(cur[2], r[2])
                cur[3] = max(cur[3], r[3])
            else:
                merged.append(tuple(cur))
                cur = list(r)
        merged.append(tuple(cur))
        # 转换为字典格式
        return [{'x1': x1, 'x2': x2, 'z1': z1, 'z2': z2} for x1, x2, z1, z2 in merged]

    @staticmethod
    def _is_region_fully_covered(rects):
        """
        判断给定的矩形列表（均为该区域内的子矩形，坐标范围为全局区块坐标）是否完全覆盖整个 32x32 区域。
        返回 bool。
        """
        bitmap = bytearray(128)  # 1024 bits
        for sx, sz, ex, ez in rects:
            # 遍历矩形内的每个区块
            for x in range(sx, ex + 1):
                for z in range(sz, ez + 1):
                    local_x = x % 32
                    local_z = z % 32
                    idx = local_x + local_z * 32
                    byte_idx = idx >> 3
                    bit_idx = idx & 7
                    bitmap[byte_idx] |= (1 << bit_idx)
        # 检查所有位是否都为 1
        return all(b == 0xFF for b in bitmap)
