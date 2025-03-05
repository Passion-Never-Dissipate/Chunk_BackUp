import datetime
import os
import re
import shutil
import time
import math
import traceback

from mcdreforged.api.all import *
from typing import *
from region_backup.config import cb_info, cb_config
from region_backup.handle_file import safe_load_json, FileStatsAnalyzer as analyzer
from region_backup.region import Region as region
from region_backup.region import ChunkSelector as selector
from region_backup.json_message import Message

Prefix = '!!cb'
cfg = {
    "config": cb_config,
    "info": cb_info
}
server_path = cb_config.server_path
dimension_info = cb_config.dimension_info
region_obj: Optional[region] = None
server_data = None
time_out = 5
countdown = 10


def print_help_msg(src: InfoCommandSource):
    if len(src.get_info().content.split()) < 2:
        src.reply(Message.get_json_str(tr("help_message", Prefix, "Chunk BackUp", cb_config.plugin_version)))
        src.get_server().execute_command("!!cb list", src)

    else:
        src.reply(Message.get_json_str(tr("full_help_message", Prefix)))


def check_backup_state(func):
    def wrapper(source: InfoCommandSource, dic: dict):
        global server_data, region_obj
        if any((region.backup_state is not None, region.back_state is not None, isinstance(region_obj, region))):
            source.reply(tr("backup_error.repeat_backup"))
            return

        try:
            return func(source, dic)

        except Exception:
            region_obj = None
            region.clear()
            source.reply(tr("backup_error.unknown_error", traceback.format_exc()))
            source.get_server().execute("save-on")

        finally:
            region.backup_state = None
            server_data = None

    return wrapper


