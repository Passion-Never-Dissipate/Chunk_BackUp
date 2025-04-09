from mcdreforged.api.utils.serializer import Serializable
from typing import Dict


class cb_info(Serializable):
    time: str = ""
    backup_type: str = ""
    user: str = ""
    backup_dimension: list = []
    comment: str = ""
    command: str = ""
    version_created: str = "1.3.0"
    minecraft_version: str = ""


class cb_custom_info(Serializable):
    time_created: str = ""
    time: str = ""
    custom_name: str = ""
    user_created: str = ""
    user: str = ""
    backup_type: str = "custom"
    backup_dimension: list = []
    version_created: str = "1.3.0"
    version_saved: str = "1.3.0"
    minecraft_version: str = ""
    sub_slot: dict = {}


class sub_slot_info(Serializable):
    time_created: str = ""
    backup_type: str = ""
    backup_dimension: str = ""
    user_created: str = ""
    chunk_top_left_pos: list = []
    chunk_bottom_right_pos: list = []
    """backup_range: str = """""
    command: str = ""
    comment: str = ""
    version_created: str = "1.3.0"


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
    data_getter: Dict[str, str] = {
        "get_pos": "data get entity {name} Pos",
        "get_dimension": "data get entity {name} Dimension",
        "save_worlds": "save-all flush",
        "auto_save_off": "save-off",
        "auto_save_on": "save-on",
        "get_pos_regex": r'^{name} has the following entity data: \[(?P<x>-?[\d.]+)d, (?P<y>-?[\d.]+)d, (?P<z>-?[\d.]+)d\]$',
        "get_dimension_regex": r'^{name} has the following entity data: "(?P<dimension>[^"]+)"$',
        "save_off_regex": "Automatic saving is now disabled",
        "saved_world_regex": "Saved the game"
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
        "set": 2,
        "custom": 1
    }
    slot: int = 10
    static_slot: int = 50
    max_chunk_length: int = 320
    max_workers = 4
    plugin_version: str = "1.3.0"
