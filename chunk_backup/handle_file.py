import os
import json
from collections import defaultdict
from typing import Dict, List, Union


def safe_load_json(target_dir: str):
    with open(target_dir, "rb") as fp:
        buffer = fp.read()
        content = buffer.decode('utf-8') if buffer[:3] != b'\xef\xbb\xbf' else buffer[3:].decode('utf-8')
        info = json.loads(content)
    return info


class FileStatsAnalyzer:
    def __init__(self, target_dir: str):
        """
        文件统计分析器

        :param target_dir: 要分析的目录路径
        """
        self.target_dir = os.path.abspath(target_dir)
        self._validate_directory()
        self.ext_stats: Dict[str, Dict] = {}  # 按扩展名统计的结果
        self.all_files_stats: Dict[str, int] = {}  # 所有文件的路径-大小映射
        self.total_size_bytes = 0  # 全部文件总大小

    def _validate_directory(self) -> None:
        """验证目标目录是否存在且可访问"""
        if not os.path.isdir(self.target_dir):
            raise NotADirectoryError(f"目录不存在或不可访问: {self.target_dir}")
        if not os.access(self.target_dir, os.R_OK):
            raise PermissionError(f"无读取权限: {self.target_dir}")

    def _get_relative_path(self, absolute_path: str) -> str:
        """将绝对路径转换为相对于目标目录的相对路径"""
        return os.path.relpath(absolute_path, self.target_dir)

    def scan_by_extension(self, extensions: List[str]) -> None:
        """
        统计指定扩展名的文件

        :param extensions: 扩展名列表，如 [".mca", ".dat"]
        """
        self.ext_stats = defaultdict(lambda: {"files": [], "total_size": 0})

        for root, _, files in os.walk(self.target_dir):
            for file in files:
                file_ext = os.path.splitext(file)[1]
                if file_ext in extensions:
                    abs_path = os.path.join(root, file)
                    rel_path = self._get_relative_path(abs_path)
                    size = os.path.getsize(abs_path)

                    self.ext_stats[file_ext]["files"].append(rel_path)
                    self.ext_stats[file_ext]["total_size"] += size

        # 转换为普通字典并过滤未找到的扩展名
        self.ext_stats = {
            ext: data
            for ext, data in self.ext_stats.items()
            if len(data["files"]) > 0
        }

    def scan_all_files(self) -> None:
        """统计目录内所有文件"""
        self.all_files_stats.clear()
        self.total_size_bytes = 0

        for root, _, files in os.walk(self.target_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = self._get_relative_path(abs_path)
                size = os.path.getsize(abs_path)

                self.all_files_stats[rel_path] = size
                self.total_size_bytes += size

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """将字节数转换为易读格式"""
        units = ("B", "KB", "MB", "GB", "TB")
        unit_idx = 0
        while size_bytes >= 1024 and unit_idx < len(units) - 1:
            size_bytes /= 1024.0
            unit_idx += 1
        return f"{size_bytes:.2f}{units[unit_idx]}"

    def get_ext_report(self) -> Dict[str, Dict[str, Union[List[str], int, str]]]:
        """生成带格式化大小的扩展名报告"""
        report = {}
        for ext, data in self.ext_stats.items():
            report[ext] = {
                "files": data["files"],
                "total_size_bytes": data["total_size"],
                "total_size_human": self.format_size(data["total_size"])
            }
        return report

    def get_full_report(self) -> Dict[str, Union[Dict, int, str]]:
        """生成完整分析报告"""
        return {
            "by_extension": self.get_ext_report(),
            "all_files": {
                "count": len(self.all_files_stats),
                "total_size_bytes": self.total_size_bytes,
                "total_size_human": self.format_size(self.total_size_bytes)
            }
        }


# 使用示例
if __name__ == "__main__":
    try:
        analyzer = FileStatsAnalyzer("/path/to/your/folder")

        # 统计特定类型文件
        analyzer.scan_by_extension([".mca", ".dat"])
        print("扩展名统计:\n", analyzer.get_ext_report())

        # 统计所有文件
        analyzer.scan_all_files()
        full_report = analyzer.get_full_report()
        print("\n完整报告:\n", full_report)

    except (NotADirectoryError, PermissionError) as e:
        print(f"初始化失败: {e}")
