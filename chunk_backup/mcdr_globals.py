from mcdreforged.api.types import PluginServerInterface, Metadata

__all__ = [
    'server',
    'metadata'
]

server: PluginServerInterface
metadata: Metadata


def __init():
    global server, metadata
    if PluginServerInterface.si_opt() is not None:
        server = PluginServerInterface.psi()
        metadata = server.get_self_metadata()


__init()


def load():
    pass
