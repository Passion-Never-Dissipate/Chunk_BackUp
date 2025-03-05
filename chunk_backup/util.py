import os

from glob import glob
from mcdreforged.plugin.si.server_interface import ServerInterface

from chunk_backup import cfg

server_path = cfg.server_path
dimension_info = cfg.dimension_info
file_formats = ["mca", "dat"]  # 可自定义扩展名


def check_dimension_info(dimension_info):
    seen = set()
    for value in dimension_info.values():
        dimension = value["dimension"]  # 假设 "dimension" 键必然存在
        if dimension in seen:
            return None  # 发现重复，立即返回
        seen.add(dimension)
    # 无重复时返回所有唯一值（或根据需求调整返回值）
    return list(seen)


def dimension_info_inversion():
    dimension_info_inversion = {}

    for key, value in dimension_info():
        dimension_info_inversion[value["dimension"]] = value
        dimension_info_inversion[value["dimension"]]["dimension"] = key


def get_files_size(path_list: list):
    file_data = {}

    for file_format in file_formats:
        unit_index = 0
        current_files_size = 0
        pattern = os.path.join(path, f"**/*.{file_format}")

        for path in path_list:
            all_files = glob.glob(pattern, recursive=True)

        for file in all_files:
            current_files_size += os.path.getsize(file)

        file_data[file_format] = {"number": len(all_files), "files_size": current_files_size}
class region_pos:
    def coordinate_transforming(pos: tuple, radius_size: int = None):

        #chunkpos[x1,z1,x2,z2]
        chunk_pos = []
        region_chunk_dict = {}
        if radius_size is None:
            # 提取两个坐标点的 x 和 z 值
            chunk_pos = [min(pos[0][0] // 16, pos[1][0] // 16),
                         min(pos[0][1] // 16, pos[1][1] // 16),
                         max(pos[0][0] // 16, pos[1][0] // 16),
                         max(pos[0][1] // 16, pos[1][1] // 16)]
        else:
            player_chunk_pos_x = pos[0] // 16
            player_chunk_pos_z = pos[1] // 16
            chunk_pos = [player_chunk_pos_x - radius_size, 
                         player_chunk_pos_z - radius_size, 
                         player_chunk_pos_x + radius_size, 
                         player_chunk_pos_z + radius_size]
            
        print(chunk_pos)
#        if chunk_pos[2] - chunk_pos[0] + 1 > 32 and chunk_pos[3] - chunk_pos[1] + 1 > 32:
        for chunk_x in range(chunk_pos[0], chunk_pos[2] + 1):
            for chunk_y in range(chunk_pos[1], chunk_pos[3] + 1):
                region_file_name = f"r.{chunk_x // 32}.{chunk_y // 32}.mca"
                region_chunk_dict.setdefault(region_file_name, []).append((chunk_x, chunk_y))
            if len(region_chunk_dict[region_file_name]) >= 1024:
                region_chunk_dict[region_file_name] = region_file_name

        return region_chunk_dict
    
def tr(key, *args):
    return ServerInterface.get_instance().tr(f"chunk_backup.{key}", *args)