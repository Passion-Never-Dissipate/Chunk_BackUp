import os
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from chunk_backup.exceptions import FatalError
from chunk_backup.mcdr_globals import server
from chunk_backup.utils.mcdr_utils import tr
from chunk_backup.types.backup_info import BackupInfo
from chunk_backup.utils.backup_utils import BackupFolderManager as Manager
from chunk_backup.utils.region.chunk import Chunk as chunk
from chunk_backup.config.config import Config


class Region:
    """
    区域（Region）处理类，提供静态方法用于导出和恢复 Minecraft 区域文件（.mca）。
    支持全量复制和选择性区块导出/合并。
    """

    @staticmethod
    def restore_regions(manager: Manager, backup_info: BackupInfo):
        """
        从备份槽位恢复区域文件到服务器世界目录。

        :param manager: BackupFolderManager 实例，提供路径配置信息
        :param backup_info: BackupInfo 对象，包含要恢复的备份元数据（如维度、选择器等）
        :return: 始终返回 True（若过程中发生异常，由上层捕获）
        """
        tasks = []  # 任务列表，每个元素为 (source, target, selector)

        # 确定备份源目录：如果是覆盖槽位（"overwrite"），则直接使用；否则为槽位路径
        backup_storage = Config.get().overwrite_storage if manager.backup_slot == Config.get().overwrite_storage else manager.region_storage / manager.backup_slot

        # 遍历每个维度
        for dimension in backup_info.dimension:
            # 从配置中获取该维度的世界名称和区域文件夹列表
            world_name = manager.config.backup.dimension[dimension]["world_name"]
            region_folder = manager.config.backup.dimension[dimension]["region_folder"]
            # 获取该维度对应的选择器（可能为 "all" 或 ChunkSelector 对象列表）
            selector = backup_info.selector[dimension]

            # 对每个区域文件夹创建恢复任务
            for folder in region_folder:
                source = manager.storage_root / backup_storage / world_name / folder  # 备份源路径
                target = manager.server_root / world_name / folder                   # 目标路径（世界目录）
                tasks.append((source, target, selector))

        # 使用线程池并发处理恢复任务，最大并发数设为2（可调整）
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            for source, target, selector in tasks:
                # 确保目标目录存在（主线程中预先创建）
                os.makedirs(target, exist_ok=True)

                # 根据选择器类型提交不同任务
                if selector[0] == "all":
                    # 全量复制：先检查源目录是否存在且包含索引文件
                    if not source.exists():
                        server.logger.error(tr("other.error.chunk.restore_backup.no_backup", path=str(source)))
                        raise FatalError(restore=True)
                    index_path = source / "index.json"
                    if not index_path.exists():
                        server.logger.error(tr("other.error.chunk.restore_backup.lack_index", path=index_path))
                        raise FatalError(restore=True)

                    futures.append(
                        executor.submit(
                            Region.safe_copytree,
                            source,
                            target,
                            exclude=['index.json']  # 恢复时排除索引文件
                        )
                    )
                else:
                    # 选择性合并：由 chunk.merge_region_file 内部处理索引检查
                    futures.append(
                        executor.submit(
                            chunk.merge_region_file,
                            source,
                            target,
                            selector
                        )
                    )

            # 等待所有任务完成，并获取结果（若任务失败，future.result() 会抛出异常，由上层处理）
            for future in as_completed(futures):
                future.result()

        return True

    @staticmethod
    def export_regions(manager: Manager, backup_info: BackupInfo, is_overwrite=False):
        """
        将世界区域文件导出到备份槽位。

        :param manager: BackupFolderManager 实例
        :param backup_info: 可以是字典（包含 'dimension', 'selector' 等键）或 BackupInfo 对象
        :param is_overwrite: 是否为覆盖备份（即写入 "overwrite" 目录，而非常规槽位）
        :return: 无返回值，但会修改 info 对象，添加 'total_size' 字段（如果是字典）或设置 total_size 属性（如果是 BackupInfo）
        """
        tasks = []
        total_size = 0

        backup_slot = Config.get().overwrite_storage if is_overwrite else manager.region_storage / manager.backup_slot

        # 设置 backup_path
        backup_info.backup_path = manager.storage_root / backup_slot

        dimensions = backup_info.dimension
        selector = backup_info.selector

        for dimension in dimensions:
            world_name = manager.config.backup.dimension[dimension]["world_name"]
            region_folder = manager.config.backup.dimension[dimension]["region_folder"]

            _selector = selector[dimension]

            for folder in region_folder:
                source = manager.server_root / world_name / folder
                target = manager.storage_root / backup_slot / world_name / folder

                tasks.append((source, target, _selector))

        # 使用线程池并发导出，最大并发数2
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            for source, target, selector in tasks:
                # 确保目标目录存在
                os.makedirs(target, exist_ok=True)

                # 根据选择器类型提交不同任务
                if selector[0] == "all":
                    # 全量复制目录（备份时包含所有文件，不需要排除）
                    os.makedirs(source, exist_ok=True)
                    future = executor.submit(
                        Region.safe_copytree,
                        source,
                        target,
                        exclude=None  # 备份时复制所有文件，包括之后要创建的索引
                    )
                    # 在 future 完成后，需要在目标目录创建索引文件
                    futures.append((future, target))
                else:
                    # 按选择器分组导出区块（内部会生成 index.json）
                    futures.append(
                        (executor.submit(
                            chunk.export_grouped_regions,
                            source,
                            target,
                            selector
                        ), None)
                    )

            # 收集各任务返回的大小，累加到 total_size，并创建索引
            for future, target_dir in futures:
                size = future.result()
                total_size += size
                if target_dir is not None:
                    # 全量复制任务：在目标目录创建 index.json
                    index_path = target_dir / "index.json"
                    with open(index_path, 'w', encoding='utf-8') as f:
                        json.dump({"type": "region"}, f)

        # 将总大小写回 info 对象
        backup_info.total_size = total_size

    @staticmethod
    def safe_copytree(source, target, exclude=None):
        """
        使用线程池并发复制目录树，并统计总大小。
        若源目录为空，则删除目标目录并重新创建空目录。

        :param source: 源目录路径
        :param target: 目标目录路径
        :param exclude: 可选，需要排除的文件名列表（如 ['index.json']）
        :return: 复制的总字节数
        """
        # 确保目标目录存在
        os.makedirs(target, exist_ok=True)

        # 从配置中获取最大工作线程数，若失败则默认4
        try:
            max_workers = Config.max_workers if Config.max_workers > 0 else 4
        except Exception:
            max_workers = 4

        copy_tasks = []  # 收集所有待复制任务

        # 使用 scandir 高效遍历源目录
        with os.scandir(source) as entries:
            for entry in entries:
                # 如果指定了排除列表且当前文件名在排除列表中，则跳过
                if exclude and entry.name in exclude:
                    continue

                src_path = entry.path
                dst_path = os.path.join(target, entry.name)

                if entry.is_dir(follow_symlinks=False):
                    # 子目录：标记为目录任务，递归处理（递归时同样传递 exclude 参数）
                    copy_tasks.append((src_path, dst_path, True))
                elif entry.is_file(follow_symlinks=False):
                    # 文件：记录文件任务，同时记录文件大小
                    copy_tasks.append((src_path, dst_path, False, entry.stat().st_size))

        # 如果源目录为空（或所有文件都被排除），则清空目标目录并返回0
        if not copy_tasks:
            shutil.rmtree(target)
            os.makedirs(target)
            return 0

        total_size = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {}
            for task in copy_tasks:
                if task[2]:  # 目录任务
                    src, dst, _ = task
                    # 递归调用时传递相同的 exclude 参数
                    future = executor.submit(Region.safe_copytree, src, dst, exclude)
                else:         # 文件任务
                    src, dst, _, size = task
                    future = executor.submit(shutil.copy2, src, dst)
                # 将 future 映射到 (src, dst, size)，便于在完成后获取信息
                future_to_task[future] = (src, dst, size if not task[2] else None)

            # 处理完成的任务，累加大小
            for future in as_completed(future_to_task):
                src, dst, size = future_to_task[future]
                if size is None:
                    # 目录任务：递归返回的大小
                    total_size += future.result()
                else:
                    # 文件任务：累加记录的文件大小
                    total_size += size

        return total_size
