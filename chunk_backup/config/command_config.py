from mcdreforged.api.utils import Serializable
from chunk_backup.types.units import Duration


class CommandPermissions(Serializable):
    root: int = 0
    abort: int = 1
    back: int = 2
    confirm: int = 1
    log: int = 1
    help: int = 0
    # del: int = 2  # see the __add_del_permission() function below
    list: int = 0
    make: int = 1
    bluemap: int = 1
    rename: int = 2
    reload: int = 3
    show: int = 0

    def get(self, literal: str) -> int:
        if literal.startswith('_'):
            raise KeyError(literal)
        return getattr(self, literal, 1)

    def items(self):
        return self.serialize().items()


def __add_del_permission():
    # 动态添加名为 'del' 的属性
    setattr(CommandPermissions, 'del', 2)  # 设置默认权限级别

    # 修改 __annotations__ 以保持类型注解（如果需要）
    annotations = list(map(tuple, CommandPermissions.__annotations__.items()))
    for i in range(len(annotations)):
        if annotations[i][0] == 'help':  # 可以根据需要选择插入位置
            annotations.insert(i + 1, ('del', int))
    CommandPermissions.__annotations__.clear()
    CommandPermissions.__annotations__.update(dict(annotations))


__add_del_permission()


class CommandConfig(Serializable):
    prefix: str = '!!cb'
    permission: CommandPermissions = CommandPermissions()
    confirm_time_wait: Duration = Duration('60s')
    restore_countdown_sec: int = 10
