from mcdreforged.api.utils.serializer import Serializable
from typing import Dict


class cb_info(Serializable):
    time: str = ""
    backup_type: str = ""
    user: str = ""
    backup_dimension: list = []
    comment: str = ""
    command: str = ""
    version_created: str = "1.2.0"


class cb_config(Serializable):
    server_path: str = "./server"
    backup_path: str = "./cb_multi"
    static_backup_path: str = "./cb_static"
    overwrite_backup_folder: str = "overwrite"
    prefix: str = "!!cb"
    dimension_info: Dict[str, dict] = {
        "0": {"dimension": "minecraft:overworld",
              "world_name": "world",
              "region_folder": [
                  "poi",
                  "entities",
                  "region"
              ]
              },
        "-1": {"dimension": "minecraft:the_nether",
               "world_name": "world",
               "region_folder": [
                   "DIM-1/poi",
                   "DIM-1/entities",
                   "DIM-1/region"
               ]
               },
        "1": {"dimension": "minecraft:the_end",
              "world_name": "world",
              "region_folder": [
                  "DIM1/poi",
                  "DIM1/entities",
                  "DIM1/region"
              ]
              }
    }
    minimum_permission_level: Dict[str, int] = {
        "make": 1,
        "pmake": 1,
        "dmake": 1,
        "back": 2,
        "restore": 2,
        "del": 2,
        "confirm": 1,
        "abort": 1,
        "reload": 2,
        "force_reload": 3,
        "list": 0,
        "show": 1,
        "set": 2
    }
    slot: int = 10
    static_slot: int = 50
    max_chunk_length: int = 320
    plugin_version: str = "1.2.0"
