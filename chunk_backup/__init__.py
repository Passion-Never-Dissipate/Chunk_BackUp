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
from chunk_backup.config import cb_info, cb_config, cb_custom_info, sub_slot_info
from chunk_backup.tools import tr, update_config, save_json_file, safe_load_json, DictReindexer as sort_dict, \
    FileStatsAnalyzer as analyzer
from chunk_backup.region import Region as region
from chunk_backup.region import ChunkSelector as selector
from chunk_backup.json_message import Message
from chunk_backup.errors import *

Prefix = '!!cb'
config_path = os.path.join(".", "config", "chunk_backup", "chunk_backup.json")
config_name = "chunk_backup.json"
cfg = cb_config
dimension_info = cb_config.dimension_info
data_getter = cb_config.data_getter
region_obj: Optional[region] = None
custom_dict = {}
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

    def get_player_info(self, end=False):
        global region_obj

        self.index = 1
        ServerInterface.get_instance().execute(data_getter["get_pos"].format(name=self.player))
        ServerInterface.get_instance().execute(data_getter["get_dimension"].format(name=self.player))
        success = wait_until(
            lambda: self.coord and self.dimension,
            time_out,
            initial_interval=0.001  # 初始更密集检测
        )
        if not success:
            self.index = None
            raise GetPlayerDataTimeout

        self.index = None

        if end:
            return
        self.get_saved_info()

    def get_saved_info(self):
        global region_obj
        self.index = 3
        ServerInterface.get_instance().execute(data_getter["auto_save_off"])
        if not wait_until(lambda: self.save_off, time_out, initial_interval=0.001):
            self.index = None
            raise SavaoffTimeout

        self.index = 4
        ServerInterface.get_instance().execute(data_getter["save_worlds"])
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
    def wrapper(source: InfoCommandSource, dic: dict, custom=False):
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
                source.get_server().execute(data_getter["auto_save_on"])

        except BackupError as error:
            server_data = None
            region_obj = None
            source.reply(error.args[0])

        except BackError as error:
            region_obj = None
            source.reply(error.args[0])

        except CreateSubSlotError as error:
            source.reply(error.args[0])

        except Exception:
            server_data = None
            region_obj = None
            source.get_server().execute(data_getter["auto_save_on"])
            source.reply(tr("error.unknown_error", traceback.format_exc()))

        finally:
            if custom:
                server_data = None
                region.backup_state = None
                return

            if region.backup_state:
                if server_data:
                    server_data = None
                if region_obj:
                    region_obj = None
                    source.get_server().execute(data_getter["auto_save_on"])
                region.backup_state = None
                return

            if region.back_state:
                region.back_state = None

    return wrapper


