import os
import struct
import time
from collections import defaultdict


def parse_region_filename(region_filename):
    """
    解析区域文件名，返回区域坐标 (region_x, region_z)
    例如：r.-1.-1.mca 返回 (-1, -1)
    """
    base = os.path.basename(region_filename)
    parts = base.split('.')
    if len(parts) >= 4:
        try:
            region_x = int(parts[1])
            region_z = int(parts[2])
            return region_x, region_z
        except ValueError:
            pass
    raise ValueError(f"无法解析区域文件名: {region_filename}")


def group_chunks_by_region(chunk_list):
    """将区块坐标按所属区域文件分组"""
    region_groups = defaultdict(list)
    for chunk_x, chunk_z in chunk_list:
        region_x = chunk_x // 32
        region_z = chunk_z // 32
        region_file = f"r.{region_x}.{region_z}.mca"
        region_groups[region_file].append((chunk_x, chunk_z))
    return region_groups


def read_chunk_data(region_file_path, chunk_x, chunk_z):
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

            # 读取原始数据
            f.seek(sector_offset * 4096)
            length = struct.unpack('>I', f.read(4))[0]
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
        print(f"读取区块 ({chunk_x}, {chunk_z}) 失败: {e}")
        return None


def init_region_file(file_path):
    """初始化一个空区域文件（填充8KB头部）"""
    with open(file_path, 'wb') as f:
        f.write(b'\x00' * 8192)


def allocate_space(free_sectors, required_sectors, file_handle):
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


def create_region_file(output_path, chunks_data):
    header = bytearray(8192)  # 偏移表 + 时间戳表
    data_sectors = bytearray()
    current_sector = 2  # 数据从第2个扇区开始

    for local_z in range(32):  # 先遍历 z
        for local_x in range(32):  # 再遍历 x
            chunk_key = (local_x, local_z)
            if chunk_key not in chunks_data:
                continue

            chunk = chunks_data[chunk_key]
            raw_data = (
                    struct.pack('>I', len(chunk['data']) + 1) +
                    bytes([chunk['compression_type']]) +
                    chunk['data']
            )
            sectors_needed = (len(raw_data) + 4095) // 4096
            padded_data = raw_data.ljust(sectors_needed * 4096, b'\x00')

            offset_index = 4 * (local_x + local_z * 32)
            offset_entry = (current_sector << 8) | sectors_needed
            header[offset_index:offset_index + 4] = struct.pack('>I', offset_entry)

            timestamp_index = 4096 + 4 * (local_x + local_z * 32)
            header[timestamp_index:timestamp_index + 4] = struct.pack('>I', chunk['timestamp'])

            data_sectors += padded_data
            current_sector += sectors_needed

    with open(output_path, 'wb') as f:
        f.write(header)
        f.write(data_sectors)


def export_grouped_regions(input_region_dir, chunk_list, output_dir):
    """主函数：按区域分组导出"""
    # 1. 按区域分组
    region_groups = group_chunks_by_region(chunk_list)

    # 2. 处理每个区域
    for region_file, chunks in region_groups.items():
        input_path = os.path.join(input_region_dir, region_file)
        output_path = os.path.join(output_dir, region_file)
        chunks_data = {}

        # 3. 读取所有目标区块
        for chunk_x, chunk_z in chunks:
            local_x = chunk_x % 32
            local_z = chunk_z % 32
            data = read_chunk_data(input_path, chunk_x, chunk_z)
            if data:
                chunks_data[(local_x, local_z)] = data

        # 4. 生成新区域文件
        create_region_file(output_path, chunks_data)
        print(f"已生成精简区域文件: {output_path}")


