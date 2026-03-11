from typing import Union
from mcdreforged.api.rtext import RTextBase
from chunk_backup.task.basic_task import ImmediateTask


class ShowWelcomeTask(ImmediateTask[None]):
    BACKUP_NUMBER_TO_SHOW = 5

    @property
    def id(self) -> str:
        return 'welcome'

    def reply(self, msg: Union[str, RTextBase], *, with_prefix: bool = False):
        super().reply(msg, with_prefix=with_prefix)

    @property
    def __cmd_prefix(self) -> str:
        return self.config.command.prefix

    def run(self) -> None:
        with self.source.preferred_language_context():
            meta = self.server.get_self_metadata()
            msg_list = [self.get_json_obj('content', prefix=self.__cmd_prefix, id=meta.id, version=meta.version),
                        self.get_json_obj('url')]
            self.reply(self.merge_rtext_lists(msg_list))
            self.server.execute_command(f"{self.__cmd_prefix} list -h -p 5", self.source)
