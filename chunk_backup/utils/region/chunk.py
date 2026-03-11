import os
import struct
import shutil
import json
import traceback
import concurrent.futures
from pathlib import Path
from collections import defaultdict
from chunk_backup.utils.mcdr_utils import tr
from chunk_backup.config.config import Config
from chunk_backup.mcdr_globals import server
from chunk_backup.exceptions import FatalError
from chunk_backup.utils.region.chunk_selector import ChunkSelector


class Chunk:
    OVER_SIZE_THRESHOLD = 1020 * 1024  # 1020 KiB

    @classmethod
    def export_grouped_regions(cls, input_region_dir, output_dir, selector):
        """
        按区域分组导出区块数据，并生成索引文件（明确指示是否有外部区块）。
        """
        if not isinstance(selector, list):
            selectors = [selector]
        else:
            selectors = selector

        all_rects = []
        for sel in selectors:
            all_rects.extend(sel._rectangles)
        if not all_rects:
            return 0

        first_sel = selectors[0]
        combined_sel = ChunkSelector._from_rectangles(
            all_rects, first_sel.max_chunk_size, first_sel.ignore_size_limit
        )
        rect_index = combined_sel.to_index()  # 用于内部处理

        region_externals = defaultdict(list)
        total_size = 0

        def process_region(region_file, data):
            local_externals = []
            local_total = 0

            rectangles = data["rectangles"]
            rect_list = []
            if isinstance(rectangles, str):
                rx, rz = cls._parse_region_filename(rectangles)
                rect_list.append((rx * 32, rz * 32, rx * 32 + 31, rz * 32 + 31))
            else:
                for r in rectangles:
                    rect_list.append(r)

            input_path = os.path.join(input_region_dir, region_file)
            output_path = os.path.join(output_dir, region_file)

            chunks_needed = []
            for (min_x, min_z, max_x, max_z) in rect_list:
                for x in range(min_x, max_x + 1):
                    for z in range(min_z, max_z + 1):
                        chunks_needed.append((x, z))

            if not os.path.exists(input_path):
                # 源区域不存在，不创建任何文件，直接返回空数据
                return region_file, local_externals, 0

            if isinstance(rectangles, str) and len(rectangles) == len(rect_list):
                # 整个区域被选中，直接复制区域文件
                local_total += os.path.getsize(input_path)
                shutil.copy2(input_path, output_path)

                # 复制该区域的所有外部文件
                src_region_x, src_region_z = cls._parse_region_filename(region_file)
                _input, _output = Path(input_region_dir), Path(output_dir)

                for x, z in ChunkSelector.get_all_chunks_in_region(src_region_x, src_region_z):
                    input_mcc = _input / f"c.{x}.{z}.mcc"
                    if not input_mcc.exists():
                        continue
                    local_total += os.path.getsize(input_mcc)
                    output_mcc = _output / f"c.{x}.{z}.mcc"
                    shutil.copy2(input_mcc, output_mcc)
                    local_externals.append((x, z))
                return region_file, local_externals, local_total
            else:
                # 部分区域，逐个处理区块
                chunks_data = {}
                with open(input_path, 'rb') as src_f:
                    for chunk_x, chunk_z in chunks_needed:
                        data_chunk = cls._read_chunk_data(input_path, chunk_x, chunk_z, file_obj=src_f)
                        if isinstance(data_chunk, dict) and data_chunk.get("actual_compression"):
                            local_externals.append((chunk_x, chunk_z))
                        chunks_data[(chunk_x % 32, chunk_z % 32)] = data_chunk

                region_size, external_size = cls._create_region_file(output_path, chunks_data)
                local_total += region_size + external_size
                return region_file, local_externals, local_total

        try:
            max_workers = Config.max_workers if Config.max_workers > 0 else 4
        except Exception:
            max_workers = 4

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for region_file, data in rect_index.items():
                future = executor.submit(process_region, region_file, data)
                futures.append(future)

            for future in concurrent.futures.as_completed(futures):
                try:
                    region_file, ext_list, size = future.result()
                    region_externals[region_file].extend(ext_list)
                    total_size += size
                except Exception:
                    server.logger.error(tr("other.error.chunk.create_backup.process_region",
                                           region=region_file,
                                           path=os.path.join(input_region_dir, region_file),
                                           error=traceback.format_exc()))
                    raise FatalError

        # 构建索引文件：只包含外部区块信息，并明确指示是否有外部区块
        external_index = {}
        for region, coords in region_externals.items():
            if coords:
                external_index[region] = [f"{x},{z}" for x, z in coords]

        index_content = {
            "external_present": bool(external_index),
            "external": external_index
        }

        index_path = os.path.join(output_dir, "index.json")
        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(index_content, f, indent=2, ensure_ascii=False)
        except Exception:
            server.logger.error(tr("other.error.chunk.create_backup.write_index", error=traceback.format_exc()))
            raise FatalError

        return total_size

    @classmethod
    def merge_region_file(cls, source_region_dir, target_region_dir, selector):
        """
        从备份恢复区域文件，要求备份文件夹必须包含索引文件。
        """
        src_path = Path(source_region_dir)
        tgt_path = Path(target_region_dir)

        # 检查备份文件夹是否为空（没有任何 .mca 文件且没有 index.json）
        has_any_file = False
        if src_path.exists():
            for item in src_path.iterdir():
                if item.is_file() and (item.suffix == '.mca' or item.name == 'index.json'):
                    has_any_file = True
                    break
        if not has_any_file:
            server.logger.error(tr("other.error.chunk.restore_backup.empty_folder", path=str(src_path)))
            raise FatalError(restore=True)

        # 检查索引文件是否存在
        index_path = src_path / "index.json"
        if not index_path.exists():
            server.logger.error(tr("other.error.chunk.restore_backup.lack_index", path=str(src_path)))
            raise FatalError(restore=True)

        # 解析索引文件
        external_map = {}
        index_has_external = False
        try:
            with open(index_path, 'r', encoding='utf-8') as fp:
                index_content = json.load(fp)
            index_has_external = index_content.get("external_present", False)
            external_map = index_content.get("external", {})
        except Exception:
            server.logger.error(tr("other.error.chunk.restore_backup.index_error", path=str(index_path)))
            raise FatalError(restore=True)

        # 将外部映射转换为坐标列表（用于全区域复制）
        external_coords = []
        if index_has_external:
            for region, coord_strs in external_map.items():
                for cs in coord_strs:
                    x, z = map(int, cs.split(','))
                    external_coords.append((x, z))

        if not isinstance(selector, list):
            selectors = [selector]
        else:
            selectors = selector

        region_to_chunks = ChunkSelector.combine_and_group(selectors)

        def process_region(region_file, chunk_list):
            src_folder = src_path
            tgt_folder = tgt_path
            src_region = src_folder / region_file
            tgt_region = tgt_folder / region_file

            # ---------- 全区域选中 ----------
            if region_file == chunk_list:
                if src_region.exists():
                    # 备份区域文件存在，直接复制
                    shutil.copy2(src_region, tgt_region)
                    # 根据索引复制外部文件
                    if index_has_external and region_file in external_map:
                        for coord_str in external_map[region_file]:
                            x, z = map(int, coord_str.split(','))
                            input_mcc = src_folder / f"c.{x}.{z}.mcc"
                            if not input_mcc.exists():
                                server.logger.error(
                                    tr("other.error.chunk.restore_backup.no_mcc",
                                       x=x, z=z, mcc=f"c.{x}.{z}.mcc", path=input_mcc))
                                raise FatalError(restore=True)
                            output_mcc = tgt_folder / f"c.{x}.{z}.mcc"
                            shutil.copy2(input_mcc, output_mcc)
                else:
                    # 备份中无此区域文件 → 整个区域为空
                    if tgt_region.exists():
                        tgt_region.unlink()
                    # 删除该区域所有外部文件
                    rx, rz = cls._parse_region_filename(region_file)
                    for x, z in ChunkSelector.get_all_chunks_in_region(rx, rz):
                        mcc_path = tgt_folder / f"c.{x}.{z}.mcc"
                        if mcc_path.exists():
                            mcc_path.unlink()
                return

            # ---------- 部分区域选中 ----------
            # 生成所有需要恢复的区块坐标
            coords = []
            for (min_x, min_z, max_x, max_z) in chunk_list:
                for x in range(min_x, max_x + 1):
                    for z in range(min_z, max_z + 1):
                        coords.append((x, z))
            if not coords:
                return

            # 打开源文件（如果存在）
            src_f = None
            if src_region.exists():
                src_f = open(src_region, 'rb')
            tgt_f = None
            free_sectors = []
            try:
                # 如果目标文件已存在，打开并扫描空闲扇区
                if tgt_region.exists():
                    tgt_f = open(tgt_region, 'r+b')
                    free_sectors = cls._scan_free_sectors(tgt_region, file_obj=tgt_f)

                for x, z in coords:
                    # 从备份读取数据
                    if src_f is not None:
                        src_data = cls._read_chunk_data(src_region, x, z, file_obj=src_f)
                    else:
                        src_data = "empty"
                    if src_data is None:
                        src_data = "empty"

                    local_x = x % 32
                    local_z = z % 32
                    offset_index = local_x + local_z * 32

                    # 如果目标文件未打开且当前区块非空，则创建目标文件
                    if tgt_f is None and src_data != "empty":
                        if not tgt_region.exists():
                            cls.init_region_file(tgt_region)
                        tgt_f = open(tgt_region, 'r+b')
                        # 新文件，空闲扇区列表为空（只有头部）

                    if tgt_f is None:
                        # 区块为空且目标文件不存在，无需处理
                        continue

                    # 读取目标当前偏移
                    tgt_f.seek(4 * offset_index)
                    offset_data = tgt_f.read(4)
                    if len(offset_data) == 4:
                        tgt_offset = struct.unpack('>I', offset_data)[0]
                        tgt_sector_start = tgt_offset >> 8
                        tgt_sector_count = tgt_offset & 0xFF
                    else:
                        tgt_sector_start = tgt_sector_count = 0

                    if src_data == "empty":
                        # 置空区块
                        if tgt_sector_start != 0:
                            cls._free_sectors(free_sectors, tgt_sector_start, tgt_sector_count)
                        tgt_f.seek(4 * offset_index)
                        tgt_f.write(struct.pack('>I', 0))
                        tgt_f.seek(4096 + 4 * offset_index)
                        tgt_f.write(struct.pack('>I', 1))
                        # 删除可能的外部文件
                        mcc_path = tgt_folder / f"c.{x}.{z}.mcc"
                        if mcc_path.exists():
                            mcc_path.unlink()
                        continue

                    # 处理非空区块
                    if src_data.get("actual_compression"):
                        # 外部区块：写入 .mcc 文件
                        mcc_filename = f"c.{x}.{z}.mcc"
                        mcc_path = tgt_folder / mcc_filename
                        with open(mcc_path, 'wb') as mcc_f:
                            mcc_f.write(src_data['data'])
                        marker_data = struct.pack('>I', 1) + bytes([src_data['compression_type']])
                        required_sectors = (len(marker_data) + 4095) // 4096
                        data_to_write = marker_data
                    else:
                        # 普通区块
                        raw_data = (
                                struct.pack('>I', src_data["length"]) +
                                bytes([src_data['compression_type']]) +
                                src_data['data']
                        )
                        required_sectors = (len(raw_data) + 4095) // 4096
                        data_to_write = raw_data

                    # 写入数据到区域文件（分配逻辑与原代码相同）
                    if tgt_sector_start != 0 and required_sectors <= tgt_sector_count:
                        if required_sectors < tgt_sector_count:
                            release_start = tgt_sector_start + required_sectors
                            release_count = tgt_sector_count - required_sectors
                            cls._free_sectors(free_sectors, release_start, release_count)
                        write_pos = tgt_sector_start * 4096
                        tgt_f.seek(write_pos)
                        tgt_f.write(data_to_write.ljust(required_sectors * 4096, b'\x00'))
                        new_offset = (tgt_sector_start << 8) | required_sectors
                        tgt_f.seek(4 * offset_index)
                        tgt_f.write(struct.pack('>I', new_offset))
                        tgt_f.seek(4096 + 4 * offset_index)
                        tgt_f.write(struct.pack('>I', src_data.get('timestamp', 1)))
                    else:
                        if tgt_sector_start != 0:
                            cls._free_sectors(free_sectors, tgt_sector_start, tgt_sector_count)
                        write_pos = cls._allocate_space(free_sectors, required_sectors, tgt_f)
                        sector_start = write_pos // 4096
                        tgt_f.seek(write_pos)
                        tgt_f.write(data_to_write.ljust(required_sectors * 4096, b'\x00'))
                        new_offset = (sector_start << 8) | required_sectors
                        tgt_f.seek(4 * offset_index)
                        tgt_f.write(struct.pack('>I', new_offset))
                        tgt_f.seek(4096 + 4 * offset_index)
                        tgt_f.write(struct.pack('>I', src_data.get('timestamp', 1)))

            except Exception:
                server.logger.error(
                    tr("other.error.chunk.restore_backup.process_region", region=region_file, path=tgt_region,
                       error=traceback.format_exc()))
                raise FatalError(restore=True)
            finally:
                if src_f is not None:
                    src_f.close()
                if tgt_f is not None:
                    tgt_f.close()

        try:
            max_workers = Config.max_workers if Config.max_workers > 0 else 4
        except Exception:
            max_workers = 4

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for region_file, chunk_list in region_to_chunks.items():
                future = executor.submit(process_region, region_file, chunk_list)
                futures.append(future)

            for future in concurrent.futures.as_completed(futures):
                future.result()

    # ---------- 以下为原有辅助方法，未涉及空间优化，保持不变 ----------
    @classmethod
    def _create_region_file(cls, output_path, chunks_data):
        """通用创建方法，处理超大区块，返回 (区域文件大小, 外部文件总大小)"""
        # 解析区域坐标
        region_x, region_z = cls._parse_region_filename(output_path)

        header = bytearray(8192)
        data_sectors = bytearray()
        current_sector = 2
        external_total = 0  # 累计外部文件大小

        for (local_x, local_z), data in chunks_data.items():
            offset_index = 4 * (local_x + local_z * 32)
            timestamp_index = 4096 + 4 * (local_x + local_z * 32)
            if data in ("empty", None):
                header[offset_index:offset_index + 4] = b'\x00\x00\x00\x00'
                header[timestamp_index:timestamp_index + 4] = struct.pack('>I', 1)
            else:
                compression_type = data['compression_type']
                chunk_data = data['data']
                if data.get("actual_compression"):
                    # 超大区块，创建外部文件
                    global_x = region_x * 32 + local_x
                    global_z = region_z * 32 + local_z
                    mcc_filename = f"c.{global_x}.{global_z}.mcc"
                    mcc_path = os.path.join(os.path.dirname(output_path), mcc_filename)
                    with open(mcc_path, 'wb') as mcc_f:
                        mcc_f.write(chunk_data)
                    external_total += len(chunk_data)  # 累加外部文件大小

                    marker_data = struct.pack('>I', 1) + bytes([data['compression_type']])
                    sectors_needed = (len(marker_data) + 4095) // 4096
                    padded_marker = marker_data.ljust(sectors_needed * 4096, b'\x00')

                    offset_entry = (current_sector << 8) | sectors_needed
                    header[offset_index:offset_index + 4] = struct.pack('>I', offset_entry)
                    timestamp = data.get('timestamp', 1)
                    header[timestamp_index:timestamp_index + 4] = struct.pack('>I', timestamp)

                    data_sectors += padded_marker
                    current_sector += sectors_needed
                else:
                    # 正常区块
                    raw_data = (
                            struct.pack('>I', data["length"]) +
                            bytes([compression_type]) +
                            chunk_data
                    )
                    sectors_needed = (len(raw_data) + 4095) // 4096
                    padded_data = raw_data.ljust(sectors_needed * 4096, b'\x00')

                    timestamp = data.get('timestamp', 1)
                    offset_entry = (current_sector << 8) | sectors_needed
                    header[offset_index:offset_index + 4] = struct.pack('>I', offset_entry)
                    header[timestamp_index:timestamp_index + 4] = struct.pack('>I', timestamp)

                    data_sectors += padded_data
                    current_sector += sectors_needed

        with open(output_path, 'wb') as f:
            f.write(header)
            f.write(data_sectors)

        region_size = len(header) + len(data_sectors)
        return region_size, external_total

    @classmethod
    def _parse_region_filename(cls, region_filename):
        base = os.path.basename(region_filename)
        parts = base.split('.')
        if len(parts) == 4 and parts[0] == "r" and parts[3] == "mca":
            region_x = int(parts[1])
            region_z = int(parts[2])
            return region_x, region_z

    @classmethod
    def _read_chunk_data(cls, region_file_path, chunk_x, chunk_z, file_obj=None):
        """
        读取区块的原始压缩数据及时间戳，自动处理外部超大区块。
        如果提供了 file_obj，则使用该已打开的文件对象进行读取（不会关闭）。
        """
        local_x = chunk_x % 32
        local_z = chunk_z % 32
        offset_index = 4 * (local_x + local_z * 32)

        need_close = False
        if file_obj is None:
            f = open(region_file_path, 'rb')
            need_close = True
        else:
            f = file_obj

        # 读取偏移量
        f.seek(offset_index)
        offset_data = f.read(4)
        if len(offset_data) != 4:
            return None
        offset = struct.unpack('>I', offset_data)[0]
        sector_offset = offset >> 8
        num_sectors = offset & 0xFF
        if sector_offset == 0 or num_sectors == 0:
            return "empty"
        # 读取该区块的前5字节（长度和压缩类型）
        f.seek(sector_offset * 4096)
        length_data = f.read(4)
        if len(length_data) != 4:
            return None
        length = struct.unpack('>I', length_data)[0]
        compression_byte = f.read(1)
        if len(compression_byte) != 1:
            return None
        compression_type = compression_byte[0]
        # 检查是否为外部区块标记
        if length == 1 and (compression_type & 0x80):
            # 是外部区块，从 .mcc 文件读取
            actual_compression = compression_type & 0x7F
            mcc_filename = f"c.{chunk_x}.{chunk_z}.mcc"
            mcc_path = os.path.join(os.path.dirname(region_file_path), mcc_filename)
            if not os.path.exists(mcc_path):
                return None
            with open(mcc_path, 'rb') as mcc_f:
                compressed_data = mcc_f.read()
            # 读取时间戳
            f.seek(4096 + 4 * (local_x + local_z * 32))
            timestamp_data = f.read(4)
            timestamp = struct.unpack('>I', timestamp_data)[0] if len(timestamp_data) == 4 else 0
            return {
                'compression_type': compression_type,
                'actual_compression': actual_compression,
                'data': compressed_data,
                'timestamp': timestamp,
                'length': length
            }
        else:
            # 普通区块，继续读取数据
            if length < 1:
                return None
            compressed_data = f.read(length - 1)
            if len(compressed_data) != length - 1:
                return None
            # 读取时间戳
            f.seek(4096 + 4 * (local_x + local_z * 32))
            timestamp_data = f.read(4)
            timestamp = struct.unpack('>I', timestamp_data)[0] if len(timestamp_data) == 4 else 0
            if need_close:
                f.close()
            return {
                'compression_type': compression_type,
                'data': compressed_data,
                'timestamp': timestamp,
                'length': length
            }

    @classmethod
    def init_region_file(cls, file_path):
        """初始化一个空区域文件"""
        with open(file_path, 'wb') as f:
            f.write(b'\x00' * 4096)
            f.write(b'\x00' * 4096)

    @classmethod
    def _scan_free_sectors(cls, region_path, file_obj=None):
        """
        扫描目标区域文件的空闲扇区，返回按起始扇区排序的列表 [(start, size), ...]
        :param region_path: 文件路径（用于获取大小）
        :param file_obj: 可选，已打开的文件对象（用于读取头部）
        """
        file_size = os.path.getsize(region_path)
        total_sectors = (file_size + 4095) // 4096
        used_sectors = set()

        if file_obj is not None:
            # 使用传入的文件对象，保存当前位置
            saved_pos = file_obj.tell()
            file_obj.seek(0)
            f = file_obj
            need_close = False
        else:
            f = open(region_path, 'rb')
            need_close = True

        try:
            for i in range(1024):
                f.seek(i * 4)
                offset = struct.unpack('>I', f.read(4))[0]
                if offset == 0:
                    continue
                sector_start = offset >> 8
                sector_count = offset & 0xFF
                if sector_start + sector_count > total_sectors:
                    continue
                used_sectors.update(range(sector_start, sector_start + sector_count))
        finally:
            if need_close:
                f.close()
            elif file_obj is not None:
                # 恢复文件指针
                file_obj.seek(saved_pos)

        # 计算空闲区域（从扇区2开始，前2个扇区为头部）
        free_sectors = []
        current_start = 2
        for sector in range(2, total_sectors):
            if sector in used_sectors:
                if current_start < sector:
                    free_sectors.append((current_start, sector - current_start))
                current_start = sector + 1
        if current_start < total_sectors:
            free_sectors.append((current_start, total_sectors - current_start))

        return cls._merge_free_sectors(free_sectors)

    @staticmethod
    def _merge_free_sectors(free_sectors):
        """合并相邻的空闲扇区"""
        if not free_sectors:
            return []
        free_sectors.sort(key=lambda x: x[0])
        merged = []
        cur_start, cur_size = free_sectors[0]
        for start, size in free_sectors[1:]:
            if start <= cur_start + cur_size:
                cur_size = max(cur_size, start - cur_start + size)
            else:
                merged.append((cur_start, cur_size))
                cur_start, cur_size = start, size
        merged.append((cur_start, cur_size))
        return merged

    @classmethod
    def _allocate_space(cls, free_sectors, required_sectors, file_handle):
        """从空闲扇区中分配空间，若没有合适的则追加到文件末尾"""
        if free_sectors:
            # 寻找最佳匹配：大小最接近且足够大的空闲区域
            best_idx = -1
            best_waste = float('inf')
            for i, (start, size) in enumerate(free_sectors):
                if size >= required_sectors:
                    waste = size - required_sectors
                    if waste < best_waste:
                        best_idx = i
                        best_waste = waste
            if best_idx != -1:
                start, size = free_sectors.pop(best_idx)
                if size > required_sectors:
                    free_sectors.append((start + required_sectors, size - required_sectors))
                return start * 4096

        # 无合适空闲区域，追加到文件末尾
        file_handle.seek(0, os.SEEK_END)
        file_end = file_handle.tell()
        if file_end % 4096 != 0:
            file_handle.write(b'\x00' * (4096 - file_end % 4096))
            file_end = file_handle.tell()
        new_pos = file_end
        # 扩展文件以容纳新数据
        file_handle.truncate(new_pos + required_sectors * 4096)
        return new_pos

    @classmethod
    def _free_sectors(cls, free_sectors, start, count):
        """将一段扇区加入空闲列表，并合并相邻的空闲区域"""
        free_sectors.append((start, count))
        # 重新排序合并
        merged = cls._merge_free_sectors(free_sectors)
        # 清空原列表并更新
        free_sectors.clear()
        free_sectors.extend(merged)
