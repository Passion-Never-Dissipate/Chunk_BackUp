import concurrent.futures
import json
import os
from os import DirEntry
from mcdreforged.api.types import ServerInterface
from collections import defaultdict
from os.path import splitext, join, relpath, abspath, isdir, isfile
from typing import Dict, Optional, Union, Set, Generator
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


class DictReindexer:
    def __init__(self, original_dict):
        self.data = original_dict.copy()
        self.original_keys = list(original_dict.keys())

    def reindex_keys(self):
        """将字典键重排序为连续整数序列"""
        values = list(self.data.values())
        self.data = {i + 1: values[i] for i in range(len(values))}
        return self.data

    def is_ordered_correctly(self):
        """检查是否符合 {1:v1, 2:v2...} 的键规律"""
        current_keys = list(self.data.keys())
        expected_keys = list(range(1, len(self.data) + 1))
        return current_keys == expected_keys

    def insert_value(self, new_value):
        """插入新值到排序后的字典末尾"""
        if not self.is_ordered_correctly():
            self.reindex_keys()
        new_key = len(self.data) + 1
        self.data[new_key] = new_value
        return self.data

    def get_current_dict(self):
        return self.data.copy()


class LazyFileAnalyzer:
    def __init__(self, target_dir: str):
        """
        惰性文件分析器

        :param target_dir: 要分析的目录路径
        """
        self.target_dir = abspath(target_dir)
        self._validate_directory()

    def _validate_directory(self) -> None:
        """验证目标目录是否存在且可访问"""
        if not isdir(self.target_dir):
            raise NotADirectoryError(f"目录不存在或不可访问: {self.target_dir}")
        if not os.access(self.target_dir, os.R_OK):
            raise PermissionError(f"无读取权限: {self.target_dir}")

    def _file_generator(self, include_subdirs: bool) -> Generator[str, None, None]:
        """生成器：按需产生文件路径"""
        if include_subdirs:
            for root, _, files in os.walk(self.target_dir):
                for file in files:
                    file_path = join(root, file)
                    if isfile(file_path):
                        yield file_path
        else:
            for entry in os.scandir(self.target_dir):
                entry: DirEntry
                if entry.is_file():
                    yield entry.path

    def is_empty(
            self,
            extensions: Optional[Set[str]] = None,
            include_subdirs: bool = False
    ) -> bool:
        """
        检查目录是否包含指定类型的文件

        :param extensions: 需要过滤的扩展名集合（None表示所有文件）
        :param include_subdirs: 是否包含子目录中的文件
        :return:
            True - 没有符合条件的文件
            False - 存在至少一个符合条件的文件

        示例：
            is_empty()                 # 检查是否没有文件
            is_empty(extensions={".txt"}) # 检查是否没有txt文件
        """
        for file_path in self._file_generator(include_subdirs):
            file_ext = splitext(file_path)[1]

            # 当不指定扩展名 或 扩展名匹配时返回非空
            if extensions is None or file_ext in extensions:
                return False
        return True

    def get_extension_sizes(
            self,
            extensions: Set[str],
            include_subdirs: bool = False,
            use_concurrency: bool = False
    ) -> Dict[str, int]:
        """
        获取指定扩展名的总大小（不记录文件路径）

        :param extensions: 需要统计的扩展名集合（例如 {".txt", ".jpg"}）
        :param include_subdirs: 是否包含子目录
        :param use_concurrency: 是否使用并发处理
        :return: 扩展名到总大小的映射字典
        """
        ext_sizes = {ext: 0 for ext in extensions}

        def process_file(file_path: str) -> Optional[tuple]:
            if not isfile(file_path):
                return None
            file_ext = splitext(file_path)[1]
            if file_ext in extensions:
                try:
                    return file_ext, os.path.getsize(file_path)
                except OSError:
                    pass
            return None

        if use_concurrency:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(process_file, fp)
                    for fp in self._file_generator(include_subdirs)
                ]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result:
                        ext, size = result
                        ext_sizes[ext] += size
        else:
            for file_path in self._file_generator(include_subdirs):
                result = process_file(file_path)
                if result:
                    ext, size = result
                    ext_sizes[ext] += size

        return {k: v for k, v in ext_sizes.items() if v > 0}

    def get_total_size(
            self,
            include_subdirs: bool = False,
            use_concurrency: bool = False
    ) -> int:
        """
        获取目录总大小

        :param include_subdirs: 是否包含子目录
        :param use_concurrency: 是否使用并发处理
        :return: 总字节数
        """
        total_size = 0

        def process_file(file_path: str) -> Optional[int]:
            try:
                return os.path.getsize(file_path) if isfile(file_path) else None
            except OSError:
                return None

        if use_concurrency:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(process_file, fp)
                    for fp in self._file_generator(include_subdirs)
                ]
                for future in concurrent.futures.as_completed(futures):
                    size = future.result()
                    if size:
                        total_size += size
        else:
            for file_path in self._file_generator(include_subdirs):
                size = process_file(file_path)
                if size:
                    total_size += size

        return total_size

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """将字节数转换为易读格式（按需调用）"""
        units = ("B", "KB", "MB", "GB", "TB")
        unit_idx = 0
        while size_bytes >= 1024 and unit_idx < len(units) - 1:
            size_bytes /= 1024.0
            unit_idx += 1
        return f"{size_bytes:.2f}{units[unit_idx]}"

    def get_file_list(
            self,
            extensions: Optional[Set[str]] = None,
            include_subdirs: bool = False,
            include_size: bool = False
    ) -> Dict[str, Union[Dict[str, int], Set[str]]]:
        """
        获取按扩展名分类的文件列表（路径集合或路径-大小字典）

        :param extensions: 过滤扩展名集合（None表示所有文件）
        :param include_subdirs: 是否包含子目录
        :param include_size: 是否包含文件大小
        :return: 按扩展名分组的字典，结构示例：
            include_size=True → {".pdf": {"documents/report.pdf": 1048576}, ...}
            include_size=False → {".pdf": {"documents/report.pdf"}, ...}
        """

        result = defaultdict(set if not include_size else dict)
        ext_filter = {ext.lower() for ext in extensions} if extensions else None

        for file_path in self._file_generator(include_subdirs):
            if not isfile(file_path):
                continue

            rel_path = relpath(file_path, self.target_dir)
            file_ext = splitext(file_path)[1].lower()

            # 扩展名过滤（统一小写处理）
            if ext_filter and file_ext not in ext_filter:
                continue

            # 动态构建数据结构
            if include_size:
                try:
                    size = os.path.getsize(file_path)
                    result[file_ext][rel_path] = size  # type: ignore
                except OSError:
                    pass
            else:
                result[file_ext].add(rel_path)  # 使用集合存储路径

        return dict(result)
