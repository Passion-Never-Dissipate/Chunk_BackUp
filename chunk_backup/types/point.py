from typing import Union
from dataclasses import dataclass
from chunk_backup.config.config import Config
from chunk_backup.utils.region.chunk_selector import ChunkSelector as chunk


@dataclass
class Point3D:
    x: Union[int, float]
    y: Union[int, float]
    z: Union[int, float]

    def __post_init__(self):
        self.x = float(self.x)
        self.y = float(self.y)
        self.z = float(self.z)

    def __add__(self, other):
        if isinstance(other, Point3D):
            return Points(self, other)
        else:
            return NotImplemented

    def to_point2d(self):
        return Point2D(self.x, self.z)


@dataclass
class Point2D:
    """只有一个坐标，对应半径模式"""
    x: Union[int, float]
    z: Union[int, float]

    def __post_init__(self):
        self.x = float(self.x)
        self.z = float(self.z)

    def __add__(self, other):
        if isinstance(other, Point2D):
            return Points(self, other)
        else:
            return NotImplemented

    def to_chunk_selector(self, radius, max_chunk_size=None, ignore_size_limit=False):
        """通过中心点和半径创建 ChunkSelector 对象"""
        max_chunk_size = max_chunk_size if max_chunk_size else Config.get().backup.max_chunk_length
        return chunk(self, radius=radius, max_chunk_size=max_chunk_size, ignore_size_limit=ignore_size_limit)


@dataclass
class Points:
    """有两个坐标，对应两点模式"""
    p1: Union[Point2D, Point3D]
    p2: Union[Point2D, Point3D]

    def to_chunk_selector(self, max_chunk_size=None, ignore_size_limit=False):
        """通过两个点创建 ChunkSelector 对象"""
        max_chunk_size = max_chunk_size if max_chunk_size else Config.get().backup.max_chunk_length
        return chunk(self, max_chunk_size=max_chunk_size, ignore_size_limit=ignore_size_limit)