def cb_custom_create(src: InfoCommandSource, dic: dict):
    name = dic["custom_name"]
    if name in custom_dict:
        src.reply(tr("prompt_msg.custom.repeat_custom", name))
        return

    custom_dict[name] = cb_custom_info.get_default().serialize()
    custom_dict[name]["custom_name"] = dic["custom_name"]
    custom_dict[name]["time_created"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    custom_dict[name]["user_created"] = src.get_info().player if src.get_info().is_player else tr(
        "prompt_msg.comment.console")
    src.reply(tr("prompt_msg.custom.create_custom_success", name))


def cb_custom_list(src: InfoCommandSource, dic: dict):
    if not custom_dict:
        src.reply(tr("prompt_msg.custom.empty"))
        return

    p = 1 if not dic.get("page") else dic["page"]
    num = len(custom_dict)
    page = math.ceil(num / 10)
    if p > page:
        src.reply(tr("prompt_msg.list.out_page"))
        return
    start = 10 * (p - 1) + 1
    end = num if 10 * (p - 1) + 1 <= num <= 10 * p else 10 * p
    lp = p - 1 if p > 1 else 0
    np = p + 1 if p + 1 <= page else 0

    try:
        msg_list = [tr("prompt_msg.custom.list.title")]
        keys = list(custom_dict.keys())
        for i in range(start, end + 1):
            slot = tr("prompt_msg.custom.list.slot", keys[i - 1], Prefix, len(custom_dict[keys[i - 1]]["sub_slot"]))
            msg_list.append(slot)

        if lp:
            msg = tr("prompt_msg.custom.list.last_page", p, lp, Prefix)
            if np:
                msg = msg + "  " + tr("prompt_msg.list.next_page", p, np, Prefix)
            msg = msg + "  " + tr("prompt_msg.list.page", end, num)
            msg_list.append(msg)
        elif np:
            msg = tr("prompt_msg.custom.list.next_page", p, np, Prefix)
            msg = msg + "  " + tr("prompt_msg.list.page", end, num)
            msg_list.append(msg)

        src.reply(Message.get_json_str("\n".join(msg_list)))

    except Exception:
        src.reply(tr("error.unknown_error", traceback.format_exc()))


def cb_custom_del(src: InfoCommandSource, dic: dict):
    if dic["custom_name"] not in custom_dict:
        src.reply(tr("prompt_msg.custom.unidentified_custom", dic["custom_name"]))
        return
    if "sub_slot" not in dic:
        if not custom_dict.pop(dic["custom_name"], None):
            src.reply(tr("prompt_msg.custom.unidentified_custom", dic["custom_name"]))
            return
        src.reply(tr("prompt_msg.custom.del_custom_success", dic["custom_name"]))
    else:
        if not custom_dict[dic["custom_name"]]["sub_slot"].pop(dic["sub_slot"], None):
            src.reply(tr("prompt_msg.custom.unidentified_sub_slot", dic["sub_slot"]))
            return
        src.reply(tr("prompt_msg.custom.del_sub_slot_success", dic["sub_slot"]))


def cb_custom_show(src: InfoCommandSource, dic: dict):
    if dic["custom_name"] not in custom_dict:
        src.reply(tr("prompt_msg.custom.unidentified_custom", dic["custom_name"]))
        return
    else:
        if "sub_slot" in dic and dic["sub_slot"] not in custom_dict[dic["custom_name"]]["sub_slot"]:
            src.reply(tr("prompt_msg.custom.unidentified_sub_slot", dic["sub_slot"]))
            return

        if "page" in dic:
            p = dic["page"]
            num = len(custom_dict[dic["custom_name"]]["sub_slot"])
            if not num:
                src.reply(tr("prompt_msg.custom.empty_sub_slot", dic["custom_name"]))
                return
            page = math.ceil(num / 10)
            if p > page:
                src.reply(tr("prompt_msg.list.out_page"))
                return
            start = 10 * (p - 1) + 1
            end = num if 10 * (p - 1) + 1 <= num <= 10 * p else 10 * p
            lp = p - 1 if p > 1 else 0
            np = p + 1 if p + 1 <= page else 0

    is_sub_slot = dic.get("sub_slot", None)
    try:
        if not is_sub_slot:
            sub_slots = custom_dict.get(dic["custom_name"], {}).get("sub_slot", {})

            seen = set()
            for sub in sub_slots.values():
                dimension = sub.get("backup_dimension")
                seen.add(dimension)
            msg_components = [
                tr("prompt_msg.custom.show.title"),
                tr("prompt_msg.custom.show.name", dic["custom_name"]),
                tr("prompt_msg.custom.show.user_created", custom_dict[dic["custom_name"]]["user_created"]),
                tr("prompt_msg.custom.show.time_created", custom_dict[dic["custom_name"]]["time_created"]),
                tr("prompt_msg.show.backup_dimension",
                   ", ".join(seen) if seen else tr("prompt_msg.comment.empty_comment")),
                tr("prompt_msg.custom.show.sub_title")
            ]
            if sub_slots:
                num = len(sub_slots)
                if "page" not in dic:
                    p = 1
                    page = math.ceil(num / 10)
                    start = 10 * (p - 1) + 1
                    end = num if 10 * (p - 1) + 1 <= num <= 10 * p else 10 * p
                    lp = p - 1 if p > 1 else 0
                    np = p + 1 if p + 1 <= page else 0

                slots = list(sub_slots.keys())

                # noinspection PyUnboundLocalVariable
                for index in range(start - 1, end):
                    key, value = slots[index], sub_slots[slots[index]]
                    if index < num - 1:
                        msg_components.append(
                            tr("prompt_msg.custom.show.sub_slot", dic["custom_name"], key, Prefix, value["comment"]))
                    else:
                        msg_components.append(
                            tr("prompt_msg.custom.show.end_sub_slot", dic["custom_name"], key, Prefix,
                               value["comment"]))

                # noinspection PyUnboundLocalVariable
                if lp:
                    # noinspection PyUnboundLocalVariable
                    msg = tr("prompt_msg.custom.show.last_page", p, lp, dic["custom_name"], Prefix)
                    # noinspection PyUnboundLocalVariable
                    if np:
                        # noinspection PyUnboundLocalVariable
                        msg = msg + "  " + tr("prompt_msg.custom.show.next_page", p, np, dic["custom_name"], Prefix)
                    msg = msg + "  " + tr("prompt_msg.list.page", end, num)
                    msg_components.append(msg)
                elif np:
                    # noinspection PyUnboundLocalVariable
                    msg = tr("prompt_msg.custom.show.next_page", p, np, dic["custom_name"], Prefix)
                    msg = msg + "  " + tr("prompt_msg.list.page", end, num)
                    msg_components.append(msg)

            src.reply(Message.get_json_str("\n".join(msg_components)))

        else:
            sub_slot = custom_dict[dic["custom_name"]]["sub_slot"].get(dic["sub_slot"])
            if not sub_slot:
                src.reply(tr("prompt_msg.custom.unidentified_sub_slot", dic["sub_slot"]))
                return
            msg_components = [
                tr("prompt_msg.show.sub_title"),
                tr("prompt_msg.show.backup_type", sub_slot["backup_type"]),
                tr("prompt_msg.show.comment", sub_slot["comment"]),
                tr("prompt_msg.custom.show.parent", dic["custom_name"]),
                tr("prompt_msg.custom.show.user_created", sub_slot["user_created"]),
                tr("prompt_msg.show.user_pos", sub_slot["user_pos"]) if sub_slot.get("user_pos") else tr(
                    "prompt_msg.show.no_pos"),
                tr("prompt_msg.show.backup_dimension", sub_slot["backup_dimension"]),
                tr("prompt_msg.show.chunk_top_left_pos", ", ".join([str(i) for i in sub_slot["chunk_top_left_pos"]])),
                tr("prompt_msg.show.chunk_bottom_right_pos",
                   ", ".join([str(i) for i in sub_slot["chunk_bottom_right_pos"]])),
                tr("prompt_msg.custom.show.command_created", sub_slot["command"]),
                tr("prompt_msg.custom.show.time_created", sub_slot["time_created"])
            ]
            src.reply(Message.get_json_str("\n".join(msg_components)))

    except Exception:
        src.reply(tr("error.unknown_error", traceback.format_exc()))


@new_thread("cb_custom_save")
@check_backup_state
def cb_custom_save(src: InfoCommandSource, dic: dict):
    global server_data
    region.backup_state = 1
    if dic["custom_name"] not in custom_dict:
        raise UnidentifiedCustom(dic["custom_name"])

    sub_slots = custom_dict[dic["custom_name"]]["sub_slot"]

    if not sub_slots: raise EmptySubSlot(dic["custom_name"])

    groups_by_dimension = {}
    groups_coords_by_dimension = {}
    for sub in sub_slots.values():
        dimension = sub["backup_dimension"]
        groups_by_dimension.setdefault(dimension, []).append(sub["chunk"])

    swap_dict = region.swap_dimension_key(dimension_info)

    for dimension in groups_by_dimension:
        if dimension not in swap_dict: raise UnidentifiedDimension(dimension)

    for dimension, chunks in groups_by_dimension.items():
        groups_coords_by_dimension[dimension] = selector.combine_and_group(chunks)

    del groups_by_dimension

    t = time.time()
    src.get_server().broadcast(tr("prompt_msg.backup.start"))
    server_data = GetServerData()
    server_data.get_saved_info()

    region_obj.cfg = cfg
    region_obj.backup_type = "custom"
    if len(src.get_info().content.split()) == 5 and src.get_info().content.split()[3] == "-s":
        region_obj.backup_path = cfg.static_backup_path
    else:
        region_obj.backup_path = cfg.backup_path
    region_obj.dimension = list(groups_coords_by_dimension.keys())
    for dimension, chunks in groups_coords_by_dimension.items():
        region_obj.world_name.append(swap_dict[dimension]["world_name"])
        region_obj.region_folder.append(swap_dict[dimension]["region_folder"])
        region_obj.coords.append(chunks)
    region_obj.organize_slot()
    region_obj.copy()
    region_obj.save_custom_info_file(custom_dict[dic["custom_name"]], src)
    t1 = time.time()
    src.get_server().broadcast(
        tr("prompt_msg.backup.done", f"{(t1 - t):.2f}")
    )
    src.get_server().broadcast(
        tr("prompt_msg.backup.custom_time", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
           f"{dic['custom_name']}")
    )


@new_thread("cb_custom_make")
@check_backup_state
def cb_custom_make(src: InfoCommandSource, dic: dict, custom=True):
    global server_data, custom_dict
    region.backup_state = 1

    if dic["custom_name"] not in custom_dict:
        raise UnidentifiedCustom(dic["custom_name"])

    if not src.get_info().is_player:
        raise NoPlayer

    swap_dict = region.swap_dimension_key(dimension_info)
    server_data = GetServerData(src.get_info().player)
    server_data.get_player_info(end=True)
    if not (server_data.dimension in swap_dict):
        raise UnidentifiedDimension(server_data.dimension)
    radius = dic["radius"]
    info = sub_slot_info.get_default().serialize()
    selected = selector(((
                             (server_data.coord[0], server_data.coord[-1]), radius
                         ),), max_chunk_size=cfg.max_chunk_length)
    info["time_created"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info["backup_dimension"] = server_data.dimension
    info["user_created"] = src.get_info().player
    info["user_pos"] = " ".join([str(i) for i in server_data.coord])
    info["backup_type"] = "chunk"
    info["chunk_top_left_pos"] = selected.corner_chunks["top_left"]
    info["chunk_bottom_right_pos"] = selected.corner_chunks["bottom_right"]
    info["command"] = src.get_info().content
    info["comment"] = dic.get("comment", tr("prompt_msg.comment.empty_comment"))
    info["chunk"] = selected
    sub = sort_dict(custom_dict[dic["custom_name"]]["sub_slot"])
    custom_dict[dic["custom_name"]]["sub_slot"] = sub.insert_value(info)
    src.reply(tr("prompt_msg.custom.create_sub_slot_success", len(custom_dict[dic["custom_name"]]["sub_slot"])))


@new_thread("cb_custom_pmake")
@check_backup_state
def cb_custom_pmake(src: InfoCommandSource, dic: dict, custom=True):
    region.backup_state = 1

    if dic["custom_name"] not in custom_dict:
        raise UnidentifiedCustom(dic["custom_name"])

    coord = ((dic["x1"], dic["z1"]), (dic["x2"], dic["z2"]))
    dic["comment"] = dic.get("comment", tr("prompt_msg.comment.empty_comment"))
    if str(dic["dimension_int"]) not in dimension_info:
        raise InputDimError
    info = sub_slot_info.get_default().serialize()
    selected = selector(coord, max_chunk_size=cfg.max_chunk_length)
    info["time_created"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info["backup_dimension"] = dimension_info[str(dic["dimension_int"])]["dimension"]
    info["user_created"] = src.get_info().player if src.get_info().is_player else tr("prompt_msg.comment.console")
    info["backup_type"] = "chunk"
    info["chunk_top_left_pos"] = selected.corner_chunks["top_left"]
    info["chunk_bottom_right_pos"] = selected.corner_chunks["bottom_right"]
    info["command"] = src.get_info().content
    info["comment"] = dic.get("comment", tr("prompt_msg.comment.empty_comment"))
    info["chunk"] = selected
    sub = sort_dict(custom_dict[dic["custom_name"]]["sub_slot"])
    custom_dict[dic["custom_name"]]["sub_slot"] = sub.insert_value(info)
    src.reply(tr("prompt_msg.custom.create_sub_slot_success", len(custom_dict[dic["custom_name"]]["sub_slot"])))


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
    selector_obj = selector(((
                    (server_data.coord[0], server_data.coord[-1]), radius
                    ),), max_chunk_size=cfg.max_chunk_length)
    selected = selector_obj.group_by_region()
    region_obj.src = src
    region_obj.cfg = cfg
    region_obj.coords.append(selected)
    region_obj.selector_obj = selector_obj
    region_obj.dimension.append(server_data.dimension)
    region_obj.world_name.append(swap_dict[server_data.dimension]["world_name"])
    region_obj.region_folder.append(swap_dict[server_data.dimension]["region_folder"])
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
    selector_obj = selector(coord, max_chunk_size=cfg.max_chunk_length)
    selected = selector_obj.group_by_region()
    t = time.time()
    src.get_server().broadcast(tr("prompt_msg.backup.start"))
    server_data = GetServerData()
    server_data.get_saved_info()
    region_obj.src = src
    region_obj.cfg = cfg
    region_obj.dimension.append(dimension_info[str(dic["dimension_int"])]["dimension"])  # 此处暂时这样写，后续必须改进
    region_obj.world_name.apeend(dimension_info[str(dic["dimension_int"])]["world_name"])
    region_obj.region_folder.append(dimension_info[str(dic["dimension_int"])]["region_folder"])
    region_obj.backup_path = region.get_backup_path(cfg, src.get_info().content)
    region_obj.coords.append(selected)
    region_obj.selector_obj = selector_obj
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

    if "sub_slot_groups" in dic:

        if info["backup_type"] != "custom":
            raise NotCustom(dic["slot"])
        parts = re.split(r'[,，]', dic["sub_slot_groups"])
        slots = []
        for part in parts:
            # 检查是否为空
            if not part: raise InvalidInput
            # 检查是否为纯数字
            if not part.isdigit(): raise InvalidInput
            # 检查前导零
            if len(part) > 1 and part[0] == '0': raise InvalidInput
            # 转换为整数并检查数值范围
            num = int(part)
            if num < 1: raise InvalidInput
            slots.append(num)

        if len(slots) != len(set(slots)): raise InputSlotRepeat
        for slot in slots:
            if str(slot) not in info["sub_slot"]:
                region_obj = None
                raise UnidentifiedSubSlot(slot)

        sub_slots = info["sub_slot"]
        dimension = set()
        for _slot in slots:
            dimension.add(sub_slots[str(_slot)]["backup_dimension"])

        region_obj.dimension = list(dimension)
        groups_by_dimension = {}
        groups_coords_by_dimension = {}
        for _slot in slots:
            dim = sub_slots[str(_slot)]["backup_dimension"]
            chunk1 = tuple(sub_slots[str(_slot)]["chunk_top_left_pos"])
            chunk2 = tuple(sub_slots[str(_slot)]["chunk_bottom_right_pos"])
            chunk = selector.from_chunk_coords(chunk1, chunk2, ignore_size_limit=True)
            groups_by_dimension.setdefault(dim, []).append(chunk)

        for dim, chunks in groups_by_dimension.items():
            groups_coords_by_dimension[dim] = selector.combine_and_group(chunks)

        region_obj.coords = groups_coords_by_dimension

        del groups_by_dimension

        region_obj.sub_slot_groups = True

    if info["backup_type"] == "custom": region_obj.custom_back = True

    ext = [".mca", ".region"]
    obj_slot = analyzer(os.path.join(region_obj.backup_path, region_obj.slot))
    obj_slot.scan_by_extension(ext, include_subdirs=True)
    if not obj_slot.get_ext_report():
        raise LackRegionFile

    time_saved = info["time"]
    src.reply(
        Message.get_json_str(
            "\n".join(
    [
        tr("prompt_msg.back.start" if info["backup_type"] != "custom" else "prompt_msg.back.custom_start", region_obj.slot.replace("slot", "", 1), time_saved, info["comment"] if info["backup_type"] != "custom" else info["custom_name"]),
        tr("prompt_msg.back.click", Prefix)
    ]
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


@new_thread("chunk_backup")
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


@new_thread("cb_del")
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
        source.get_server().reload_plugin("region_backup")
        source.reply(tr("prompt_msg.set.done"))

    except Exception:
        source.reply(tr("error.unknown_error", traceback.format_exc()))


@new_thread("cb_show")
def cb_show(src: InfoCommandSource, dic: dict):
    args = src.get_info().content.split()
    is_overwrite = (args[-1] == "overwrite")
    backup_path = cfg.backup_path if is_overwrite else region.get_backup_path(cfg, src.get_info().content)
    name = "overwrite" if is_overwrite else f"slot{dic.get('slot', 1)}"
    info_path = os.path.join(backup_path, name, "info.json")
    if not os.path.exists(info_path):
        src.reply(tr("prompt_msg.show.empty", dic["slot"] if dic else (name if name == "overwrite" else 1)))
        return

    try:
        info = safe_load_json(info_path)
        if "page" in dic:
            if info["backup_type"] != "custom":
                src.reply(tr("prompt_msg.show.not_custom", dic.get('slot', 1)))
                return
            p = dic["page"]
            num = len(info["sub_slot"])
            if not num:
                src.reply(tr("prompt_msg.custom.empty_sub_slot", info["custom_name"]))
                return
            page = math.ceil(num / 10)
            if p > page:
                src.reply(tr("prompt_msg.list.out_page"))
                return
            start = 10 * (p - 1) + 1
            end = num if 10 * (p - 1) + 1 <= num <= 10 * p else 10 * p
            lp = p - 1 if p > 1 else 0
            np = p + 1 if p + 1 <= page else 0

        if "sub_slot" not in dic:
            size = analyzer(os.path.join(backup_path, name))
            size.scan_all_files(include_subdirs=True)
            total = size.get_full_report()["all_files"]["total_size_human"]

        if info["backup_type"] == "custom":
            sub_slots = info["sub_slot"]
            if "sub_slot" in dic:
                sub_slot = sub_slots.get(str(dic["sub_slot"]))
                if not sub_slot:
                    src.reply(tr("prompt_msg.custom.unidentified_sub_slot", dic["sub_slot"]))
                    return

                msg_components = [
                    tr("prompt_msg.show.sub_title"),
                    tr("prompt_msg.custom.show.parent", info["custom_name"]),
                    tr("prompt_msg.show.backup_type", sub_slot["backup_type"]),
                    tr("prompt_msg.show.user_saved", info["user"]),
                    tr("prompt_msg.custom.show.user_created", sub_slot["user_created"]),
                    tr("prompt_msg.show.time_saved", info["time"]),
                    tr("prompt_msg.custom.show.time_created", sub_slot["time_created"]),
                    tr("prompt_msg.show.backup_dimension", sub_slot["backup_dimension"]),
                    tr("prompt_msg.show.user_pos", sub_slot["user_pos"]) if "user_pos" in sub_slot else tr(
                        "prompt_msg.show.no_pos"),
                    tr("prompt_msg.show.chunk_top_left_pos",
                       ", ".join([str(x) for x in sub_slot["chunk_top_left_pos"]])),
                    tr("prompt_msg.show.chunk_bottom_right_pos",
                       ", ".join([str(x) for x in sub_slot["chunk_bottom_right_pos"]])),
                    tr("prompt_msg.show.comment", sub_slot["comment"]),
                    tr("prompt_msg.show.command", sub_slot["command"]),
                    tr("prompt_msg.show.version_saved", info["version_saved"]),
                    tr("prompt_msg.show.version_created", sub_slot["version_created"]),
                    tr("prompt_msg.show.minecraft_version", info["minecraft_version"]),
                ]

            else:
                num = len(sub_slots)
                if "page" not in dic:
                    p = 1
                    page = math.ceil(num / 10)
                    start = 10 * (p - 1) + 1
                    end = num if 10 * (p - 1) + 1 <= num <= 10 * p else 10 * p
                    lp = p - 1 if p > 1 else 0
                    np = p + 1 if p + 1 <= page else 0
                # noinspection PyUnboundLocalVariable
                msg_components = [
                    tr("prompt_msg.show.title"),
                    tr("prompt_msg.show.custom_name", info["custom_name"]),
                    tr("prompt_msg.show.backup_type", info["backup_type"]),
                    tr("prompt_msg.show.user_saved", info["user"]),
                    tr("prompt_msg.custom.show.user_created", info["user_created"]),
                    tr("prompt_msg.show.time_saved", info["time"]),
                    tr("prompt_msg.custom.show.time_created", info["time_created"]),
                    tr("prompt_msg.show.backup_dimension", ", ".join(info["backup_dimension"])),
                    tr("prompt_msg.show.size", total),
                    tr("prompt_msg.show.version_saved", info["version_saved"]),
                    tr("prompt_msg.show.version_created", info["version_created"]),
                    tr("prompt_msg.show.minecraft_version", info["minecraft_version"]),
                    tr("prompt_msg.custom.show.sub_title")
                ]

                if num:

                    slots = list(sub_slots.keys())

                    # noinspection PyUnboundLocalVariable
                    for index in range(start - 1, end):
                        key, value = slots[index], sub_slots[slots[index]]
                        if index < num - 1:
                            msg_components.append(
                                tr("prompt_msg.show.sub_slot", dic.get('slot', 1), key, Prefix, value["comment"]))
                        else:
                            msg_components.append(
                                tr("prompt_msg.show.end_sub_slot", dic.get('slot', 1), key, Prefix, value["comment"]))

                    # noinspection PyUnboundLocalVariable
                    if lp:
                        # noinspection PyUnboundLocalVariable
                        msg = tr("prompt_msg.show.last_page", p, lp, dic.get('slot', 1), Prefix)
                        # noinspection PyUnboundLocalVariable
                        if np:
                            # noinspection PyUnboundLocalVariable
                            msg = msg + "  " + tr("prompt_msg.show.next_page", p, np, dic.get('slot', 1), Prefix)
                        msg = msg + "  " + tr("prompt_msg.list.page", end, num)
                        msg_components.append(msg)
                    elif np:
                        # noinspection PyUnboundLocalVariable
                        msg = tr("prompt_msg.show.next_page", p, np, dic.get('slot', 1), Prefix)
                        msg = msg + "  " + tr("prompt_msg.list.page", end, num)
                        msg_components.append(msg)

        else:
            if "sub_slot" in dic:
                src.reply(tr("prompt_msg.show.not_custom", dic.get('slot', 1)))
                return
            # noinspection PyUnboundLocalVariable
            msg_components = [
                tr("prompt_msg.show.title"),
                tr("prompt_msg.show.time_saved", info["time"]),
                tr("prompt_msg.show.backup_type", info["backup_type"]),
                tr("prompt_msg.show.backup_dimension", ", ".join(info["backup_dimension"])),
                tr("prompt_msg.show.user_saved", info["user"]),
                tr("prompt_msg.show.user_pos", info["user_pos"]) if "user_pos" in info else tr(
                    "prompt_msg.show.no_pos"),
                tr("prompt_msg.show.comment", info["comment"]),
                tr("prompt_msg.show.command", info["command"]),
                tr("prompt_msg.show.size", total),
                tr("prompt_msg.show.version_saved", info["version_created"]),
            ]

            if "minecraft_version" in info:
                msg_components.append(tr("prompt_msg.show.minecraft_version", info["minecraft_version"]))

            if "chunk_bottom_right_pos" in info:
                msg_components.append(tr("prompt_msg.show.chunk_top_left_pos", ", ".join([str(x) for x in info["chunk_top_left_pos"]])))

            if "chunk_bottom_right_pos" in info:
                msg_components.append(tr("prompt_msg.show.chunk_bottom_right_pos", ", ".join([str(x) for x in info["chunk_bottom_right_pos"]])))

        # noinspection PyUnboundLocalVariable
        src.reply(Message.get_json_str("\n".join(msg_components)))

    except Exception:
        src.reply(tr("error.unknown_error", traceback.format_exc()))


@new_thread("cb_list")
def cb_list(source: InfoCommandSource, dic: dict):
    backup_path = region.get_backup_path(cfg, source.get_info().content)
    dynamic = (backup_path == cfg.backup_path)
    region._ensure_backup_dirs(cfg)
    slot_list = region._get_sorted_slots(backup_path, numeric_only=True)
    num = len(slot_list)
    if not slot_list:
        source.reply(tr("prompt_msg.list.empty_slot"))
        return

    p = 1 if not dic else dic["page"]
    page = math.ceil(num / 10)
    if p > page:
        source.reply(tr("prompt_msg.list.out_page"))
        return
    msg_list = [tr("prompt_msg.list.dynamic") if dynamic else tr("prompt_msg.list.static")]
    start = 10 * (p - 1) + 1
    end = num if 10 * (p - 1) + 1 <= num <= 10 * p else 10 * p
    lp = p - 1 if p > 1 else 0
    np = p + 1 if p + 1 <= page else 0

    try:
        for i in slot_list[start - 1:end]:
            name = f"slot{i}"
            path = os.path.join(backup_path, name, "info.json")
            if os.path.exists(path):
                try:
                    info = safe_load_json(path)
                except Exception:
                    msg = tr("prompt_msg.list.info_broken", i)
                    msg_list.append(msg)
                    continue

                time_saved = info["time"]
                dimension = ",".join(info['backup_dimension'])
                user_saved = info["user"]
                size_slot = analyzer(os.path.join(backup_path, name))
                size_slot.scan_all_files(include_subdirs=True)
                backup_type = info["backup_type"]
                if backup_type == "custom":
                    custom_name = info["custom_name"]
                    msg = tr(
                        "prompt_msg.list.custom_slot", i, size_slot.get_full_report()["all_files"]["total_size_human"],
                        time_saved, custom_name, " -s" if not dynamic else "", dimension, user_saved, Prefix
                    )

                else:
                    comment = info["comment"]
                    command = info["command"]
                    msg = tr(
                        "prompt_msg.list.slot", i, size_slot.get_full_report()["all_files"]["total_size_human"],
                        time_saved,
                        comment, " -s"
                        if not dynamic else "", dimension, user_saved, command, Prefix
                    )

                msg_list.append(msg)

            else:
                msg = tr("prompt_msg.list.empty_size", i)
                msg_list.append(msg)

        if lp:
            msg = tr("prompt_msg.list.last_page", p, lp, " -s" if not dynamic else "", Prefix)
            if np:
                msg = msg + "  " + tr("prompt_msg.list.next_page", p, np, " -s" if not dynamic else "", Prefix)
            msg = msg + "  " + tr("prompt_msg.list.page", end, num)
            msg_list.append(msg)
        elif np:
            msg = tr("prompt_msg.list.next_page", p, np, " -s" if not dynamic else "", Prefix)
            msg = msg + "  " + tr("prompt_msg.list.page", end, num)
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
    source.get_server().execute(data_getter["auto_save_on"])
    source.reply(tr("prompt_msg.reload.done"))
    source.get_server().reload_plugin("chunk_backup")


# 消息监听器
def on_info(server: PluginServerInterface, info: Info):
    if not server_data or region_obj:
        return

    if not info.is_from_server:
        return

    if server_data.index == 1:
        # 处理坐标获取
        if not server_data.coord:
            pos = re.match(data_getter["get_pos_regex"].format(name=server_data.player), info.content)
            if pos:
                server_data.coord = [float(pos.group('x')), float(pos.group('y')), float(pos.group('z'))]

        # 处理维度获取
        elif not server_data.dimension:
            dim = re.match(data_getter["get_dimension_regex"].format(name=server_data.player), info.content)
            if dim:
                server_data.dimension = dim.group('dimension')
        return

    if server_data.index == 3 and info.content == data_getter["save_off_regex"]:
        server_data.save_off = 1
        return

    if server_data.index == 4 and info.content == data_getter["saved_world_regex"]:
        server_data.save_all = 1


def on_load(server: PluginServerInterface, old):
    global cfg, dimension_info, Prefix, server_data, region_obj, data_getter

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
    dimension_info = cfg.dimension_info
    data_getter = cfg.data_getter

    server.register_help_message(Prefix, tr("introduction.register_message"))
    lvl = cfg.minimum_permission_level
    require = Requirements()
    builder = SimpleCommandBuilder()

    builder.command(f"{Prefix}", print_help_msg)
    builder.command(f"{Prefix} help", print_help_msg)
    builder.command(f"{Prefix} custom create <custom_name>", cb_custom_create)
    builder.command(f"{Prefix} custom list", cb_custom_list)
    builder.command(f"{Prefix} custom list <page>", cb_custom_list)
    builder.command(f"{Prefix} custom show <custom_name> page <page>", cb_custom_show)
    builder.command(f"{Prefix} custom show <custom_name>", cb_custom_show)
    builder.command(f"{Prefix} custom show <custom_name> <sub_slot>", cb_custom_show)
    builder.command(f"{Prefix} custom del <custom_name>", cb_custom_del)
    builder.command(f"{Prefix} custom del <custom_name> <sub_slot>", cb_custom_del)
    builder.command(f"{Prefix} custom save <custom_name>", cb_custom_save)
    builder.command(f"{Prefix} custom save -s <custom_name>", cb_custom_save)
    builder.command(f"{Prefix} custom make <custom_name> <radius>", cb_custom_make)
    builder.command(f"{Prefix} custom make <custom_name> <radius> <comment>", cb_custom_make)
    builder.command(f"{Prefix} custom pmake <custom_name> <x1> <z1> <x2> <z2> in <dimension_int>", cb_custom_pmake)
    builder.command(f"{Prefix} custom pmake <custom_name> <x1> <z1> <x2> <z2> in <dimension_int> <comment>",
                    cb_custom_pmake)
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
    builder.command(f"{Prefix} back <slot> <sub_slot_groups>", cb_back)
    builder.command(f"{Prefix} back -s", cb_back)
    builder.command(f"{Prefix} back -s <slot>", cb_back)
    builder.command(f"{Prefix} back -s <slot> <sub_slot_groups>", cb_back)
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
    builder.command(f"{Prefix} show <slot>", cb_show)
    builder.command(f"{Prefix} show <slot> page <page>", cb_show)
    builder.command(f"{Prefix} show <slot> <sub_slot>", cb_show)
    builder.command(f"{Prefix} show -s", cb_show)
    builder.command(f"{Prefix} show -s <slot>", cb_show)
    builder.command(f"{Prefix} show -s <slot> page <page>", cb_show)
    builder.command(f"{Prefix} show -s <slot> <sub_slot>", cb_show)
    builder.command(f"{Prefix} show overwrite", cb_show)
    builder.command(f"{Prefix} reload", cb_reload)
    builder.command(f"{Prefix} force_reload", cb_force_reload)

    builder.arg("x1", Number)
    builder.arg("z1", Number)
    builder.arg("x2", Number)
    builder.arg("z2", Number)
    builder.arg("dimension", Text)
    builder.arg("custom_name", Text)
    builder.arg("dimension_int", Integer)
    builder.arg("length", lambda length: Integer(length).at_min(1))
    builder.arg("sub_slot", lambda sub_slot: Integer(sub_slot).at_min(1))
    builder.arg("radius", lambda radius: Integer(radius).at_min(0))
    builder.arg("comment", GreedyText)
    builder.arg("slot", lambda s: Integer(s).at_min(1))
    builder.arg("page", lambda page: Integer(page).at_min(1))
    builder.arg("sub_slot_groups", Text)

    for literal in cb_config.minimum_permission_level:
        permission = lvl[literal]
        builder.literal(literal).requires(
            require.has_permission(permission),
            failure_message_getter=lambda err: tr("prompt_msg.lack_permission")
        )

    builder.register(server)
