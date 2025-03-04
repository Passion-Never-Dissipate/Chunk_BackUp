from mcdreforged.api.all import *
from chunk_backup.json_message import Message


help_msg = """
Chunk BackUp

"""

#main

def print_help_msg(sourece: CommandSource):
    sourece.reply(help_msg)

def reload_plugin(source: CommandSource):
    source.get_server().reload_plugin("world_eater_manage")
    source.reply(tr("reload"))



def on_load(sserver: PluginServerInterface):
    builder = SimpleCommandBuilder()

    builder.command('!!cp',print_help_msg)
    builder.command('!!cp reload', reload_plugin)