@new_thread("cb_make")
@check_backup_state
def cb_make(src: InfoCommandSource, dic: dict):
    global server_data
    region.backup_state = 1
    if not src.get_info().is_player:
        src.reply(tr("backup_error.source_error"))
        return
    dic["comment"] = dic.get("comment", tr("comment.empty_comment"))
    radius = dic["radius"]
    t = time.time()
    src.get_server().broadcast(tr("backup.start"))
    server_data = GetServerData(src.get_info().player)
    server_data.get_player_info()
    if not region_obj:
        src.reply(tr("backup_error.timeout"))
        return
    region_obj.backup_path = region.get_backup_path(src.get_info().content)
    max_msg = region.organize_slot(region_obj.backup_path, rename=1)
    if max_msg:
        src.get_server().broadcast(max_msg)
        return
    selected = selector(((server_data.coord[:1], server_data.coord[2:], radius),)).group_by_region()
    region_obj.coord = selected
    """if region.copy(server_data.dimension, backup_path, coord):
        src.get_server().broadcast(tr("config_error"))
        return"""
    region_obj.save_info_file(src.get_info().content, dic["comment"], src)
    t1 = time.time()
    src.get_server().broadcast(
        tr("backup.done", f"{(t1 - t):.2f}")
    )

    src.get_server().broadcast(
        tr("backup.date", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
    )
    src.get_server().execute("save-on")


@new_thread("cb_pos_make")
@check_backup_state
def cb_pos_make(src: InfoCommandSource, dic: dict):
    global server_data
    region.backup_state = 1
    coord = ((dic["x1"], dic["z1"]), (dic["x2"], dic["z2"]))
    dic["comment"] = dic.get("comment", tr("comment.empty_comment"))
    if str(dic["dimension_int"]) not in dimension_info:
        src.reply(tr("backup_error.dim_error"))
        return
    t = time.time()
    src.get_server().broadcast(tr("backup.start"))
    server_data = GetServerData()
    server_data.get_saved_info()
    if not region_obj:
        src.reply(tr("backup_error.timeout"))
        return
    region_obj.backup_path = region.get_backup_path(src.get_info().content)
    max_msg = region.organize_slot(region_obj.backup_path, rename=1)
    if max_msg:
        src.get_server().broadcast(max_msg)
        return
    selected = selector(coord).group_by_region()
    region_obj.coord = selected
    """if region.copy(str(dic["dimension_int"]), backup_path, coord):
        src.reply(tr("config_error"))
        return"""
    region_obj.save_info_file(src.get_info().content, dic["comment"], src)
    t1 = time.time()
    src.get_server().broadcast(
        tr("backup.done", f"{(t1 - t):.2f}")
    )

    src.get_server().broadcast(
        tr("backup.date", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
    )
    src.get_server().execute("save-on")


@new_thread("cb_dim_make")
@check_backup_state
def cb_dim_make(src: InfoCommandSource, dic: dict):
    global server_data
    region.backup_state = 1
    dic["comment"] = dic.get("comment", tr("comment.empty_comment"))
    res = re.findall(r'-\d+|\d+', dic["dimension"])
    dimension = [s for s in res]
    if len(dimension) != len(set(dimension)):
        src.reply(tr("backup_error.dim_repeat"))
        return
    for dim in dimension:
        if dim not in dimension_info:
            src.reply(tr("backup_error.dim_error"))
            return
    t = time.time()
    src.get_server().broadcast(tr("backup.start"))
    server_data = GetServerData()
    server_data.get_saved_info()
    if not region_obj:
        src.reply(tr("backup_error.timeout"))
        return
    region_obj.backup_path = region.get_backup_path(src.get_info().content)
    max_msg = region.organize_slot(region_obj.backup_path, rename=1)
    if max_msg:
        src.get_server().broadcast(max_msg)
        return
    """for dim in dimension:
        if region.copy(dim, backup_path):
            source.reply(tr("config_error"))
            return"""
    region_obj.save_info_file(src.get_info().content, dic["comment"], src)
    t1 = time.time()
    src.get_server().broadcast(
        tr("backup.done", f"{(t1 - t):.2f}")
    )

    src.get_server().broadcast(
        tr("backup.date", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
    )
    src.get_server().execute("save-on")


@new_thread("cb_back")
@check_backup_state
def cb_back(src: InfoCommandSource, dic: dict):
    global region_obj
    region_obj = region()
    region.back_state = 1
    region_obj.backup_path = region.get_backup_path(src.get_info().content)
    if not dic:
        if src.get_info().content.split()[1] == "restore":
            region_obj.slot = cfg["config"].overwrite_backup_folder
        else:
            region_obj.slot = "slot1"
    else:
        region_obj.slot = f"slot{dic['slot']}"
    info_path = os.path.join(region_obj.backup_path, dic["slot"], "info.json")
    if not os.path.exists(info_path):
        src.reply(tr("back_error.lack_info"))
        return
    """if not region.get_total_size([
        os.path.join(
            backup_path, dic["slot"], i) for i in os.listdir(
            os.path.join(
                backup_path, dic["slot"]
            )
        )
        if os.path.isdir(os.path.join(backup_path, dic["slot"], i))
    ])[-1]:
        src.reply(tr("back_error.lack_region"))
        return"""
    info = safe_load_json(info_path)

    _time = info["time"]
    comment = info["comment"]

    src.reply(
        Message.get_json_str(
            "\n".join([tr("back.start", dic["slot"].replace("slot", "", 1), _time, comment), tr("back.click")]))
    )
    t1 = time.time()
    region.back_state = 2
    while region.back_state == 2:
        if time.time() - t1 > countdown:
            src.reply(tr("back_error.timeout"))
            return
        time.sleep(0.01)

    if region.back_state == -1:
        src.reply(tr("back.abort"))
        return
    src.get_server().broadcast(tr("back.countdown", countdown))

    for t in range(1, countdown):
        time.sleep(1)
        if region.back_state == -1:
            src.reply(tr("back.abort"))
            return
        src.get_server().broadcast(
            Message.get_json_str(
                tr("back.count", f"{countdown - t}", dic["slot"].replace("slot", "", 1))
            )
        )
    region.back_slot = dic["slot"]
    src.get_server().stop()


def cb_abort(source: CommandSource):
    # 当前操作备份信息
    if region.back_state not in {2, 3}:
        source.reply(tr("abort"))
        return
    region.back_state = -1


def cb_confirm(source: CommandSource):
    if region.back_state != 2:
        source.reply(tr("confirm"))
        return
    region.back_state = 3


def on_server_stop(server: PluginServerInterface, server_return_code: int):
    global region_obj
    try:
        if region.back_state and isinstance(region_obj, region):
            if server_return_code != 0:
                server.logger.error(tr("back_error.server_error"))
                return
            server.logger.info(tr("back.run"))
            backup_path = region_obj.backup_path
            info = safe_load_json(os.path.join(backup_path, region_obj.slot, "info.json"))

            dimension = info["backup_dimension"].split(",")

            new_dict = region.swap_dimension_key(dimension_info)

            if not new_dict:
                server.logger.error(tr("back_error.wrong_dim"))
                return

            for i in dimension:
                if i not in new_dict:
                    server.logger.error(tr("back_error.wrong_dim"))
                    return

            """dimension = info["backup_dimension"].split(",")
            all_dimension = [d for d in dimension_info.values()]
            if not all(i in [v["dimension"] for v in all_dimension] for i in dimension):
                region.clear()
                server.logger.error(tr("back_error.wrong_dim"))
                return

            region_folder = {}
            dimension = set(dimension)  # 转换为集合，自动去重
            for v in all_dimension:
                if v["dimension"] in dimension:  # 直接检查是否在集合中
                    region_folder[v["dimension"]] = [v["world_name"], v["region_folder"]]"""

            server.start()

    except Exception:
        server.logger.error(tr("back_error.unknown_error", traceback.format_exc()))
        return

    finally:
        region_obj = None
        region.clear()


def cb_del(source: InfoCommandSource, dic: dict):
    try:
        # 获取文件夹地址
        backup_path = region.get_backup_path(source.get_info().content)
        s = os.path.join(backup_path, f"slot{dic['slot']}")
        # 删除整个文件夹
        if os.path.exists(s):
            shutil.rmtree(s, ignore_errors=True)
            source.reply(tr("del", dic['slot']))
            return
        source.reply(tr("del_error.lack_slot", dic['slot']))

    except Exception:
        source.reply(tr("del_error.unknown_error", traceback.format_exc()))


def cb_list(source: InfoCommandSource, dic: dict):
    backup_path = region.get_backup_path(source.get_info().content)
    dynamic = (backup_path == cfg["config"].backup_path)
    slot_ = region.organize_slot(backup_path)
    if not slot_:
        source.reply(tr("list.empty_slot"))
        return

    p = 1 if not dic else dic["page"]
    page = math.ceil(slot_ / 10)
    if p > page:
        source.reply(tr("list.out_page"))
        return
    msg_list = [tr("list.dynamic") if dynamic else tr("list.static")]
    start = 10 * (p - 1) + 1
    end = slot_ if 10 * (p - 1) + 1 <= slot_ <= 10 * p else 10 * p
    lp = p - 1 if p > 1 else 0
    np = p + 1 if p + 1 <= page else 0

    try:
        for i in range(start, end + 1):
            name = f"slot{i}"
            path = os.path.join(backup_path, name, "info.json")
            if os.path.exists(path):
                info = safe_load_json(path)
                t = info["time"]
                comment = info["comment"]
                dimension = info['backup_dimension']
                user = info["user"]
                command = info["command"]
                size = region.get_total_size([os.path.join(backup_path, name)])
                msg = tr(
                    "list.slot_info", i, size[0], t, comment, "-s"
                    if not dynamic else "", dimension, user, command
                )
                msg_list.append(msg)
            else:
                msg = tr("list.empty_size", i)
                msg_list.append(msg)

        if lp:
            msg = tr("list.last_page", p, lp, "-s" if not dynamic else "")
            if np:
                msg = msg + "  " + tr("list.next_page", p, np, "-s" if not dynamic else "")
            msg = msg + "  " + tr("list.page", end, slot_)
            msg_list.append(msg)
        elif np:
            msg = tr("list.next_page", p, np, "-s" if not dynamic else "")
            msg = msg + "  " + tr("list.page", end, slot_)
            msg_list.append(msg)

        source.reply(Message.get_json_str("\n".join(msg_list)))
        dynamic_ = region.get_total_size([cfg["config"].backup_path])[-1]
        static_ = region.get_total_size([cfg["config"].static_backup_path])[-1]
        msg = tr(
            "list.total_size", region.convert_bytes(dynamic_),
            region.convert_bytes(static_), region.convert_bytes(dynamic_ + static_)
        )
        source.reply(msg)

    except Exception:
        source.reply(tr("list_error", traceback.format_exc()))
        return


def cb_reload(source: CommandSource):
    source.reply(tr("reload"))
    source.get_server().reload_plugin("region_backup")


def tr(key, *args):
    return ServerInterface.get_instance().tr(f"region_backup.{key}", *args)


def on_info(server: PluginServerInterface, info: Info):
    if isinstance(server_data, GetServerData) and not region_obj:
        if isinstance(server_data.player, str) and info.content.startswith(
                f"{server_data.player} has the following entity data: ") \
                and not server_data.save_all and not server_data.save_off and info.is_from_server:
            if not server_data.coord:
                server_data.coord = info.content.split(sep="entity data: ")[-1]
            else:
                server_data.dimension = info.content.split(sep="entity data: ")[-1]
            return

        if info.content.startswith("Saved the game") and info.is_from_server \
                and not server_data.dimension and not server_data.coord:
            server_data.save_off = 1
            return

        if info.content.startswith("Automatic saving is now disabled") \
                and not server_data.dimension and not server_data.coord:
            server_data.save_all = 1


class GetServerData:
    def __init__(self, player: Optional[str] = None):
        self.player = player
        self.coord = None
        self.dimension = None
        self.save_off = None
        self.save_all = None

    def get_player_info(self):
        global region_obj
        ServerInterface.get_instance().execute(f"data get entity {self.player} Pos")
        time.sleep(0.01)
        ServerInterface.get_instance().execute(f"data get entity {self.player} Dimension")

        t1 = time.time()
        while not self.coord or not self.dimension:
            if time.time() - t1 > time_out:
                region_obj = None
                return
            time.sleep(0.01)

        self.coord = [float(p.strip('d')) for p in self.coord.strip("[]").split(',')]
        self.dimension = self.dimension.strip('"')
        self.get_saved_info()

    def get_saved_info(self):
        global region_obj
        ServerInterface.get_instance().execute("save-off")
        t1 = time.time()
        while not self.save_off:
            if time.time() - t1 > time_out:
                region_obj = None
                return
            time.sleep(0.01)
        ServerInterface.get_instance().execute("save-all flush")
        t1 = time.time()
        while not self.save_all:
            if time.time() - t1 > time_out:
                region_obj = None
                return
            time.sleep(0.01)

        region_obj = region()


def on_load(server: PluginServerInterface, old):
    global dimension_info, server_path, Prefix, server_data, region_obj

    if old:
        server_data = old.server_data
        region_obj = old.region_obj

    if not os.path.exists(server.get_data_folder()):
        server.save_config_simple(config=cb_config.get_default())

    cfg["config"] = server.load_config_simple(target_class=cb_config)

    Prefix = cfg["config"].prefix
    server_path = cfg["config"].server_path
    dimension_info = cfg["config"].dimension_info

    server.register_help_message(Prefix, tr("register_message"))
    lvl = cfg["config"].minimum_permission_level
    require = Requirements()
    builder = SimpleCommandBuilder()

    builder.command(f"{Prefix}", print_help_msg)
    builder.command(f"{Prefix} help", print_help_msg)
    builder.command(f"{Prefix} make <radius>", cb_make)
    builder.command(f"{Prefix} make <radius> <comment>", cb_make)
    builder.command(f"{Prefix} make -s <radius>", cb_make)
    builder.command(f"{Prefix} make -s <radius> <comment>", cb_make)
    builder.command(f"{Prefix} dmake <dimension> <comment>", cb_dim_make)
    builder.command(f"{Prefix} dmake <dimension>", cb_dim_make)
    builder.command(f"{Prefix} dmake -s <dimension>", cb_dim_make)
    builder.command(f"{Prefix} dmake -s <dimension> <comment>", cb_dim_make)
    builder.command(f"{Prefix} pmake <x1> <z1> <x2> <z2> <dimension_int>", cb_pos_make)
    builder.command(f"{Prefix} pmake <x1> <z1> <x2> <z2> <dimension_int> <comment>", cb_pos_make)
    builder.command(f"{Prefix} pmake -s <x1> <z1> <x2> <z2> <dimension_int>", cb_pos_make)
    builder.command(f"{Prefix} pmake -s <x1> <z1> <x2> <z2> <dimension_int> <comment>", cb_pos_make)
    builder.command(f"{Prefix} back", cb_back)
    builder.command(f"{Prefix} back <slot>", cb_back)
    builder.command(f"{Prefix} back -s", cb_back)
    builder.command(f"{Prefix} back -s <slot>", cb_back)
    builder.command(f"{Prefix} restore", cb_back)
    builder.command(f"{Prefix} confirm", cb_confirm)
    builder.command(f"{Prefix} del <slot>", cb_del)
    builder.command(f"{Prefix} del -s <slot>", cb_del)
    builder.command(f"{Prefix} abort", cb_abort)
    builder.command(f"{Prefix} list", cb_list)
    builder.command(f"{Prefix} list <page>", cb_list)
    builder.command(f"{Prefix} list -s", cb_list)
    builder.command(f"{Prefix} list -s <page>", cb_list)
    builder.command(f"{Prefix} reload", cb_reload)

    builder.arg("x1", Number)
    builder.arg("z1", Number)
    builder.arg("x2", Number)
    builder.arg("z2", Number)
    builder.arg("dimension", Text)
    builder.arg("dimension_int", Integer)
    builder.arg("radius", lambda radius: Integer(radius).at_min(0))
    builder.arg("comment", GreedyText)
    builder.arg("slot", lambda s: Integer(s).at_min(1))
    builder.arg("page", lambda page: Integer(page).at_min(1))

    for literal in cb_config.minimum_permission_level:
        permission = lvl[literal]
        builder.literal(literal).requires(
            require.has_permission(permission),
            failure_message_getter=lambda err: tr("lack_permission")
        )

    builder.register(server)