def merge_region_file(source_region_path, target_region_path, overwrite=False, backup_path=None):
    """
    将源区域文件中的所有有效区块合并到目标区域文件中
    overwrite: 是否覆盖目标区域中已存在的区块
    backup_path: 如果提供，则将目标区域中被覆盖的区块备份到该路径生成的区域文件中
    """
    # 初始化关键变量
    region_x = None
    region_z = None
    backup_chunks = {}  # 始终初始化备份字典

    if not os.path.exists(source_region_path):
        raise FileNotFoundError(f"源区域文件不存在: {source_region_path}")

    # 读取源数据
    try:
        source_chunks = read_region_metadata(source_region_path)
    except Exception as e:
        print(f"读取源区域文件失败: {e}")
        return

    # 解析目标区域坐标（无论是否启用备份）
    try:
        region_x, region_z = parse_region_filename(target_region_path)
    except Exception as e:
        print(f"解析目标区域坐标失败: {e}")
        if backup_path:
            print("已禁用备份功能")
            backup_path = None

    # 如果需要备份则重新初始化字典
    if backup_path:
        backup_chunks = {}

    # 初始化目标文件
    if not os.path.exists(target_region_path):
        init_region_file(target_region_path)

    # 扫描目标文件空闲扇区
    try:
        free_sectors = scan_free_sectors(target_region_path)
    except Exception as e:
        print(f"扫描目标文件空闲扇区失败: {e}")
        return

    with open(target_region_path, 'r+b') as target_f:
        for chunk in source_chunks:
            if chunk['sector_count'] == 0:
                continue

            local_x = chunk['local_x']
            local_z = chunk['local_z']
            offset_index = local_x + local_z * 32

            # 读取目标文件对应位置的偏移表数据
            target_f.seek(4 * offset_index)
            existing_offset = struct.unpack('>I', target_f.read(4))[0]
            existing_sectors = existing_offset & 0xFF
            existing_start = existing_offset >> 8

            # 如果目标位置已有数据且允许覆盖，则先备份原数据
            if existing_sectors > 0 and overwrite and backup_path:
                # 验证区域坐标已正确解析
                if region_x is None or region_z is None:
                    print("无法备份：区域坐标解析失败")
                    continue

                # 根据目标区域文件名计算完整区块坐标
                full_chunk_x = region_x * 32 + local_x
                full_chunk_z = region_z * 32 + local_z

                # 读取备份数据
                backup_chunk = read_chunk_data(target_region_path, full_chunk_x, full_chunk_z)
                if backup_chunk:
                    backup_chunks[(local_x, local_z)] = backup_chunk

                # 扇区回收逻辑
                if existing_start >= 2:
                    free_sectors.append((existing_start, existing_sectors))
                    free_sectors.sort()
                    i = 0
                    while i < len(free_sectors) - 1:
                        curr_start, curr_size = free_sectors[i]
                        next_start, next_size = free_sectors[i + 1]
                        if curr_start + curr_size == next_start:
                            free_sectors[i] = (curr_start, curr_size + next_size)
                            del free_sectors[i + 1]
                        else:
                            i += 1

            # 如果目标位置已有数据且不覆盖，则跳过
            if existing_sectors > 0 and not overwrite:
                print(f"跳过已有区块 ({local_x}, {local_z})")
                continue

            # 分配写入位置
            write_position = allocate_space(free_sectors, chunk['sector_count'], target_f)

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
                print(f"写入区块 ({local_x}, {local_z}) 失败: {e}")

    # 生成备份文件（仅当有备份数据时）
    if backup_path and backup_chunks:
        create_region_file(backup_path, backup_chunks)
        print(f"备份区域文件已生成: {backup_path}")
    elif backup_path and not backup_chunks:
        print("警告：启用了备份功能但未找到可备份的区块")

    print("完成")


def read_region_metadata(region_path):
    chunks = []
    try:
        file_size = os.path.getsize(region_path)
        if file_size < 8192:
            print(f"错误: 文件 {region_path} 不是有效的区域文件（大小不足8192字节）")
            return chunks

        # 一次性读取整个头部数据
        with open(region_path, 'rb') as f:
            header = f.read(8192)

        # 遍历 1024 个条目
        for i in range(1024):
            offset_data = header[i * 4:(i + 1) * 4]
            if len(offset_data) != 4:
                print(f"警告: 偏移表条目 {i} 数据不完整，已跳过")
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
                    print(f"警告: 区块 ({i % 32}, {i // 32}) 扇区范围越界，已跳过")
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
        print(f"读取区域文件 {region_path} 失败: {e}")
        return []


def merge_free_sectors(free_sectors):
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


def scan_free_sectors(region_path):
    """空闲扇区扫描"""
    try:
        file_size = os.path.getsize(region_path)

        if file_size % 4096 != 0:
            print(f"警告: 区域文件 {os.path.basename(region_path)} 大小异常")

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
                    print(f"警告: 无效扇区范围 [{sector_start}-{sector_start + sector_count})")
                    continue

                if sector_start < 0 or sector_count <= 0:
                    print(f"无效扇区参数: start={sector_start}, count={sector_count}")
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

        return merge_free_sectors(free_sectors)

    except Exception as e:
        print(f"扫描空闲扇区失败: {e}")
        return []


# 将区域文件里某些区块导入到一个新区域文件中
for i in range(100):
    chunk_list = [(0, -1)]
    export_grouped_regions(
        input_region_dir=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region",
        chunk_list=chunk_list,
        output_dir=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region\test"
    )

    time.sleep(5)

    # 将导出的 r.0.-1.mca 合并回原世界

    merge_region_file(
        source_region_path=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region\test\r.0.-1.mca",
        target_region_path=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region\r.0.-1.mca",
        backup_path=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region\backup\r.0.-1.mca",
        overwrite=True
    )
