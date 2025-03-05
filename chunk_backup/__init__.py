import datetime
from glob import glob
import json
import os
from queue import Full
import re
import shutil
import time
import math
import copy
import traceback

from concurrent.futures import ThreadPoolExecutor
from mcdreforged.api.all import *
from chunk_backup.config import cp_info, cp_config
from chunk_backup.json_message import Message

Prefix = '!!cp'
cfg = cp_config
cfg_path = os.path.join(".", "config", "Chunk_Backup.json")
server_path = cfg.server_path
dimension_info = cfg.dimension_info
data = None
time_out = 5
countdown = 10











def print_help_msg(source: InfoCommandSource):
    if len(source.get_info().content.split()) < 2:
        source.reply(Message.get_json_str(tr("help_message", Prefix, "Region BackUp", cp_config.plugin_version)))
        source.get_server().execute_command("!!cp list", source)

    else:
        source.reply(Message.get_json_str(tr("full_help_message", Prefix)))


@new_thread("cp_make")
def cp_make(source: InfoCommandSource, dic: dict):
    global data
    try:
        if not source.get_info().is_player:
            source.reply(tr("backup_error.source_error"))
            return

        if not region.backup_state:
            region.backup_state = 1
            if "comment" not in dic:
                dic["comment"] = tr("comment.empty_comment")
            radius = dic["radius"]
            t = time.time()
            source.get_server().broadcast(tr("backup.start"))
            data = player_info(source)
            if not data.get_player_info():
                data = None
                region.backup_state = None
                source.get_server().execute("save-on")
                source.reply(tr("backup_error.timeout"))
                return
            _data = copy.copy(data)
            data = None
            backup_path = region.get_backup_path(source.get_info().content)
            is_more = region.organize_slot(backup_path, 1)
            if is_more:
                region.backup_state = None
                source.get_server().execute("save-on")
                source.get_server().broadcast(is_more)
                return
            coord = region.coordinate_transfer(_data.coordinate[:1] + _data.coordinate[2:], radius)
            if region.copy(_data.dimension, backup_path, coord):
                region.backup_state = None
                source.get_server().execute("save-on")
                source.get_server().broadcast(tr("config_error"))
                return
            region.save_info_file(_data.dimension, backup_path, source.get_info().content, dic["comment"], src=source)
            t1 = time.time()
            source.get_server().broadcast(tr("backup.done", f"{(t1 - t):.2f}"))
            source.get_server().broadcast(
                tr("backup.date", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
            )
            source.get_server().execute("save-on")
            region.backup_state = None
            return

    except Exception:
        data = None
        region.backup_state = None
        source.reply(tr("backup_error.unknown_error", traceback.format_exc()))
        source.get_server().execute("save-on")
        return

    source.reply(tr("backup_error.repeat_backup"))


@new_thread("cp_pos_make")
def cp_pos_make(source: InfoCommandSource, dic: dict):
    global data
    try:
        if not region.backup_state:
            region.backup_state = 1
            x1, z1, x2, z2 = dic["x1"], dic["z1"], dic["x2"], dic["z2"]
            if "comment" not in dic:
                dic["comment"] = tr("comment.empty_comment")

            if str(dic["dimension_int"]) not in dimension_info:
                region.backup_state = None
                source.reply(tr("backup_error.dim_error"))
                return
            t = time.time()
            source.get_server().broadcast(tr("backup.start"))
            data = player_info(source)
            if not data.get_save_info():
                data = None
                region.backup_state = None
                source.get_server().execute("save-on")
                source.reply(tr("backup_error.timeout"))
                return
            data = None
            backup_path = region.get_backup_path(source.get_info().content)
            is_more = region.organize_slot(backup_path, 1)
            if is_more:
                region.backup_state = None
                source.get_server().execute("save-on")
                source.get_server().broadcast(is_more)
                return
            coord = region.coordinate_transfer(
                [(int(x1 // 512), int(x2 // 512)), (int(z1 // 512), int(z2 // 512))]
                , command="pos_make"
            )
            if region.copy(str(dic["dimension_int"]), backup_path, coord):
                region.backup_state = None
                source.get_server().execute("save-on")
                source.reply(tr("config_error"))
                return
            region.save_info_file(
                dimension_info[str(dic["dimension_int"])]["dimension"],
                backup_path, source.get_info().content,
                dic["comment"], src=source
            )
            t1 = time.time()
            source.get_server().broadcast(tr("backup.done", f"{(t1 - t):.2f}"))
            source.get_server().broadcast(
                tr("backup.date", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
            )
            source.get_server().execute("save-on")
            region.backup_state = None
            return

    except Exception:
        data = None
        region.backup_state = None
        source.reply(tr("backup_error.unknown_error", traceback.format_exc()))
        source.get_server().execute("save-on")
        return

    source.reply(tr("backup_error.repeat_backup"))


@new_thread("cp_dim_make")
def cp_dim_make(source: InfoCommandSource, dic: dict):
    global data
    try:
        if not region.backup_state:
            region.backup_state = 1
            if "comment" not in dic:
                dic["comment"] = tr("comment.empty_comment")

            res = re.findall(r'-\d+|\d+', dic["dimension"])
            dimension = [s for s in res]
            if len(dimension) != len(set(dimension)):
                region.backup_state = None
                source.reply(tr("backup_error.dim_repeat"))
                return

            for dim in dimension:
                if dim not in dimension_info:
                    region.backup_state = None
                    source.reply(tr("backup_error.dim_error"))
                    return
            t = time.time()
            source.get_server().broadcast(tr("backup.start"))
            data = player_info(source)
            if not data.get_save_info():
                data = None
                region.backup_state = None
                source.get_server().execute("save-on")
                source.reply(tr("backup_error.timeout"))
                return
            data = None
            backup_path = region.get_backup_path(source.get_info().content)
            is_more = region.organize_slot(backup_path, 1)
            if is_more:
                region.backup_state = None
                source.get_server().execute("save-on")
                source.get_server().broadcast(is_more)
                return
            for dim in dimension:
                if region.copy(dim, backup_path):
                    region.backup_state = None
                    source.get_server().execute("save-on")
                    source.reply(tr("config_error"))
                    return
            dimension = [dimension_info[d]["dimension"] for d in dimension]
            region.save_info_file(dimension, backup_path, source.get_info().content, dic["comment"], src=source)
            t1 = time.time()
            source.get_server().broadcast(tr("backup.done", f"{(t1 - t):.2f}"))
            source.get_server().broadcast(
                tr("backup.date", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"{dic['comment']}")
            )
            source.get_server().execute("save-on")
            region.backup_state = None
            return

    except Exception:
        data = None
        region.backup_state = None
        source.reply(tr("backup_error.unknown_error", traceback.format_exc()))
        source.get_server().execute("save-on")
        return

    source.reply(tr("backup_error.repeat_backup"))


@new_thread("cp_back")
def cp_back(source: InfoCommandSource, dic: dict):
    if region.back_state is None:
        region.back_state = 0
        try:
            backup_path = region.get_backup_path(source.get_info().content)
            if not dic:
                if source.get_info().content.split()[1] == "restore":
                    dic["slot"] = cfg.overwrite_backup_folder
                else:
                    dic["slot"] = "slot1"
            else:
                dic["slot"] = f"slot{dic['slot']}"
            if not os.path.exists(os.path.join(backup_path, dic["slot"], "info.json")):
                region.back_state = None
                source.reply(tr("back_error.lack_info"))
                return
            if not region.get_total_size([
                os.path.join(
                    backup_path, dic["slot"], i) for i in os.listdir(
                    os.path.join(
                        backup_path, dic["slot"]
                    )
                )
                if os.path.isdir(os.path.join(backup_path, dic["slot"], i))
            ])[-1]:
                source.reply(tr("back_error.lack_region"))
                return
            with open(os.path.join(backup_path, dic["slot"], "info.json"), "cp") as fp:
                buffer = fp.read()
                content = buffer.decode('utf-8') if buffer[:3] != b'\xef\xbb\xbf' else buffer[3:].decode('utf-8')
                info = json.loads(content)

            t = info["time"]
            comment = info["comment"]

            source.reply(
                Message.get_json_str(
                    "\n".join([tr("back.start", dic["slot"].replace("slot", "", 1), t, comment), tr("back.click")]))
            )
            t1 = time.time()
            while not region.back_state:
                if time.time() - t1 > countdown:
                    source.reply(tr("back_error.timeout"))
                    region.back_state = None
                    return
                time.sleep(0.01)

            if region.back_state is True:
                source.reply(tr("back.abort"))
                region.back_state = None
                return
            source.get_server().broadcast(tr("back.countdown", countdown))

            for stop_time in range(1, countdown):
                time.sleep(1)
                if region.back_state is True:
                    region.back_state = None
                    source.reply(tr("back.abort"))
                    return
                source.get_server().broadcast(
                    Message.get_json_str(
                        tr("back.count", f"{countdown - stop_time}", dic["slot"].replace("slot", "", 1))
                    )
                )
            region.back_slot = dic["slot"]
            region.save_backup_path_(backup_path)
            source.get_server().stop()
            return

        except Exception:
            region.back_state = None
            region.save_backup_path_(None)
            source.reply(tr("back_error.unknown_error", traceback.format_exc()))
            return

    source.reply(tr("back_error.repeat_back"))


def cp_abort(source: CommandSource):
    # 当前操作备份信息
    if region.back_state is None:
        source.reply(tr("abort"))
        return
    region.back_state = True


def cp_confirm(source: CommandSource):
    if region.back_state is None:
        source.reply(tr("confirm"))
        return
    region.back_state = 1


def on_server_stop(server: PluginServerInterface, server_return_code: int):
    try:
        if region.back_slot:
            if server_return_code != 0:
                region.clear()
                server.logger.error(tr("back_error.server_error"))
                return
            server.logger.info(tr("back.run"))

            backup_path = region.get_backup_path_()
            update_single_slot(os.path.join(backup_path, region.back_slot))
            with open(os.path.join(backup_path, region.back_slot, "info.json"), "cp") as fp:
                buffer = fp.read()
                content = buffer.decode('utf-8') if buffer[:3] != b'\xef\xbb\xbf' else buffer[3:].decode('utf-8')
                info = json.loads(content)

            dimension = info["backup_dimension"].split(",")
            all_dimension = [d for d in dimension_info.values()]
            if not all(i in [v["dimension"] for v in all_dimension] for i in dimension):
                region.clear()
                server.logger.error(tr("back_error.wrong_dim"))
                return

            region_folder = {}
            dimension = set(dimension)  # 转换为集合，自动去重
            for v in all_dimension:
                if v["dimension"] in dimension:  # 直接检查是否在集合中
                    region_folder[v["dimension"]] = [v["world_name"], v["region_folder"]]

            region.back(region_folder)
            region.clear()
            server.start()

    except Exception:
        region.clear()
        server.logger.error(tr("back_error.unknown_error", traceback.format_exc()))
        return


def cp_del(source: InfoCommandSource, dic: dict):
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
        return


def cp_list(source: InfoCommandSource, dic: dict):
    backup_path = region.get_backup_path(source.get_info().content)
    dynamic = (backup_path == cfg.backup_path)
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
                with open(path, "cp") as fp:
                    buffer = fp.read()
                    content = buffer.decode('utf-8') if buffer[:3] != b'\xef\xbb\xbf' else buffer[3:].decode('utf-8')
                    info = json.loads(content)
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
        dynamic_ = region.get_total_size([cfg.backup_path])[-1]
        static_ = region.get_total_size([cfg.static_backup_path])[-1]
        msg = tr(
            "list.total_size", region.convert_bytes(dynamic_),
            region.convert_bytes(static_), region.convert_bytes(dynamic_ + static_)
        )
        source.reply(msg)

    except Exception:
        source.reply(tr("list_error", traceback.format_exc()))
        return


def update_single_slot(slot):
    info_path = os.path.join(slot, "info.json")
    if not os.path.exists(info_path):
        return

    with open(info_path, "cp") as fp:
        buffer = fp.read()
        content = buffer.decode('utf-8') if not buffer.startswith(b'\xef\xbb\xbf') \
            else buffer[3:].decode('utf-8')
        info = json.loads(content)

        if "version_created" not in info:
            info["version_created"] = cfg.plugin_version
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=4)
            world_path = os.path.join(slot, "world")
            os.makedirs(world_path, exist_ok=True)

            for folder in os.listdir(slot):
                folder_path = os.path.join(slot, folder)
                if os.path.isdir(folder_path) and folder != "world":
                    shutil.copytree(folder_path, os.path.join(world_path, folder))
                    shutil.rmtree(folder_path, ignore_errors=True)

            return True


def cp_update_slot(source: InfoCommandSource):
    count = 0
    source.reply(tr("update_slot.start"))

    for backup_path in [cfg.backup_path, cfg.static_backup_path]:
        if not os.path.exists(backup_path):
            continue

        pattern = re.compile(r'^(?:slot([1-9]\d*)|overwrite)$')
        slots = [
            os.path.join(backup_path, folder)
            for folder in os.listdir(backup_path)
            if os.path.isdir(os.path.join(backup_path, folder)) and pattern.match(folder)
        ]

        for slot in slots:
            if update_single_slot(slot):
                count += 1

    if count:
        source.reply(tr("update_slot.done", count))
    else:
        source.reply(tr("update_slot.non-need"))


def cp_reload(source: CommandSource):
    try:
        source.reply(tr("reload"))
        source.get_server().reload_plugin("chunk_backup")

    except Exception:
        source.reply(tr("reload_error", traceback.format_exc()))


def tr(key, *args):
    return ServerInterface.get_instance().tr(f"chunk_backup.{key}", *args)


def on_unload(server: PluginServerInterface):
    global cfg, data
    cfg = cp_config
    region.clear()
    data = None


def on_info(server: PluginServerInterface, info: Info):
    if isinstance(data, player_info):
        if info.content.startswith(f"{data.user} has the following entity data: ") and info.is_from_server:
            if not data.coordinate:
                data.coordinate = info.content.split(sep="entity data: ")[-1]
                return
            data.dimension = info.content.split(sep="entity data: ")[-1]

        if info.content.startswith("Saved the game") and info.is_from_server:
            data.save_off = 1
            return

        if info.content.startswith("Automatic saving is now disabled") and info.is_from_server:
            data.save_all = 1


class player_info:
    def __init__(self, src=None):
        self.src = src
        self.user = src.get_info().player if src else None
        self.coordinate = None
        self.dimension = None
        self.save_off = None
        self.save_all = None

    def get_player_info(self):
        global data
        self.src.get_server().execute(f"data get entity {self.user} Pos")
        self.src.get_server().execute(f"data get entity {self.user} Dimension")

        t1 = time.time()
        while not self.coordinate or not self.dimension:
            if time.time() - t1 > time_out:
                data = None
                return
            time.sleep(0.01)

        self.coordinate = [float(p.strip('d')) for p in self.coordinate.strip("[]").split(',')]
        self.dimension = self.dimension.strip('"')
        if not self.get_save_info():
            return
        return 1

    def get_save_info(self):
        global data
        self.src.get_server().execute("save-off")
        self.src.get_server().execute("save-all flush")

        t1 = time.time()
        while not self.save_off or not self.save_all:
            if time.time() - t1 > time_out:
                data = None
                return
            time.sleep(0.01)
        return 1


class region:
    backup_state = None
    back_state = None
    back_slot = None
    __backup_path = None

    @classmethod
    def clear(cls):
        if cls.back_state == 1:
            cls.__backup_path = None
        cls.backup_state = None
        cls.back_state = None
        cls.back_slot = None

    @classmethod
    def get_backup_path_(cls):
        return cls.__backup_path

    @classmethod
    def save_backup_path_(cls, backup_path):
        cls.__backup_path = backup_path

    @classmethod
    def get_backup_path(cls, command):
        if len(command.split()) > 2 and command.split()[2] == "-s":
            return cfg.static_backup_path
        return cfg.backup_path

    @classmethod
    def get_total_size(cls, folder_paths):
        """计算多个文件夹的总大小（多线程优化）"""
        total_size = 0
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(cls.get_folder_size, folder_path): folder_path for folder_path in folder_paths}
            for future in futures:
                try:
                    total_size += future.result()
                except Exception:
                    folder_path = futures[future]
                    ServerInterface.get_instance().logger.info(
                        f"计算§c{folder_path}§r的大小时出错:§e{traceback.format_exc()}")

        return cls.convert_bytes(total_size), total_size

    @classmethod
    def get_folder_size(cls, folder_path):
        """计算单个文件夹的大小"""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                try:
                    # 解析符号链接
                    real_path = os.path.realpath(file_path)
                    total_size += os.path.getsize(real_path)
                except (FileNotFoundError, PermissionError):
                    # 忽略无法访问的文件
                    continue

        return total_size

    @classmethod
    def convert_bytes(cls, size):
        """将字节数转换为人类可读的格式（如 KB、MB、GB）"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f}{unit}"
            size /= 1024

        return f"{size:.2f}PB"

    @classmethod
    def organize_slot(cls, backup_path=cfg.backup_path, rename=None):
        if not os.path.exists(backup_path):
            os.makedirs(backup_path)
        pattern = re.compile(r'^slot([1-9]\d*)$')
        slot_list = [
            i for i in os.listdir(backup_path) if os.path.isdir(os.path.join(backup_path, i)) and pattern.match(i)
        ]
        sorted_list = sorted(slot_list, key=lambda x: int(re.search(r'\d+', x).group()))
        temp = []

        def clear_temp():
            """清除临时文件夹的标记"""
            for i in temp:
                os.rename(os.path.join(backup_path, i), os.path.join(backup_path, i.strip("_temp")))

        def rename_slots(index=1):
            """重命名文件夹"""
            for i, v in zip(range(len(sorted_list) - 1, -1, -1), reversed(sorted_list)):
                new_name = f"slot{i + index}"
                if v == new_name:
                    continue

                if i > 0 and new_name in sorted_list:
                    temp.append(f"{new_name}_temp")
                    os.rename(os.path.join(backup_path, v), os.path.join(backup_path, f"{new_name}_temp"))
                else:
                    os.rename(os.path.join(backup_path, v), os.path.join(backup_path, new_name))

        if rename:
            max_slots = cfg.static_slot if backup_path != cfg.backup_path else cfg.slot

            if len(sorted_list) > max_slots:
                msg = tr(
                    "backup_error.static_more_than", max_slots, len(sorted_list)
                ) if backup_path != cfg.backup_path else tr(
                    "backup_error.dynamic_more_than", max_slots, len(sorted_list)
                )

                return msg

            if len(sorted_list) == max_slots:
                if backup_path != cfg.backup_path:
                    return tr("backup_error.static_more_than", max_slots, len(sorted_list))
                shutil.rmtree(os.path.join(backup_path, f"slot{max_slots}"), ignore_errors=True)
                sorted_list.pop()

            if slot_list:
                rename_slots(2)
                clear_temp()

            os.makedirs(os.path.join(backup_path, "slot1"), exist_ok=True)
            return

        if slot_list:
            rename_slots()
            clear_temp()

        return len(
            [i for i in os.listdir(backup_path) if os.path.isdir(os.path.join(backup_path, i)) and pattern.match(i)]
        )

    @classmethod
    def save_info_file(cls, dimension, backup_path=cfg.backup_path, command=None,
                       comment=None, _slot="slot1", src=None
                       ):
        info_path = os.path.join(backup_path, _slot, "info.json")
        info = cp_info.get_default().serialize()
        info["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        info["backup_dimension"] = dimension if not isinstance(
            dimension, list) else ",".join([str(s) for s in dimension]
                                           )
        info["user"] = src.get_info().player if src else tr("comment.console")
        info["command"] = command
        info["comment"] = comment

        with open(info_path, "w", encoding="utf-8") as fp:
            json.dump(info, fp, ensure_ascii=False, indent=4)

    @classmethod
    def coordinate_transfer(cls, raw_coordinate, r=0, command="make"):
        if command == "make":
            x, z = raw_coordinate
            return cls.coordinate_transfer(
                [
                    (int(x // 16 - r) // 32, int(x // 16 + r) // 32), (int(z // 16 + r) // 32, int(z // 16 - r) // 32)
                ],
                command="pos_make"
            )

        elif command == "pos_make":
            coordinate = []
            left = min((raw_coordinate[0]))
            right = max(raw_coordinate[0])
            top = max(raw_coordinate[-1])
            bottom = min(raw_coordinate[-1])

            for x in range(left, right + 1):
                for z in range(bottom, top + 1):
                    coordinate.append((x, z))
            return coordinate

    @staticmethod
    def _copy_files(src_folder, dst_folder, files=None):
        """将指定文件从源文件夹复制到目标文件夹"""
        if not files:
            if os.path.exists(src_folder):
                if os.path.exists(dst_folder):
                    shutil.rmtree(dst_folder, ignore_errors=True)
                shutil.copytree(src_folder, dst_folder)
            return

        for filename in files:
            src_path = os.path.join(src_folder, filename)
            dst_path = os.path.join(dst_folder, filename)
            shutil.copy2(src_path, dst_path)

    @classmethod
    def _process_region(cls, folders, src_base, dst_base, slot_base=None, backup_mode="file"):
        """处理单个区域的文件夹备份和恢复"""
        for folder in folders:
            src_folder = os.path.join(src_base, folder)
            dst_folder = os.path.join(dst_base, folder)

            if slot_base:
                slot_folder = os.path.join(slot_base, folder)
                if backup_mode == "file":
                    os.makedirs(dst_folder, exist_ok=True)
                    slot_files = os.listdir(slot_folder)
                    # 备份源文件夹到覆盖备份路径
                    cls._copy_files(src_folder, dst_folder, slot_files)
                    # 从备份槽复制文件到源文件夹
                    cls._copy_files(slot_folder, src_folder, slot_files)

                else:
                    if os.path.exists(src_folder):
                        if os.path.exists(dst_folder):
                            shutil.rmtree(src_folder, ignore_errors=True)
                        shutil.copytree(src_folder, dst_folder)
                        shutil.rmtree(src_folder, ignore_errors=True)
                        shutil.copytree(slot_folder, src_folder)

            else:
                if backup_mode == "file":
                    slot_files = os.listdir(dst_folder)
                    # 从覆盖备份复制文件到源文件夹
                    cls._copy_files(dst_folder, src_folder, slot_files)
                else:
                    if os.path.exists(dst_folder):
                        shutil.rmtree(src_folder, ignore_errors=True)
                        shutil.copytree(dst_folder, src_folder)

    @classmethod
    def back(cls, region_folder):
        overwrite_folder = os.path.join(cfg.backup_path, cfg.overwrite_backup_folder)
        backup_path = cls.get_backup_path_()
        # 如果覆盖备份文件夹存在且当前备份槽不是覆盖备份文件夹，则清空覆盖备份文件夹
        if os.path.exists(overwrite_folder) and cls.back_slot != cfg.overwrite_backup_folder:
            shutil.rmtree(overwrite_folder)
            os.makedirs(overwrite_folder)

        with open(os.path.join(backup_path, cls.back_slot, "info.json"), "cp") as fp:
            buffer = fp.read()
            content = buffer.decode('utf-8') if buffer[:3] != b'\xef\xbb\xbf' else buffer[3:].decode('utf-8')
            info = json.loads(content)

        backup_mode = "folder" if info["command"].split()[1] == "dim_make" else "file"

        # 如果当前备份槽不是覆盖备份文件夹，则进行备份和恢复操作
        if cls.back_slot != cfg.overwrite_backup_folder:
            for region_info in region_folder.values():
                world_name, folders = region_info[0], region_info[-1]
                region_origin = os.path.join(server_path, world_name)
                region_overwrite = os.path.join(overwrite_folder, world_name)
                region_slot = os.path.join(backup_path, cls.back_slot, world_name)
                cls._process_region(
                    folders, region_origin, region_overwrite, region_slot, backup_mode
                )
            cls.save_info_file(
                list(region_folder.keys()), cfg.backup_path, info["command"], tr("comment.overwrite_comment"),
                cfg.overwrite_backup_folder
            )
        else:
            # 如果当前备份槽是覆盖备份文件夹，则直接从覆盖备份恢复
            for region_info in region_folder.values():
                world_name, folders = region_info[0], region_info[-1]
                region_origin = os.path.join(server_path, world_name)
                region_overwrite = os.path.join(overwrite_folder, world_name)
                cls._process_region(folders, region_origin, region_overwrite, backup_mode=backup_mode)

    @classmethod
    def copy(cls, dimension, backup_path=cfg.backup_path, coordinate=None, slot_="slot1"):
        time.sleep(0.1)

        # 遍历 dimension_info 字典
        for dim_key, info in dimension_info.items():
            # 检查维度键是否匹配（考虑数字字符串和原始字符串）
            if dimension == info["dimension"] or dim_key == dimension:
                region_folder = info["region_folder"]
                world_name = info["world_name"]
                break  # 找到匹配项后退出循环
        else:
            # 如果没有找到匹配项，可以在这里处理（例如，设置默认值或抛出异常）
            region_folder = None  # 或其他默认值
            world_name = None  # 或其他默认值

        if not region_folder or not world_name:
            return 1

        backup_dir = os.path.join(backup_path, slot_, world_name)

        if not coordinate:
            for folder in region_folder:
                if os.path.exists(os.path.join(backup_dir, folder)):
                    shutil.rmtree(os.path.join(backup_dir, folder))

                try:
                    shutil.copytree(
                        os.path.join(server_path, world_name, folder),
                        os.path.join(backup_dir, folder)
                    )

                except FileNotFoundError:
                    continue
            return

        for i, folder in enumerate(region_folder):
            os.makedirs(os.path.join(backup_dir, folder), exist_ok=True)
            for positions in coordinate:
                if not positions:
                    continue
                x, z = positions
                file = f"r.{x}.{z}.mca"
                try:
                    shutil.copy2(
                        os.path.join(server_path, world_name, folder, file),
                        os.path.join(backup_dir, folder, file)
                    )

                except FileNotFoundError:
                    continue


def on_load(server: PluginServerInterface, old):
    global cfg, dimension_info, server_path

    if not os.path.exists(cfg_path):
        server.save_config_simple(
            file_name=cfg_path, in_data_folder=False, config=cp_config.get_default()
        )

    cfg = server.load_config_simple(
        file_name=cfg_path, in_data_folder=False, target_class=cp_config
    )

    server_path = cfg.server_path
    dimension_info = cfg.dimension_info if not cfg.bukkit_mode else cfg.dimension_info_for_bukkit

    server.register_help_message(Prefix, tr("register_message"))
    lvl = cfg.minimum_permission_level
    require = Requirements()
    builder = SimpleCommandBuilder()

    builder.command("!!cp", print_help_msg)
    builder.command("!!cp help", print_help_msg)
    builder.command("!!cp make <radius>", cp_make)
    builder.command("!!cp make <radius> <comment>", cp_make)
    builder.command("!!cp make -s <radius>", cp_make)
    builder.command("!!cp make -s <radius> <comment>", cp_make)
    builder.command("!!cp dim_make <dimension> <comment>", cp_dim_make)
    builder.command("!!cp dim_make <dimension>", cp_dim_make)
    builder.command("!!cp dim_make -s <dimension>", cp_dim_make)
    builder.command("!!cp dim_make -s <dimension> <comment>", cp_dim_make)
    builder.command("!!cp pos_make <x1> <z1> <x2> <z2> <dimension_int>", cp_pos_make)
    builder.command("!!cp pos_make <x1> <z1> <x2> <z2> <dimension_int> <comment>", cp_pos_make)
    builder.command("!!cp pos_make -s <x1> <z1> <x2> <z2> <dimension_int>", cp_pos_make)
    builder.command("!!cp pos_make -s <x1> <z1> <x2> <z2> <dimension_int> <comment>", cp_pos_make)
    builder.command("!!cp back", cp_back)
    builder.command("!!cp back <slot>", cp_back)
    builder.command("!!cp back -s", cp_back)
    builder.command("!!cp back -s <slot>", cp_back)
    builder.command("!!cp restore", cp_back)
    builder.command("!!cp confirm", cp_confirm)
    builder.command("!!cp del <slot>", cp_del)
    builder.command("!!cp del -s <slot>", cp_del)
    builder.command("!!cp abort", cp_abort)
    builder.command("!!cp list", cp_list)
    builder.command("!!cp list <page>", cp_list)
    builder.command("!!cp list -s", cp_list)
    builder.command("!!cp list -s <page>", cp_list)
    builder.command("!!cp reload", cp_reload)
    builder.command("!!cp update_slot", cp_update_slot)

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

    for literal in cp_config.minimum_permission_level:
        permission = lvl[literal]
        builder.literal(literal).requires(
            require.has_permission(permission),
            failure_message_getter=lambda err: tr("lack_permission")
        )

    builder.register(server)
