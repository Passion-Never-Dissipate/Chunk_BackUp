import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from chunk_backup.log.log_info import LogTask
from chunk_backup.config.config import Config
from chunk_backup.mcdr_globals import server
from chunk_backup.utils.mcdr_utils import tr


class LogManager:
    """
    日志管理器类，负责管理任务日志文件的存储、清理和查询。
    维护一个固定大小的日志目录，每个任务对应一个 JSON 文件。
    """
    MAX_LOGS = 100  # 最大日志文件数量

    def __init__(self):
        """初始化日志管理器，创建日志存储目录。"""
        self.config = Config.get()
        self.storage_root = Path(self.config.storage_root)
        self.log_storage = self.storage_root / self.config.log_storage
        self._lock = threading.Lock()
        self.log_storage.mkdir(parents=True, exist_ok=True)

    def _list_log_files(self) -> list[Path]:
        """
        返回所有符合日志文件名格式的文件的 Path 列表，按时间戳升序排序（旧 → 新）。
        内部方法，不单独加锁，需在调用时由外层锁保护。
        """
        files = []
        for f in self.log_storage.glob("*.json"):
            if self.is_valid_log_file(f.name):
                files.append(f)
        # 按文件名中的时间戳排序（升序）
        files.sort(key=lambda p: self._extract_timestamp(p))
        return files

    @staticmethod
    def _extract_timestamp(file_path: Path) -> str:
        """
        从日志文件名中提取时间戳部分（YYYYMMDD_HHMMSS_ffffff）。
        文件名格式：<task>_YYYYMMDD_HHMMSS_ffffff.json
        使用正则匹配，若匹配失败返回空字符串。
        """
        match = re.search(r'_(\d{8}_\d{6}_\d{6})\.json$', file_path.name)
        return match.group(1) if match else ''

    def _cleanup(self):
        """
        清理超出数量限制的旧日志文件。
        按时间戳升序排序，删除最旧的文件直到数量不超过 MAX_LOGS。
        """
        with self._lock:
            files = self._list_log_files()
            if len(files) <= self.MAX_LOGS:
                return
            # 删除最旧的（列表前面的）文件
            for f in files[:-self.MAX_LOGS]:
                f.unlink(missing_ok=True)

    def get_log_files(self, start: int, end: int) -> list[str]:
        """
        获取从新到旧排序的第 start 到第 end 个日志文件名（包含两端）。
        仅返回符合格式的有效日志文件。
        :param start: 起始位置，正整数，1 表示最新文件。
        :param end: 结束位置，正整数，且 >= start。
        :return: 文件名列表，按从新到旧顺序。
        """
        if start <= 0 or end <= 0 or start > end:
            return []

        with self._lock:
            files = self._list_log_files()  # 已按时间戳升序（旧→新）
            # 反转得到新→旧顺序
            files.reverse()
            start_idx = start - 1
            end_idx = end
            selected = files[start_idx:end_idx]
            return [f.name for f in selected]

    def count_log_files(self) -> int:
        """
        返回当前日志文件夹中所有符合格式的日志文件数量。
        """
        with self._lock:
            return len(self._list_log_files())

    def get_latest_log(self) -> Optional[Path]:
        """
        返回最新（时间最晚）的日志文件路径。
        如果没有日志文件，返回 None。
        """
        with self._lock:
            files = self._list_log_files()
            if files:
                return files[-1]
            return None

    def get_latest_log_by_task(self, task_id: str) -> Optional[Path]:
        """
        根据任务ID返回最新的日志文件路径。
        :param task_id: 任务ID，即文件名中的 <task> 部分
        :return: 最新的日志文件 Path 对象，若无则返回 None
        """
        with self._lock:
            files = self._list_log_files()  # 已按时间戳升序排序（旧 → 新）
            # 过滤出以 task_id + '_' 开头的文件
            matched = [f for f in files if f.name.startswith(task_id + '_')]
            if matched:
                return matched[-1]  # 最后一个即最新
            return None

    def is_valid_log_file(self, filename: str) -> bool:
        """
        判断给定文件名是否是合法的日志文件名，并且该文件存在于日志目录中。
        合法日志文件名格式：<task>_YYYYMMDD_HHMMSS_ffffff.json
        :param filename: 文件名（不包含路径）
        :return: 如果文件名格式正确且文件存在，返回 True；否则返回 False。
        """
        pattern = re.compile(r'^(.+)_(\d{8}_\d{6}_\d{6})\.json$')
        if not pattern.match(filename):
            return False
        file_path = self.log_storage / filename
        return file_path.is_file()

    def task_logger(self, log_task: LogTask):
        """返回一个 TaskLogger 上下文管理器实例。"""
        return TaskLogger(self, log_task)


