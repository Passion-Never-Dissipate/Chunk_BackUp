import concurrent.futures
import json
import os
from os import DirEntry
from mcdreforged.api.types import ServerInterface
from collections import defaultdict
from os.path import splitext, join, relpath, abspath, isdir, isfile
from typing import Dict, List, Optional, Tuple, Union, Set
from chunk_backup.config import cb_config as config


def tr(key, *args):
    return ServerInterface.get_instance().tr(f"chunk_backup.{key}", *args)


def safe_load_json(target_dir: str):
    with open(target_dir, "rb") as fp:
        buffer = fp.read()
        content = buffer.decode('utf-8') if buffer[:3] != b'\xef\xbb\xbf' else buffer[3:].decode('utf-8')
        info = json.loads(content)
    return info


def save_json_file(target_dir: str, dic: dict):
    with open(target_dir, "w", encoding="utf-8") as fp:
        json.dump(dic, fp, indent=4, ensure_ascii=False)


def update_config(old_config, template=config.get_default().serialize()):
    for key in template:
        if key not in old_config:
            old_config[key] = template[key]
        else:
            old_val = old_config[key]
            template_val = template[key]
            if isinstance(old_val, dict) and isinstance(template_val, dict):
                update_config(old_val, template_val)
            elif isinstance(old_val, list) and isinstance(template_val, list):
                for i in range(len(template_val)):
                    if i < len(old_val):
                        old_elem = old_val[i]
                        template_elem = template_val[i]
                        if isinstance(old_elem, dict) and isinstance(template_elem, dict):
                            update_config(old_elem, template_elem)
                    else:
                        old_val.append(template_val[i])
    return old_config


class FileStatsAnalyzer:
    def __init__(self, target_dir: str):
        """
        文件统计分析器

        :param target_dir: 要分析的目录路径
        """
        self.target_dir = abspath(target_dir)
        self._validate_directory()
        self.ext_stats: Dict[str, Dict] = {}
        self.all_files_stats: Dict[str, int] = {}
        self.total_size_bytes = 0

    def _validate_directory(self) -> None:
        """验证目标目录是否存在且可访问"""
        if not isdir(self.target_dir):
            raise NotADirectoryError(f"目录不存在或不可访问: {self.target_dir}")
        if not os.access(self.target_dir, os.R_OK):
            raise PermissionError(f"无读取权限: {self.target_dir}")

    def _get_relative_path(self, absolute_path: str) -> str:
        """将绝对路径转换为相对于目标目录的相对路径"""
        return relpath(absolute_path, self.target_dir)

    def _collect_file_paths(self, include_subdirs: bool) -> List[str]:
        file_paths = []  # 初始化列表
        if include_subdirs:
            for root, _, files in os.walk(self.target_dir):
                for file in files:
                    abs_path = join(root, file)
                    if isfile(abs_path):
                        file_paths.append(abs_path)
        else:
            for entry in os.scandir(self.target_dir):  # type: DirEntry
                if entry.is_file():
                    file_paths.append(entry.path)
        return file_paths

    def scan_by_extension(
            self,
            extensions: List[str],
            max_workers: Optional[int] = None,
            include_subdirs: bool = False
    ) -> None:
        """
        统计指定扩展名的文件（可选包含子文件夹）

        :param extensions: 扩展名列表，如 [".mca", ".dat"]
        :param max_workers: 线程池最大工作线程数
        :param include_subdirs: 是否包含子目录文件（默认False）
        """
        self.ext_stats = defaultdict(lambda: {"files": [], "total_size": 0})
        target_extensions = set(extensions)
        file_paths = self._collect_file_paths(include_subdirs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self._process_single_file,
                    fp,
                    target_extensions=target_extensions
                )
                for fp in file_paths
            ]

            for future in concurrent.futures.as_completed(futures):
                ext, rel_path, size = future.result()
                if ext:
                    self.ext_stats[ext]["files"].append(rel_path)
                    self.ext_stats[ext]["total_size"] += size

        # 清理空数据并转换字典类型
        self.ext_stats = {
            ext: {"files": data["files"], "total_size": data["total_size"]}
            for ext, data in self.ext_stats.items()
            if data["files"]
        }

    def scan_all_files(
            self,
            max_workers: Optional[int] = None,
            include_subdirs: bool = False
    ) -> None:
        """
        统计目录内所有文件（可选包含子文件夹）

        :param max_workers: 线程池最大工作线程数
        :param include_subdirs: 是否包含子目录文件（默认False）
        """
        self.all_files_stats.clear()
        self.total_size_bytes = 0
        file_paths = self._collect_file_paths(include_subdirs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self._process_single_file,
                    fp,
                    get_all_files=True
                )
                for fp in file_paths
            ]

            results = [future.result() for future in concurrent.futures.as_completed(futures)]

            for _, rel_path, size in results:
                if rel_path:
                    self.all_files_stats[rel_path] = size
                    self.total_size_bytes += size

    def _process_single_file(
            self,
            file_path: str,
            target_extensions: Optional[Set[str]] = None,
            get_all_files: bool = False
    ) -> Tuple[Optional[str], str, int]:
        """
        文件处理核心方法

        :return: (扩展名, 相对路径, 文件大小)
                 当get_all_files=True时，扩展名返回None
                 当文件无效时返回(None, "", 0)
        """
        try:
            if not isfile(file_path):
                return None, "", 0

            rel_path = self._get_relative_path(file_path)
            size = os.path.getsize(file_path)

            if get_all_files:
                return None, rel_path, size

            if target_extensions:
                file_ext = splitext(file_path)[1]
                if file_ext in target_extensions:
                    return file_ext, rel_path, size

            return None, "", 0

        except (OSError, PermissionError):
            return None, "", 0

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
        return {
            ext: {
                "files": data["files"],
                "total_size_bytes": data["total_size"],
                "total_size_human": self.format_size(data["total_size"])
            }
            for ext, data in self.ext_stats.items()
        }

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
