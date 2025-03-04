import os
import struct
import zlib
import time
from collections import defaultdict


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
    """从空闲扇区中分配空间，返回写入位置的字节偏移量"""
    # 优先选择第一个足够大的空闲区域
    for i, (start_sector, count) in enumerate(free_sectors):
        if count >= required_sectors:
            # 更新空闲扇区列表
            remaining = count - required_sectors
            if remaining > 0:
                free_sectors[i] = (start_sector + required_sectors, remaining)
            else:
                del free_sectors[i]
            return start_sector * 4096

    # 无合适空闲区域，追加到文件末尾
    file_handle.seek(0, os.SEEK_END)
    end_position = file_handle.tell()
    aligned_position = ((end_position + 4095) // 4096) * 4096
    return aligned_position


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


def merge_region_file(source_region_path, target_region_path, overwrite=False):
    """
    将源区域文件中的所有有效区块合并到目标区域文件
    - overwrite: 是否覆盖目标区域中已存在的区块
    """
    if not os.path.exists(source_region_path):
        raise FileNotFoundError(f"源区域文件不存在: {source_region_path}")

    # 读取源数据
    try:
        source_chunks = read_region_metadata(source_region_path)
    except Exception as e:
        print(f"读取源区域文件失败: {e}")
        return

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

            # 检查目标位置是否已有数据
            target_f.seek(4 * offset_index)
            existing_offset = struct.unpack('>I', target_f.read(4))[0]
            existing_sectors = existing_offset & 0xFF

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


def scan_free_sectors(region_path):
    """更健壮的空闲扇区扫描"""
    try:
        file_size = os.path.getsize(region_path)
        if file_size % 4096 != 0:
            print(f"警告: 区域文件 {os.path.basename(region_path)} 大小异常")

        total_sectors = file_size // 4096
        used_sectors = set()

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

                used_sectors.update(range(sector_start, sector_start + sector_count))

        # 计算空闲区域
        free_sectors = []
        current_start = 2  # 前2扇区为头部
        for sector in range(2, total_sectors):
            if sector in used_sectors:
                if current_start < sector:
                    free_sectors.append((current_start, sector - current_start))
                current_start = sector + 1
        if current_start < total_sectors:
            free_sectors.append((current_start, total_sectors - current_start))

        return free_sectors
    except Exception as e:
        print(f"扫描空闲扇区失败: {e}")
        return []


# 将区域文件里某些区块导入到一个新区域文件中

chunk_list = [(0, -7), (1, -8)]
export_grouped_regions(
    input_region_dir=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region",
    chunk_list=chunk_list,
    output_dir=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region\test"
)

time.sleep(3)


# 将导出的 r.0.-1.mca 合并回原世界

merge_region_file(
    source_region_path=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region\test\r.0.-1.mca",
    target_region_path=r"E:\生电端\.minecraft\versions\1.18.2-Fabric 0.14.9\saves\新的世界 (2)\region\r.0.-1.mca",
    overwrite=True
)

