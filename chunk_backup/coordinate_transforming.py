class region_pos:
    def coordinate_transforming(pos: tuple, radius_size: int = None):

        #chunkpos[x1,z1,x2,z2]
        chunk_pos = []
        region_chunk_dict = {}
        if radius_size is None:
            # 提取两个坐标点的 x 和 z 值
            #x1, z1 = pos[0][0] // 16, pos[0][1] // 16
            #x2, z2 = pos[1][0] // 16, pos[1][1] // 16

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

#print(region_pos.coordinate_transforming(((14, -111), (1, -98))))
#print(region_pos.coordinate_transforming((10, -107), 0))
#print(region_pos.coordinate_transforming(((-2, -2),(509,509))))