import os
import struct
import shutil
import traceback
from chunk_backup.tools import tr
from mcdreforged.api.all import ServerInterface


class Chunk:

    @classmethod
    def export_grouped_regions(cls, input_region_dir, output_dir, region_groups):
        """按区域分组导出"""
        for region_file, chunks in region_groups.items():
            input_path = os.path.join(input_region_dir, region_file)
            output_path = os.path.join(output_dir, region_file.replace("mca", "region"))

            # 处理输入文件不存在的情况
            if not os.path.exists(input_path):
                # 全区域模式特殊处理
                if region_file == chunks:
                    # 直接创建空区域文件（8KB全0）
                    cls.init_region_file(os.path.join(output_dir, region_file))

                else:
                    # 创建包含指定空区块的文件
                    chunks_data = {
                        (chunk_x % 32, chunk_z % 32): None
                        for chunk_x, chunk_z in chunks
                    }
                    cls._create_region_file(output_path, chunks_data)

                continue

            if region_file == chunks:
                shutil.copy2(input_path, os.path.join(output_dir, region_file))
                continue

            chunks_data = {}
            for chunk_x, chunk_z in chunks:
                local_x = chunk_x % 32
                local_z = chunk_z % 32
                data = cls._read_chunk_data(input_path, chunk_x, chunk_z)
                # 显式记录所有选中的区块，数据不存在时标记为 None
                chunks_data[(local_x, local_z)] = data  # data 可能为 None

            cls._create_region_file(output_path, chunks_data)

        return True

    @classmethod
    def merge_region_file(cls, source_region_path, target_region_path, overwrite=False, backup_path=None):
        """
        将源区域文件中的所有有效区块合并到目标区域文件中
        overwrite: 是否覆盖目标区域中已存在的区块
        backup_path: 如果提供，则将目标区域中被覆盖的区块备份到该路径生成的区域文件中
        """
        backup_chunks = {}  # 始终初始化备份字典

        # 读取源数据
        try:
            source_chunks = cls._read_region_metadata(source_region_path)
        except Exception as e:
            ServerInterface.get_instance().logger.error(tr("error.region_error.read_source_region_fail", e))
            return

        # 解析目标区域坐标（无论是否启用备份）
        try:
            region_x, region_z = cls._parse_region_filename(target_region_path)
        except Exception as e:
            ServerInterface.get_instance().logger.error(tr("error.region_error.mca_pos_analyze_error", e))
            return

            # 如果需要备份则重新初始化字典
        if backup_path: backup_chunks = {}

        # 初始化目标文件
        if not os.path.exists(target_region_path):
            cls.init_region_file(target_region_path)

        # 扫描目标文件空闲扇区
        free_sectors = cls._scan_free_sectors(target_region_path)

        with open(target_region_path, 'r+b') as target_f:
            for chunk in source_chunks:

                local_x = chunk['local_x']
                local_z = chunk['local_z']
                offset_index = local_x + local_z * 32

                if chunk['timestamp'] == 0:
                    continue

                # 读取目标文件对应位置的偏移表数据
                """target_f.seek(4 * offset_index)
                offset_data = target_f.read(4)
                if len(offset_data) < 4:  # 处理不完整的偏移数据
                    existing_offset = 0
                else:
                    existing_offset = struct.unpack('>I', offset_data)[0]

                existing_sectors = existing_offset & 0xFF
                existing_start = existing_offset >> 8"""

                # ===== 新增备份逻辑 =====
                if backup_path:
                    full_x = region_x * 32 + local_x
                    full_z = region_z * 32 + local_z

                    # 读取目标区块数据（包含空状态）
                    target_chunk = cls._read_chunk_with_nullable(target_region_path, full_x, full_z)

                    backup_data = target_chunk if target_chunk else {'status': 'empty'}
                    backup_chunks[(local_x, local_z)] = backup_data

                if chunk['sector_count'] == 0:
                    if overwrite:
                        # 将目标区块设置为空
                        target_f.seek(4 * offset_index)
                        target_f.write(struct.pack('>I', 0))  # 设置偏移为0
                        target_f.seek(4096 + 4 * offset_index)
                        target_f.write(struct.pack('>I', chunk['timestamp']))  # 更新时间戳
                    continue  # 跳过后续数据写入步骤

                # 分配写入位置
                write_position = cls._allocate_space(free_sectors, chunk['sector_count'], target_f)

                # 写入数据并更新元数据
                try:
                    target_f.seek(write_position)
                    target_f.write(chunk['raw_data'])

                    # 更新偏移表
                    new_offset = (write_position // 4096 << 8) | chunk['sector_count']
                    target_f.seek(4 * offset_index)
                    target_f.write(struct.pack('>I', new_offset))

                    # 更新时间戳
                    target_f.seek(4096 + 4 * offset_index)
                    target_f.write(struct.pack('>I', chunk['timestamp']))
                except Exception as e:
                    ServerInterface.get_instance().logger.error("error.system_error.write_chunk_file_error", local_x,
                                                                local_z, e)

        if backup_path and backup_chunks:
            # 转换备份数据结构
            formatted_backup = {}
            for (lx, lz), data in backup_chunks.items():
                if data.get('status') == 'empty':
                    # 标记为需要显式清空
                    formatted_backup[(lx, lz)] = None
                elif data is not None:
                    # 正常区块数据
                    formatted_backup[(lx, lz)] = data

            # 创建备份文件
            if formatted_backup:
                cls._create_region_file(backup_path, formatted_backup)
            else:
                # 创建空文件表示无变更
                cls.init_region_file(backup_path)
        """elif backup_path and not backup_chunks:
            ServerInterface.get_instance().logger.error(tr("warn.not_select_abel_backup_chunk"))"""
        return True

    @classmethod
    def merge_custom_region_file(cls, source_region_path, target_region_path, chunk_list, overwrite=False,
                                 backup_path=None):
        """
        将源区域文件中指定区块列表的区块合并到目标区域文件中
        :param source_region_path: 源区域文件路径（.region）
        :param target_region_path: 目标区域文件路径（.mca）
        :param chunk_list: 需要合并的区块列表，如 [(chunk_x1, chunk_z1), ...]
        :param overwrite: 是否覆盖目标区域中已存在的区块
        :param backup_path: 备份被替换区块的路径（可选）
        :return: 操作是否成功
        """
        server = ServerInterface.get_instance()
        logger = server.logger
        success = True

        # 解析目标区域坐标（用于备份命名）
        try:
            region_x, region_z = cls._parse_region_filename(target_region_path)
        except Exception as e:
            logger.error(tr("error.region_error.mca_pos_analyze_error", e))
            return

        # 扫描目标文件空闲扇区
        free_sectors = cls._scan_free_sectors(target_region_path)

        # 初始化备份数据
        backup_chunks = {}
        if backup_path:
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)

        with open(target_region_path, 'r+b') as target_f:
            for chunk_x, chunk_z in chunk_list:
                # 读取源区块数据
                source_data = cls._read_chunk_data(source_region_path, chunk_x, chunk_z)

                # 计算本地坐标（local_x, local_z）
                local_x = chunk_x % 32
                local_z = chunk_z % 32
                offset_index = local_x + local_z * 32

                # ==== 备份逻辑 ====
                if backup_path:
                    full_x = region_x * 32 + local_x
                    full_z = region_z * 32 + local_z
                    target_data = cls._read_chunk_with_nullable(target_region_path, full_x, full_z)

                    backup_data = target_data if target_data else {'status': 'empty'}
                    backup_chunks[(local_x, local_z)] = backup_data

                # ==== 写入逻辑 ====
                if source_data is None:
                    # 源区块不存在，若需要覆盖则清空目标区块
                    if overwrite:
                        # 将目标区块偏移设为0
                        target_f.seek(4 * offset_index)
                        target_f.write(struct.pack('>I', 0))
                        # 更新时间戳为1（显式空区块）
                        target_f.seek(4096 + 4 * offset_index)
                        target_f.write(struct.pack('>I', 1))
                    continue

                # 分配空间
                """total_length = len(source_data['data']) + 5  # 4字节长度 +1字节压缩类型 +数据"""
                sector_count = (len(source_data['data']) + 5 + 4095) // 4096  # 正确向上取整

                # 分配空间
                write_position = cls._allocate_space(free_sectors, sector_count, target_f)

                # 构造原始数据（含长度和压缩类型）
                data_length = len(source_data['data']) + 1  # 压缩类型占1字节
                raw_data = (
                        struct.pack('>I', data_length) +
                        bytes([source_data['compression_type']]) +
                        source_data['data']
                ).ljust(sector_count * 4096, b'\x00')

                try:
                    # 写入数据
                    target_f.seek(write_position)
                    target_f.write(raw_data)

                    # 更新偏移表
                    new_offset = (write_position // 4096 << 8) | sector_count
                    target_f.seek(4 * offset_index)
                    target_f.write(struct.pack('>I', new_offset))

                    # 更新时间戳（使用源区块的时间戳）
                    timestamp = source_data.get('timestamp', 1)
                    target_f.seek(4096 + 4 * offset_index)
                    target_f.write(struct.pack('>I', timestamp))
                except Exception as e:
                    logger.error(tr("error.system_error.write_chunk_file_error", chunk_x, chunk_z, e))
                    success = False

        # ==== 生成备份文件 ====
        if backup_path and backup_chunks:
            formatted_backup = {}
            for (lx, lz), data in backup_chunks.items():
                if data.get('status') == 'empty':
                    formatted_backup[(lx, lz)] = None
                else:
                    formatted_backup[(lx, lz)] = data
            cls._create_region_file(backup_path, formatted_backup)

        return success

    @classmethod
    def custom_restore_direct(cls, backup_dir, original_dir, region_dict, backup_backup_dir=None):
        """
        直接合并模式的自定义回档
        :param backup_dir: 备份文件夹路径（包含 .region 文件）
        :param original_dir: 原版区域文件夹路径（包含 .mca 文件）
        :param region_dict: 区域配置字典，如 {"r.0.0.mca": [(0,1), (0,2)], ...}
        :param backup_backup_dir: 备份被替换区块的目录（可选）
        :return: 是否全部成功
        """
        server = ServerInterface.get_instance()
        logger = server.logger

        for region_file, chunks in region_dict.items():

            source_path = os.path.join(backup_dir, region_file.replace('.mca', '.region')) if region_file != chunks else os.path.join(backup_dir, region_file)
            target_path = os.path.join(original_dir, region_file)

            # 检查源文件是否存在
            if not os.path.exists(source_path):
                if os.path.exists(os.path.join(backup_dir, region_file)):
                    source_path = os.path.join(backup_dir, region_file)
                # logger.error(tr('error.custom_restore.backup_not_found', source_path))"
                else:
                    continue

            # 处理备份路径
            backup_path = None
            if backup_backup_dir:
                backup_file = region_file.replace('.mca', '.region') if region_file != chunks else region_file
                backup_path = os.path.join(backup_backup_dir, backup_file)

            if not os.path.exists(target_path):
                cls.init_region_file(target_path)

            # 执行合并
            try:
                if region_file == chunks:
                    if backup_backup_dir:
                        shutil.copy2(target_path, backup_path)
                    shutil.copy2(source_path, target_path)
                    continue
                cls.merge_custom_region_file(
                    source_region_path=source_path,
                    target_region_path=target_path,
                    chunk_list=chunks,
                    overwrite=True,
                    backup_path=backup_path
                )

            except Exception:
                logger.error(tr('error.unknown_error', traceback.format_exc()))

    @classmethod
    def _create_region_file(cls, output_path, chunks_data):
        """通用创建方法（兼容空文件生成）"""
        # 如果没有需要特殊处理的区块，直接创建空文件

        # 原有区块处理逻辑保持不变
        header = bytearray(8192)
        data_sectors = bytearray()
        current_sector = 2

        for (local_x, local_z), data in chunks_data.items():
            offset_index = 4 * (local_x + local_z * 32)
            timestamp_index = 4096 + 4 * (local_x + local_z * 32)
            if data is None:
                # 显式空区块：时间戳设为1
                header[offset_index:offset_index + 4] = b'\x00\x00\x00\x00'
                header[timestamp_index:timestamp_index + 4] = struct.pack('>I', 1)  # 显式空区块
            else:
                # 正常数据区块
                raw_data = (
                        struct.pack('>I', len(data['data']) + 1) +
                        bytes([data['compression_type']]) +
                        data['data']
                )
                sectors_needed = (len(raw_data) + 4095) // 4096
                padded_data = raw_data.ljust(sectors_needed * 4096, b'\x00')

                timestamp = data['timestamp'] if data['timestamp'] != 0 else 1
                offset_entry = (current_sector << 8) | sectors_needed

                header[offset_index:offset_index + 4] = struct.pack('>I', offset_entry)
                header[timestamp_index:timestamp_index + 4] = struct.pack('>I', timestamp)

                data_sectors += padded_data
                current_sector += sectors_needed

        with open(output_path, 'wb') as f:
            f.write(header)
            f.write(data_sectors)

    @classmethod
    def _parse_region_filename(cls, region_filename):
        """
        解析区域文件名，返回区域坐标 (region_x, region_z)
        例如：r.-1.-1.mca 返回 (-1, -1)
        """
        base = os.path.basename(region_filename)
        parts = base.split('.')
        if len(parts) == 4 and parts[0] == "r" and parts[3] in ("mca", "region"):
            try:
                region_x = int(parts[1])
                region_z = int(parts[2])
                return region_x, region_z
            except ValueError:
                pass
        raise ValueError(tr("error.mca_analyze_error", region_filename))

    @classmethod
    def _read_chunk_data(cls, region_file_path, chunk_x, chunk_z):
        """读取区块的原始压缩数据及时间戳（不解压）"""
        local_x = chunk_x % 32
        local_z = chunk_z % 32
        offset_index = 4 * (local_x + local_z * 32)

        try:
            with open(region_file_path, 'rb') as f:
                # 读取偏移量
                f.seek(offset_index)
                offset_data = f.read(4)
                if len(offset_data) != 4:
                    return None
                offset = struct.unpack('>I', offset_data)[0]
                sector_offset = offset >> 8
                num_sectors = offset & 0xFF

                if sector_offset == 0 or num_sectors == 0:
                    return None

                f.seek(sector_offset * 4096)
                length_data = f.read(4)
                if len(length_data) != 4:
                    return None

                length = struct.unpack('>I', length_data)[0]
                if length < 1:
                    return None

                compression_type = ord(f.read(1))
                compressed_data = f.read(length - 1)

                # 读取时间戳表
                f.seek(4096 + 4 * (local_x + local_z * 32))
                timestamp_data = f.read(4)
                timestamp = struct.unpack('>I', timestamp_data)[0] if len(timestamp_data) == 4 else 0

                return {
                    'compression_type': compression_type,
                    'data': compressed_data,
                    'timestamp': timestamp
                }
        except Exception as e:
            ServerInterface.get_instance().broadcast(
                tr("error.system_error.read_chunk_file_error", chunk_x, chunk_z, e))
            return None

    @classmethod
    def init_region_file(cls, file_path):
        """初始化一个空区域文件（严格合规的8KB头部）"""
        with open(file_path, 'wb') as f:
            # 前4096字节全0（偏移表）
            f.write(b'\x00' * 4096)
            # 后4096字节全0（时间戳表）
            f.write(b'\x00' * 4096)

    @classmethod
    def _allocate_space(cls, free_sectors, required_sectors, file_handle):
        """优先使用最合适的空闲区域"""
        if not free_sectors:
            # 追加到文件末尾
            file_handle.seek(0, os.SEEK_END)
            current_pos = file_handle.tell()
            aligned_pos = ((current_pos + 4095) // 4096) * 4096
            file_handle.truncate(aligned_pos + required_sectors * 4096)
            return aligned_pos

        # 寻找最小可用的空闲区域
        best_idx = -1
        min_waste = float('inf')
        for i, (start, size) in enumerate(free_sectors):
            if size >= required_sectors:
                waste = size - required_sectors
                if waste < min_waste:
                    best_idx = i
                    min_waste = waste

        if best_idx != -1:
            start, size = free_sectors.pop(best_idx)
            if size > required_sectors:
                # 分割剩余空间
                free_sectors.append((start + required_sectors, size - required_sectors))
            return start * 4096

        # 无合适区域则追加
        file_handle.seek(0, os.SEEK_END)
        current_pos = file_handle.tell()
        aligned_pos = ((current_pos + 4095) // 4096) * 4096
        file_handle.truncate(aligned_pos + required_sectors * 4096)
        return aligned_pos

    @classmethod
    def _read_region_metadata(cls, region_path):
        chunks = []
        try:
            file_size = os.path.getsize(region_path)
            if file_size < 8192:
                ServerInterface.get_instance().logger.error(tr("error.region_error.mca_unable", region_path))
                return chunks

            # 一次性读取整个头部数据
            with open(region_path, 'rb') as f:
                header = f.read(8192)

            # 遍历 1024 个条目
            for i in range(1024):
                offset_data = header[i * 4:(i + 1) * 4]
                if len(offset_data) != 4:
                    ServerInterface.get_instance().logger.warning(tr("warn.migration_incomplete", i))
                    offset = 0
                else:
                    offset = struct.unpack('>I', offset_data)[0]

                sector_offset = offset >> 8
                sector_count = offset & 0xFF

                timestamp_data = header[4096 + i * 4:4096 + (i + 1) * 4]
                timestamp = struct.unpack('>I', timestamp_data)[0] if len(timestamp_data) == 4 else 0

                # 检查扇区范围是否合法
                if sector_offset > 0:
                    max_sector = file_size // 4096
                    if sector_offset + sector_count > max_sector:
                        ServerInterface.get_instance().logger.warning(tr("warn.sector_out_of_bounds", i % 32, i // 32))
                        sector_count = 0
                        raw_data = b''
                    else:
                        # 此处单独打开文件读取数据，避免影响 header 的读取
                        with open(region_path, 'rb') as f:
                            f.seek(sector_offset * 4096)
                            raw_data = f.read(sector_count * 4096)
                else:
                    raw_data = b''

                chunks.append({
                    'local_x': i % 32,
                    'local_z': i // 32,
                    'sector_count': sector_count,
                    'timestamp': timestamp,
                    'raw_data': raw_data
                })

            return chunks
        except Exception as e:
            ServerInterface.get_instance().logger.error(tr("error.region_error.read_region_file_fail", region_path, e))
            return []

    @classmethod
    def _merge_free_sectors(cls, free_sectors):
        """完全合并相邻或重叠的空闲扇区"""
        if not free_sectors:
            return []

        # 按起始位置排序
        free_sectors.sort(key=lambda x: x[0])

        merged = []
        current_start, current_size = free_sectors[0]

        for start, size in free_sectors[1:]:
            if start <= current_start + current_size:
                # 合并重叠或相邻区域
                new_end = max(current_start + current_size, start + size)
                current_size = new_end - current_start
            else:
                merged.append((current_start, current_size))
                current_start, current_size = start, size

        merged.append((current_start, current_size))
        return merged

    @classmethod
    def _scan_free_sectors(cls, region_path):
        """空闲扇区扫描"""
        try:
            file_size = os.path.getsize(region_path)

            if file_size % 4096 != 0:
                ServerInterface.get_instance().logger.warning(tr("warn.mca_size_abnormal", region_path))

            total_sectors = (file_size + 4095) // 4096  # 正确对齐
            used_sectors: set[int] = set()  # type: ignore

            with open(region_path, 'rb') as f:
                # 标记已用扇区
                for i in range(1024):
                    f.seek(i * 4)
                    offset = struct.unpack('>I', f.read(4))[0]
                    if offset == 0:
                        continue

                    sector_start = offset >> 8
                    sector_count = offset & 0xFF
                    if sector_start + sector_count > total_sectors:
                        ServerInterface.get_instance().logger.error(
                            tr("warn.sector_range_invalid", sector_start, sector_start + sector_count))
                        continue

                    if sector_start < 0 or sector_count <= 0:
                        ServerInterface.get_instance().logger.error(
                            tr("error.system_error.invalid_sector_parameter", sector_start, sector_count))
                        continue

                    used_sectors.update(range(sector_start, sector_start + sector_count))

            # 计算空闲区域
            free_sectors = []
            current_start = 2  # 前2扇区为头部
            for sector in range(2, total_sectors):
                if sector in used_sectors:
                    if current_start < sector:
                        free_sectors.append((current_start, sector - current_start))
                    current_start = sector + 1

            last_used = max(used_sectors) if used_sectors else 1
            if last_used < total_sectors - 1:
                free_sectors.append((last_used + 1, total_sectors - last_used - 1))

            return cls._merge_free_sectors(free_sectors)

        except Exception as e:
            # ServerInterface.get_instance().logger.error(tr("error.system_error.scan_mca_leisure_error", e))
            return []

    @classmethod
    def _read_chunk_with_nullable(cls, region_path, chunk_x, chunk_z):
        """
        增强版区块读取方法，能识别空状态
        返回值：
        - None: 区块不存在
        - dict: 正常区块数据
        """
        local_x = chunk_x % 32
        local_z = chunk_z % 32

        try:
            with open(region_path, 'rb') as f:

                f.seek(4 * (local_x + local_z * 32))
                offset_data = f.read(4)
                if len(offset_data) != 4:
                    return None

                offset = struct.unpack('>I', offset_data)[0]
                if offset == 0:
                    # 明确标记空状态
                    return {'status': 'empty'}

                # 正常读取流程
                return cls._read_chunk_data(region_path, chunk_x, chunk_z)
        except FileNotFoundError:
            return {'status': 'empty'}  # 文件不存在视为全空
        except Exception as e:
            ServerInterface.get_instance().logger.error(tr("error.read_chunk_fail", chunk_x, chunk_z, e))
            # return None
