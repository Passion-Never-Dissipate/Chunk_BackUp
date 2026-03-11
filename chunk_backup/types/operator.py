import dataclasses
from typing import Union
from chunk_backup import constants
from mcdreforged.api.types import CommandSource


class _ChunkBackupOperatorName(str):
    pass


class ChunkBackupOperatorNames:
    """For :meth:`chunk_backup.types.operator.Operator.cb`"""
    import_ = _ChunkBackupOperatorName('import')
    pre_restore = _ChunkBackupOperatorName('pre_restore')
    scheduled_backup = _ChunkBackupOperatorName('scheduled_backup')
    test = _ChunkBackupOperatorName('test')


@dataclasses.dataclass(frozen=True)
class Operator:
    type: str
    name: str

    @classmethod
    def unknown(cls) -> 'Operator':
        return Operator('unknown', '')

    @classmethod
    def cb(cls, cb_op_name: _ChunkBackupOperatorName) -> 'Operator':
        return Operator(constants.PLUGIN_ID, str(cb_op_name))

    @classmethod
    def player(cls, name: str) -> 'Operator':
        return Operator('player', name)

    @classmethod
    def console(cls) -> 'Operator':
        return Operator('console', '')

    @classmethod
    def literal(cls, name: str) -> 'Operator':
        return Operator('literal', name)

    @classmethod
    def of(cls, value: Union[str, 'CommandSource']) -> 'Operator':
        from mcdreforged.api.all import CommandSource
        if isinstance(value, CommandSource):
            if value.is_player:
                # noinspection PyUnresolvedReferences
                return cls.player(value.player)
            elif value.is_console:
                return cls.console()
            else:
                return Operator('command_source', str(value))
        elif isinstance(value, str):
            if ':' in value:
                t, n = value.split(':', 1)
                return Operator(type=t, name=n)
            else:
                return Operator(type='literal', name=value)
        else:
            raise TypeError(value)

    def __str__(self):
        return f'{self.type}:{self.name}'

    def is_player(self) -> bool:
        return self.type == 'player'
