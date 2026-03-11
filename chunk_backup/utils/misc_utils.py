from typing import Any, Optional, TypeVar

from chunk_backup import constants

_T = TypeVar('_T')


def represent(obj: Any, *, attrs: Optional[dict] = None) -> str:
    if attrs is None:
        attrs = {name: value for name, value in vars(obj).items() if not name.startswith('_')}
    kv = []
    for name, value in attrs.items():
        kv.append(f'{name}={value}')
    return '{}({})'.format(type(obj).__name__, ', '.join(kv))


def make_thread_name(name: str) -> str:
    return f'CB@{constants.INSTANCE_ID}-{name}'
