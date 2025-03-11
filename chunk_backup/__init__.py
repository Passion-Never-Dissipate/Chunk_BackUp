import datetime
import os
import re
import shutil
import time
import math
import traceback

from typing import Optional
from mcdreforged.api.types import Info, InfoCommandSource, CommandSource, ServerInterface, PluginServerInterface
from mcdreforged.api.command import SimpleCommandBuilder, Requirements, Number, Integer, GreedyText, Text
from mcdreforged.api.decorator import new_thread
from chunk_backup.config import cb_info, cb_config
from chunk_backup.tools import tr, update_config, save_json_file, safe_load_json, FileStatsAnalyzer as analyzer
from chunk_backup.region import Region as region
from chunk_backup.region import ChunkSelector as selector
from chunk_backup.json_message import Message
from chunk_backup.errors import *

Prefix = '!!cb'
config_path = os.path.join(".", "config", "chunk_backup", "chunk_backup.json")
config_name = "chunk_backup.json"
cfg = cb_config
server_path = cb_config.server_path
dimension_info = cb_config.dimension_info
region_obj: Optional[region] = None
time_out = 10
countdown = 10


def wait_until(condition_checker, timeout, initial_interval=0.001, max_interval=0.1):
    """动态轮询
    :param condition_checker: 条件判断的lambda表达式
    :param timeout: 超时时间(秒)
    :param initial_interval: 初始轮询间隔(默认1ms)
    :param max_interval: 最大轮询间隔(默认100ms)
    """
    deadline = time.time() + timeout
    current_interval = initial_interval

    while not condition_checker():
        if time.time() > deadline:
            return False
        time.sleep(current_interval)
        current_interval = min(current_interval * 2, max_interval)
    return True


class GetServerData:
    def __init__(self, player: Optional[str] = None):
        self.player = player
        self.coord = None
        self.dimension = None
        self.save_off = None
        self.save_all = None
        self.index = None

    def get_player_info(self):
        global region_obj

        self.index = 1
        ServerInterface.get_instance().execute(f"data get entity {self.player} Pos")
        ServerInterface.get_instance().execute(f"data get entity {self.player} Dimension")
        success = wait_until(
            lambda: self.coord and self.dimension,
            time_out,
            initial_interval=0.001  # 初始更密集检测
        )
        if not success:
            self.index = None
            raise GetPlayerDataTimeout

        self.index = None
        self.coord = [float(p.strip('d')) for p in self.coord.strip("[]").split(',')]
        self.dimension = self.dimension.strip('"')
        self.get_saved_info()

    def get_saved_info(self):
        global region_obj
        self.index = 3
        ServerInterface.get_instance().execute("save-off")
        if not wait_until(lambda: self.save_off, time_out, initial_interval=0.001):
            self.index = None
            raise SavaoffTimeout

        self.index = 4
        ServerInterface.get_instance().execute("save-all flush")
        if not wait_until(lambda: self.save_all, time_out, initial_interval=0.01, max_interval=0.1):
            self.index = None
            raise SaveallTimeout

        self.index = None
        region_obj = region()


server_data: Optional[GetServerData] = None


def print_help_msg(src: InfoCommandSource):
    if len(src.get_info().content.split()) < 2:
        src.reply(
            Message.get_json_str(tr("introduction.help_message", Prefix, "Chunk BackUp", cb_config.plugin_version)))
        src.get_server().execute_command(f"{Prefix} list", src)

    else:
        src.reply(Message.get_json_str(tr("introduction.full_help_message", Prefix)))


