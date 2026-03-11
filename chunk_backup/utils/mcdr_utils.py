from abc import ABC
from typing import Union, Any, Optional
from chunk_backup import constants
from chunk_backup.utils.json_parser import Message as msg
from mcdreforged.api.types import ServerInterface, CommandSource, PlayerCommandSource, ConsoleCommandSource
from mcdreforged.api.rtext import RText, RTextList, RColor, RAction, RTextBase


def tr(key: str, *args, **kwargs) -> RTextBase:
    return ServerInterface.si().rtr(constants.PLUGIN_ID + '.' + key, *args, **kwargs)


def get_json_obj(key: str, *args, **kwargs) -> RTextBase:
    return msg.get_json_str(tr(key, *args, **kwargs).to_plain_text())


class TranslationContext(ABC):
    def __init__(self, base_key: str):
        self.__base_key = base_key

    def tr(self, key: str, *args, **kwargs) -> RTextBase:
        k = self.__base_key
        if len(key) > 0:
            k += '.' + key
        return tr(k, *args, **kwargs)

    def get_json_obj(self, key: str, *args, **kwargs) -> RTextList:
        without_id = kwargs.pop('without_id', False)
        if not without_id:
            return msg.get_json_str(self.tr(key, *args, **kwargs).to_plain_text())
        else:
            return msg.get_json_str(tr(key, *args, **kwargs).to_plain_text())

    @classmethod
    def merge_rtext_lists(cls, *args, separator: Optional[Union[str, RTextBase]] = "\n") -> RTextList:
        return msg.merge_rtext_lists(*args, separator=separator)


def mkcmd(s: str) -> str:
    from chunk_backup.config.config import Config
    cmd = '§7' + Config.get().command.prefix
    if len(s) > 0:
        cmd += ' ' + s + '§f'
    return cmd


def __make_message_prefix() -> RTextBase:
    return RTextList(RText('[CB]', RColor.yellow).h('Chunk Backup'), ' ')


def reply_message(source: CommandSource, msg: Union[str, RTextBase], *, with_prefix: bool = True):
    if with_prefix:
        msg = RTextList(__make_message_prefix(), msg)
    source.reply(msg)


def broadcast_message(msg: Union[str, RTextBase], *, with_prefix: bool = True):
    if with_prefix:
        msg = RTextList(__make_message_prefix(), msg)
    from chunk_backup import mcdr_globals
    mcdr_globals.server.broadcast(msg)

