from typing import Optional, Union

from mcdreforged.api.types import CommandSource
from mcdreforged.api.rtext import RTextBase
from chunk_backup.task.basic_task import ImmediateTask


class ShowHelpTask(ImmediateTask[None]):
    COMMANDS_WITH_DETAILED_HELP = [
        'make',
        'back',
        'list',
        'show',
        'log',
        'del'
    ]

    def __init__(self, source: CommandSource, what: Optional[str] = None):
        super().__init__(source)
        self.what = what

    @property
    def id(self) -> str:
        return 'help'

    def reply(self, msg: Union[str, RTextBase], *, with_prefix: bool = False):
        super().reply(msg, with_prefix=with_prefix)

    @property
    def __cmd_prefix(self) -> str:
        return self.config.command.prefix

    def __has_permission(self, literal: str) -> bool:
        return self.source.has_permission(self.config.command.permission.get(literal))

    def run(self) -> None:

        if self.what is None:
            msg_list = [
                self.get_json_obj('commands.content', prefix=self.__cmd_prefix),
                self.get_json_obj('arguments.content', prefix=self.__cmd_prefix)
            ]
            self.reply(self.merge_rtext_lists(msg_list))
            return

        self.reply(self.get_json_obj(f"node_help.{self.what}", prefix=self.__cmd_prefix))