def check_backup_state(func):
    def wrapper(source: InfoCommandSource, dic: dict):
        global server_data, region_obj
        if any((region.backup_state is not None, region.back_state is not None, isinstance(region_obj, region))):
            source.reply(tr("prompt_msg.repeat_backup"))
            return

        if not region.check_dimension(dimension_info):
            source.reply(tr("prompt_msg.repeat_dimension"))
            return

        try:
            return func(source, dic)

        except Timeout as error:
            source.reply(tr("prompt_msg.backup.timeout", Prefix))
            if not type(error).__name__ == "GetPlayerDataTimeout":
                source.get_server().execute("save-on")

        except BackupError as error:
            server_data = None
            region_obj = None
            if not type(error).__name__ == "BackupTimeout":
                source.get_server().execute("save-on")
            source.reply(error.args[0])

        except BackError as error:
            region_obj = None
            source.reply(error.args[0])

        except Exception:
            server_data = None
            region_obj = None
            source.reply(tr("error.unknown_error", traceback.format_exc()))

        finally:
            if region.backup_state:
                if server_data:
                    server_data = None
                if region_obj:
                    region_obj = None
                    source.get_server().execute("save-on")
                region.backup_state = None
                return

            if region.back_state:
                region.back_state = None

    return wrapper


@new_thread("cb_make")
@check_backup_state
def cb_make(src: InfoCommandSource, dic: dict):
    global server_data
    region.backup_state = 1
    if not src.get_info().is_player:
        raise NoPlayer
    swap_dict = region.swap_dimension_key(dimension_info)
    dic["comment"] = dic.get("comment", tr("prompt_msg.comment.empty_comment"))
    radius = dic["radius"]
    t = time.time()
    src.get_server().broadcast(tr("prompt_msg.backup.start"))
    server_data = GetServerData(src.get_info().player)
    server_data.get_player_info()
    if not (server_data.dimension in swap_dict):
        raise UnidentifiedDimension(server_data.dimension)
    region_obj.user_pos = " ".join([str(i) for i in server_data.coord])
    selected = selector((((server_data.coord[0], server_data.coord[-1]), radius),),
                        max_chunk_size=cfg.max_chunk_length).group_by_region()
    region_obj.src = src
    region_obj.cfg = cfg
    region_obj.coords = selected
    region_obj.dimension.append(server_data.dimension)
    region_obj.world_name = swap_dict[server_data.dimension]["world_name"]
    region_obj.region_folder = swap_dict[server_data.dimension]["region_folder"]
    region_obj.backup_path = region.get_backup_path(cfg, src.get_info().content)
    region_obj.organize_slot()
    region_obj.copy()
    region_obj.save_info_file(src, dic["comment"])
    t1 = time.time()
    src.get_server().broadcast(
        tr("prompt_msg.backup.done", f"{(t1 - t):.2f}")
    )
    src.get_server().broadcast(
        tr("prompt_msg.backup.time", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
    )


@new_thread("cb_pos_make")
@check_backup_state
def cb_pos_make(src: InfoCommandSource, dic: dict):
    global server_data
    region.backup_state = 1
    coord = ((dic["x1"], dic["z1"]), (dic["x2"], dic["z2"]))
    dic["comment"] = dic.get("comment", tr("prompt_msg.comment.empty_comment"))
    if str(dic["dimension_int"]) not in dimension_info:
        raise InputDimError
    selected = selector(coord, max_chunk_size=cfg.max_chunk_length).group_by_region()
    t = time.time()
    src.get_server().broadcast(tr("prompt_msg.backup.start"))
    server_data = GetServerData()
    server_data.get_saved_info()
    region_obj.src = src
    region_obj.cfg = cfg
    region_obj.dimension.append(dimension_info[str(dic["dimension_int"])]["dimension"])  # 此处暂时这样写，后续必须改进
    region_obj.world_name = dimension_info[str(dic["dimension_int"])]["world_name"]
    region_obj.region_folder = dimension_info[str(dic["dimension_int"])]["region_folder"]
    region_obj.backup_path = region.get_backup_path(cfg, src.get_info().content)
    region_obj.coords = selected
    region_obj.organize_slot()
    region_obj.copy()
    region_obj.save_info_file(src, dic["comment"])
    t1 = time.time()
    src.get_server().broadcast(
        tr("prompt_msg.backup.done", f"{(t1 - t):.2f}")
    )
    src.get_server().broadcast(
        tr("prompt_msg.backup.time", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
    )


@new_thread("cb_dim_make")
@check_backup_state
def cb_dim_make(src: InfoCommandSource, dic: dict):
    global server_data
    region.backup_state = 1
    dic["comment"] = dic.get("comment", tr("prompt_msg.comment.empty_comment"))
    pattern = r'^[-+]?\d+(?:[，,][-+]?\d+)*$'
    if not re.fullmatch(pattern, dic["dimension"]):
        raise InvalidInput
    res = re.findall(r'[-+]?\d+', dic["dimension"])
    dimension = [s for s in res]
    if len(dimension) != len(set(dimension)):
        raise InputDimRepeat
    for dim in dimension:
        if dim not in dimension_info:
            raise InputDimError
    t = time.time()
    src.get_server().broadcast(tr("prompt_msg.backup.start"))
    server_data = GetServerData()
    server_data.get_saved_info()
    region_obj.backup_type = "region"
    region_obj.cfg = cfg
    region_obj.dimension = dimension  # 这里的dimension是一个数字维度键列表
    region_obj.backup_path = region.get_backup_path(cfg, src.get_info().content)
    region_obj.organize_slot()
    region_obj.copy()
    region_obj.save_info_file(src, dic["comment"])
    t1 = time.time()
    src.get_server().broadcast(
        tr("prompt_msg.backup.done", f"{(t1 - t):.2f}")
    )
    src.get_server().broadcast(
        tr("prompt_msg.backup.time", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
    )


@new_thread("cb_back")
@check_backup_state
def cb_back(src: InfoCommandSource, dic: dict):
    global region_obj
    region.back_state = 1

    region_obj = region()
    region_obj.cfg = cfg
    region_obj.src = src
    region_obj.backup_path = region.get_backup_path(cfg, src.get_info().content)

    if not dic:
        if src.get_info().content.split()[1] == "restore":
            region_obj.slot = cfg.overwrite_backup_folder
            dic["slot"] = cfg.overwrite_backup_folder
        else:
            region_obj.slot = "slot1"
            dic["slot"] = 1
    else:
        region_obj.slot = f"slot{dic['slot']}"

    info_path = os.path.join(region_obj.backup_path, region_obj.slot, "info.json")
    if not os.path.exists(info_path):
        raise LackInfoFile

    info = safe_load_json(info_path)
    swap_dict = region.swap_dimension_key(dimension_info)
    if any(i not in swap_dict for i in info["backup_dimension"]):
        raise InvalidInfoDimension(dic["slot"])

    region_obj.dimension = info["backup_dimension"]
    region_obj.backup_type = info["backup_type"]

    ext = [".mca", ".region"]
    obj_slot = analyzer(os.path.join(region_obj.backup_path, region_obj.slot))
    obj_slot.scan_by_extension(ext, include_subdirs=True)
    if not obj_slot.get_ext_report():
        raise LackRegionFile

    time_ = info["time"]
    comment = info["comment"]
    src.reply(
        Message.get_json_str(
            "\n".join(
                [tr("prompt_msg.back.start", region_obj.slot.replace("slot", "", 1), time_, comment),
                 tr("prompt_msg.back.click", Prefix)]
            )
        )
    )

    t1 = time.time()
    region.back_state = 2
    while region.back_state == 2:
        if time.time() - t1 > countdown:
            raise BackTimeout
        time.sleep(0.01)

    if region.back_state == -1:
        raise BackAbort

    src.get_server().broadcast(tr("prompt_msg.back.down", countdown))

    for t in range(1, countdown):
        time.sleep(1)
        if region.back_state == -1:
            raise BackAbort
        src.get_server().broadcast(
            Message.get_json_str(
                tr("prompt_msg.back.count", f"{countdown - t}", Prefix, region_obj.slot.replace("slot", "", 1))
            )
        )

    src.get_server().stop()


def on_server_stop(server: PluginServerInterface, server_return_code: int):
    global region_obj
    try:
        if not region.backup_state and not region.back_state and isinstance(region_obj, region):
            if server_return_code != 0:
                server.logger.error(tr("error.server_error"))
                return
            server.logger.info(tr("prompt_msg.back.run"))
            region_obj.back()
            if region_obj.slot != region_obj.cfg.overwrite_backup_folder:
                region_obj.save_info_file()
            server.start()

    except Exception:
        server.logger.error(tr("error.unknown_error", traceback.format_exc()))
        server.start()

    finally:
        region_obj = None
        region.clear()


def cb_abort(source: CommandSource):
    # 当前操作备份信息
    if region.back_state not in {2, 3}:
        source.reply(tr("prompt_msg.abort"))
        return
    region.back_state = -1


def cb_confirm(source: CommandSource):
    if region.back_state != 2:
        source.reply(tr("prompt_msg.confirm"))
        return
    region.back_state = 3


def cb_del(source: InfoCommandSource, dic: dict):
    try:
        # 获取文件夹地址
        backup_path = region.get_backup_path(cfg, source.get_info().content)
        s = os.path.join(backup_path, f"slot{dic['slot']}")
        # 删除整个文件夹
        if os.path.exists(s):
            shutil.rmtree(s, ignore_errors=True)
            source.reply(tr("prompt_msg.del.done", dic['slot']))
            return
        source.reply(tr("prompt_msg.del.lack_slot", dic['slot']))

    except Exception:
        source.reply(tr("error.unknown_error", traceback.format_exc()))


def cb_set_config(source: InfoCommandSource, dic: dict):
    try:
        new_dict = safe_load_json(config_path)

        content = source.get_info().content
        right = content.split(maxsplit=2)[-1].split()
        command = right[0]
        if command == "slot":
            if len(right) == 3:
                new_dict["static_slot"] = dic["slot"]
            else:
                new_dict["slot"] = dic["slot"]

        elif command == "max_chunk_length":
            new_dict["max_chunk_length"] = dic["length"]

        save_json_file(config_path, new_dict)
        source.reply(tr("prompt_msg.set.done"))

    except Exception:
        source.reply(tr("error.unknown_error", traceback.format_exc()))


def cb_show(src: InfoCommandSource, dic: dict):
    args = src.get_info().content.split()
    is_overwrite = (args[-1] == "overwrite")
    backup_path = cfg.backup_path if is_overwrite else region.get_backup_path(cfg, src.get_info().content)
    name = "overwrite" if is_overwrite else f"slot{dic.get('page', 1)}"
    info_path = os.path.join(backup_path, name, "info.json")
    if not os.path.exists(info_path):
        src.reply(tr("prompt_msg.show.empty", 1 if name != "overwrite" else name if not dic else dic["page"]))
        return
    try:
        size = analyzer(os.path.join(backup_path, name))
        size.scan_all_files(include_subdirs=True)
        total = size.get_full_report()["all_files"]["total_size_human"]
        info = safe_load_json(info_path)
        msg_components = [
            tr("prompt_msg.show.title"),
            tr("prompt_msg.show.time", info["time"]),
            tr("prompt_msg.show.backup_type", info["backup_type"]),
            tr("prompt_msg.show.backup_dimension", ",".join(info["backup_dimension"])),
            tr("prompt_msg.show.user", info["user"]),
            tr("prompt_msg.show.user_pos", info["user_pos"]) if "user_pos" in info else tr("prompt_msg.show.no_pos"),
            tr("prompt_msg.show.comment", info["comment"]),
            tr("prompt_msg.show.command", info["command"]),
            tr("prompt_msg.show.size", total),
            tr("prompt_msg.show.version_created", info["version_created"])
        ]
        msg = [comp for comp in msg_components]
        src.reply(Message.get_json_str("\n".join(msg)))

    except Exception:
        src.reply(tr("error.unknown_error", traceback.format_exc()))


def cb_list(source: InfoCommandSource, dic: dict):
    backup_path = region.get_backup_path(cfg, source.get_info().content)
    dynamic = (backup_path == cfg.backup_path)
    slot_ = region.get_slot_number(backup_path, cfg)
    if not slot_:
        source.reply(tr("prompt_msg.list.empty_slot"))
        return

    p = 1 if not dic else dic["page"]
    page = math.ceil(slot_ / 10)
    if p > page:
        source.reply(tr("prompt_msg.list.out_page"))
        return
    msg_list = [tr("prompt_msg.list.dynamic") if dynamic else tr("prompt_msg.list.static")]
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
                _time = info["time"]
                comment = info["comment"]
                dimension = ",".join(info['backup_dimension'])
                user = info["user"]
                command = info["command"]
                size_slot = analyzer(os.path.join(backup_path, name))
                size_slot.scan_all_files(include_subdirs=True)
                msg = tr(
                    "prompt_msg.list.slot", i, size_slot.get_full_report()["all_files"]["total_size_human"], _time,
                    comment, " -s"
                    if not dynamic else "", dimension, user, command, Prefix
                )
                msg_list.append(msg)
            else:
                msg = tr("prompt_msg.list.empty_size", i)
                msg_list.append(msg)

        if lp:
            msg = tr("prompt_msg.list.last_page", p, lp, " -s" if not dynamic else "", Prefix)
            if np:
                msg = msg + "  " + tr("prompt_msg.list.next_page", p, np, " -s" if not dynamic else "", Prefix)
            msg = msg + "  " + tr("prompt_msg.list.page", end, slot_)
            msg_list.append(msg)
        elif np:
            msg = tr("prompt_msg.list.next_page", p, np, " -s" if not dynamic else "", Prefix)
            msg = msg + "  " + tr("prompt_msg.list.page", end, slot_)
            msg_list.append(msg)

        source.reply(Message.get_json_str("\n".join(msg_list)))
        if p == 1:
            dynamic_ = analyzer(cfg.backup_path)
            dynamic_.scan_all_files(include_subdirs=True)
            static_ = analyzer(cfg.static_backup_path)
            static_.scan_all_files(include_subdirs=True)
            msg = tr(
                "prompt_msg.list.total_size", dynamic_.get_full_report()["all_files"]["total_size_human"],
                static_.get_full_report()["all_files"]["total_size_human"],
                analyzer.format_size(
                    dynamic_.get_full_report()["all_files"]["total_size_bytes"] +
                    static_.get_full_report()["all_files"][
                        "total_size_bytes"])
            )
            source.reply(msg)

    except Exception:
        source.reply(tr("error.unknown_error", traceback.format_exc()))


def cb_reload(source: CommandSource):
    source.reply(tr("prompt_msg.reload.done"))
    source.get_server().reload_plugin("chunk_backup")


def cb_force_reload(source: CommandSource):
    global server_data, region_obj
    server_data = None
    region_obj = None
    region.clear()
    source.get_server().execute("save-on")
    source.reply(tr("prompt_msg.reload.done"))
    source.get_server().reload_plugin("chunk_backup")


# 消息监听器
def on_info(server: PluginServerInterface, info: Info):
    if server_data and not region_obj:
        if isinstance(server_data.player, str) and info.content.startswith(
                f"{server_data.player} has the following entity data: ") and server_data.index == 1 and info.is_from_server:
            if not server_data.coord:
                server_data.coord = info.content.split(sep="entity data: ")[-1]
            else:
                server_data.dimension = info.content.split(sep="entity data: ")[-1]
            return

        if info.content.startswith(
                "Automatic saving is now disabled") and server_data.index == 3 and info.is_from_server:
            server_data.save_off = 1
            return

        if info.content.startswith("Saved the game") and server_data.index == 4 and info.is_from_server:
            server_data.save_all = 1


def on_load(server: PluginServerInterface, old):
    global cfg, dimension_info, server_path, Prefix, server_data, region_obj

    if old:
        server_data = old.server_data
        region_obj = old.region_obj

    if not os.path.exists(os.path.join(server.get_data_folder(), config_name)):
        server.save_config_simple(cb_config.get_default(), config_name)
    else:
        old_dict = server.load_config_simple(config_name, target_class=cb_config).serialize()
        new_dict = update_config(old_dict)
        if new_dict["plugin_version"] != cfg.plugin_version:
            new_dict["plugin_version"] = cfg.plugin_version
        save_json_file(config_path, new_dict)

    cfg = server.load_config_simple(config_name, target_class=cb_config)

    Prefix = cfg.prefix
    server_path = cfg.server_path
    dimension_info = cfg.dimension_info

    server.register_help_message(Prefix, tr("introduction.register_message"))
    lvl = cfg.minimum_permission_level
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
    builder.command(f"{Prefix} pmake <x1> <z1> <x2> <z2> in <dimension_int>", cb_pos_make)
    builder.command(f"{Prefix} pmake <x1> <z1> <x2> <z2> in <dimension_int> <comment>", cb_pos_make)
    builder.command(f"{Prefix} pmake -s <x1> <z1> <x2> <z2> in <dimension_int>", cb_pos_make)
    builder.command(f"{Prefix} pmake -s <x1> <z1> <x2> <z2> in <dimension_int> <comment>", cb_pos_make)
    builder.command(f"{Prefix} back", cb_back)
    builder.command(f"{Prefix} back <slot>", cb_back)
    builder.command(f"{Prefix} back -s", cb_back)
    builder.command(f"{Prefix} back -s <slot>", cb_back)
    builder.command(f"{Prefix} restore", cb_back)
    builder.command(f"{Prefix} confirm", cb_confirm)
    builder.command(f"{Prefix} del <slot>", cb_del)
    builder.command(f"{Prefix} del -s <slot>", cb_del)
    builder.command(f"{Prefix} set slot <slot>", cb_set_config)
    builder.command(f"{Prefix} set slot -s <slot>", cb_set_config)
    builder.command(f"{Prefix} set max_chunk_length <length>", cb_set_config)
    builder.command(f"{Prefix} abort", cb_abort)
    builder.command(f"{Prefix} list", cb_list)
    builder.command(f"{Prefix} list <page>", cb_list)
    builder.command(f"{Prefix} list -s", cb_list)
    builder.command(f"{Prefix} list -s <page>", cb_list)
    builder.command(f"{Prefix} show", cb_show)
    builder.command(f"{Prefix} show <page>", cb_show)
    builder.command(f"{Prefix} show -s", cb_show)
    builder.command(f"{Prefix} show -s <page>", cb_show)
    builder.command(f"{Prefix} show overwrite", cb_show)
    builder.command(f"{Prefix} reload", cb_reload)
    builder.command(f"{Prefix} force_reload", cb_force_reload)

    builder.arg("x1", Number)
    builder.arg("z1", Number)
    builder.arg("x2", Number)
    builder.arg("z2", Number)
    builder.arg("dimension", Text)
    builder.arg("dimension_int", Integer)
    builder.arg("length", lambda length: Integer(length).at_min(1))
    builder.arg("radius", lambda radius: Integer(radius).at_min(0))
    builder.arg("comment", GreedyText)
    builder.arg("slot", lambda s: Integer(s).at_min(1))
    builder.arg("page", lambda page: Integer(page).at_min(1))

    for literal in cb_config.minimum_permission_level:
        permission = lvl[literal]
        builder.literal(literal).requires(
            require.has_permission(permission),
            failure_message_getter=lambda err: tr("prompt_msg.lack_permission")
        )

    builder.register(server)
