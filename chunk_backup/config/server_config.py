import re
from typing import List, Dict

from mcdreforged.api.utils import Serializable
from chunk_backup.types.units import Duration


_LEGACY_DATA_GETTER_REGEX = {
    "crood_getter": re.compile('^{name} has the following entity data: \\[(?P<x>-?\\d*\\.?\\d+(?:[eE][-+]?\\d+)?)d, (?P<y>-?\\d*\\.?\\d+(?:[eE][-+]?\\d+)?)d, (?P<z>-?\\d*\\.?\\d+(?:[eE][-+]?\\d+)?)d\\]$'),
    "dimension_getter": re.compile('^{name} has the following entity data: \"(?P<dimension>[^\"]+)\"$')
}
_LEGACY_SAVED_WORLD_REGEX = [
    re.compile('Saved the game'),
    re.compile('Saved the world'),
]


class MinecraftServerCommands(Serializable):
    get_entity_data: str = 'data get entity {name} {path}'
    save_all_worlds: str = 'save-all flush'
    auto_save_off: str = 'save-off'
    auto_save_on: str = 'save-on'


class ServerConfig(Serializable):
    turn_off_auto_save: bool = True
    commands: MinecraftServerCommands = MinecraftServerCommands()
    data_getter_regex: Dict[str, re.Pattern] = {
        key: re.compile('^(?:System chat: )?' + pattern.pattern[1:])
        for key, pattern in _LEGACY_DATA_GETTER_REGEX.items()
    }
    saved_world_regex: List[re.Pattern] = [
        re.compile('(?:System chat: )?' + pattern.pattern)
        for pattern in _LEGACY_SAVED_WORLD_REGEX
    ]
    save_world_max_wait: Duration = Duration('10min')

    def upgrade_data_getter_regex(self) -> bool:
        """升级旧版默认正则，保留用户自定义的匹配规则。"""
        modified = False
        for key, legacy_pattern in _LEGACY_DATA_GETTER_REGEX.items():
            if self.data_getter_regex.get(key) == legacy_pattern:
                self.data_getter_regex[key] = re.compile('^(?:System chat: )?' + legacy_pattern.pattern[1:])
                modified = True
        return modified

    def upgrade_saved_world_regex(self) -> bool:
        """升级旧版默认保存提示正则，保留自定义规则和空列表。"""
        modified = False
        for index, pattern in enumerate(self.saved_world_regex):
            if pattern in _LEGACY_SAVED_WORLD_REGEX:
                self.saved_world_regex[index] = re.compile('(?:System chat: )?' + pattern.pattern)
                modified = True
        return modified