class TaskLogger:
    """
    任务日志上下文管理器，负责在任务生命周期内创建和更新对应的日志文件。
    使用 with 语句包装任务代码，自动处理日志的写入和状态更新。
    """

    def __init__(self, manager: LogManager, log_task: LogTask):
        self.manager = manager
        self.log_task = log_task
        self.file_path: Optional[Path] = None  # 当前任务对应的日志文件路径
        self._log_created = False  # 标记日志文件是否成功创建

    def _make_filepath(self, ts: str) -> Path:
        """根据时间戳生成日志文件完整路径。"""
        filename = f"{self.log_task.task}_{ts}.json"
        return self.manager.log_storage / filename

    def __enter__(self):
        """
        进入上下文时执行：生成时间戳、创建文件路径、写入初始日志内容（task_done = False）。
        若文件写入失败，仅记录错误，任务仍可继续执行。
        """
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S_%f")  # 用于文件名的紧凑格式
        self.file_path = self._make_filepath(ts)
        self.log_task.date = now.strftime("%Y-%m-%d %H:%M:%S")  # 用于日志内容的可读格式
        try:
            self.manager._cleanup()  # 先清理旧文件，保证数量不超限
            with open(self.file_path, 'w', encoding='utf-8') as f:
                dic = self.log_task.serialize()
                json.dump(dic, f, ensure_ascii=False, indent=4)
            self._log_created = True  # 标记创建成功
        except Exception:
            # 记录错误但不抛出，避免影响任务执行
            name = tr(f"task.{self.log_task.task}.name").to_plain_text()
            server.logger.error(tr("other.error.log_error", name=name).to_plain_text())
            # _log_created 保持 False
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        退出上下文时执行：
        - 如果任务成功且日志已创建，更新 task_done 或特定字段。
        - 如果任务失败且日志已创建，根据失败情况更新特定字段。
        任何文件操作异常仅记录，不抛出，避免干扰任务本身的错误处理。
        """
        if not self._log_created:
            return  # 日志未创建，直接返回，异常继续传播

        # 读取现有日志数据
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            name = tr(f"task.{self.log_task.task}.name").to_plain_text()
            server.logger.error(tr("other.error.log_error", name=name).to_plain_text())
            return  # 读取失败，无法更新，直接返回

        # 根据是否有异常决定更新策略
        if exc_type is None:
            # 任务成功
            if "pre_restore_done" in data and getattr(self.log_task, "pre_restore_done", None) is not None:
                # 针对 backup_restore 任务，标记两个阶段完成
                data["pre_backup_done"] = self.log_task.pre_backup_done
                data["pre_restore_done"] = self.log_task.pre_restore_done
            else:
                # 普通任务，标记完成
                data['task_done'] = True
                if "pre_backup_done" in data:
                    data["pre_backup_done"] = self.log_task.pre_backup_done
                data.pop("pre_restore_done", None)
        else:
            # 任务失败
            if "pre_backup_done" in data and hasattr(self.log_task, "pre_backup_done"):
                data["pre_backup_done"] = self.log_task.pre_backup_done
            if "pre_restore_done" in data and hasattr(self.log_task, "pre_restore_done"):
                # 如果预恢复状态为 None，表示未执行，删除该字段；否则标记为失败（False）
                if self.log_task.pre_restore_done is None:
                    data.pop("pre_restore_done", None)
                else:
                    data["pre_restore_done"] = self.log_task.pre_restore_done

        # 写回文件
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.manager._cleanup()

        except Exception:
            name = tr(f"task.{self.log_task.task}.name").to_plain_text()
            server.logger.error(tr("other.error.log_error", name=name).to_plain_text())
