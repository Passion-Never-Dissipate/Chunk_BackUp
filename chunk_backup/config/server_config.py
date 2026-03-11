import re
from typing import List, Dict

from mcdreforged.api.utils import Serializable
from chunk_backup.types.units import Duration


class MinecraftServerCommands(Serializable):
    get_entity_data: str = 'data get entity {name} {path}'
    save_all_worlds: str = 'save-all flush'
    auto_save_off: str = 'save-off'
    auto_save_on: str = 'save-on'


class ServerConfig(Serializable):
    turn_off_auto_save: bool = True
    commands: MinecraftServerCommands = MinecraftServerCommands()
    data_getter_regex: Dict[str, re.Pattern] = {
        "crood_getter": re.compile('^{name} has the following entity data: \\[(?P<x>-?\\d*\\.?\\d+(?:[eE][-+]?\\d+)?)d, (?P<y>-?\\d*\\.?\\d+(?:[eE][-+]?\\d+)?)d, (?P<z>-?\\d*\\.?\\d+(?:[eE][-+]?\\d+)?)d\\]$'),
        "dimension_getter": re.compile('^{name} has the following entity data: \"(?P<dimension>[^\"]+)\"$')
    }
    saved_world_regex: List[re.Pattern] = [
        re.compile('Saved the game'),
        re.compile('Saved the world'),
    ]
    save_world_max_wait: Duration = Duration('10min')
