import contextlib
import threading
import datetime
import shutil
import traceback
import candy_tools as ct

from typing import Optional
from collections import defaultdict
from mcdreforged.api.types import InfoCommandSource
from mcdreforged.api.rtext import RColor
from chunk_backup.action.create_backup_action import CreateBackupAction
from chunk_backup.task.basic_task import HeavyTask
from chunk_backup.task import TaskEvent
from chunk_backup.types.backup_info import BackupInfo
from chunk_backup.types.operator import Operator
from chunk_backup.utils.mcdr_utils import tr
from chunk_backup.utils.serverdata_getter import ServerDataGetter
from chunk_backup.types.point import Point2D
from chunk_backup.utils.backup_utils import PlayerDataFolderManager
from chunk_backup.utils.region.chunk_selector import ChunkSelector
from chunk_backup.log.log_manager import LogManager
from chunk_backup.log.log_info import LogTask
from chunk_backup.exceptions import MaxChunkLength, MaxChunkRadius
from chunk_backup.utils.timer import Timer


class CreateBackupTask(HeavyTask[Optional[int]]):

    def __init__(
        self,
        source: InfoCommandSource,
        context: dict,
        operator: Optional[Operator] = None,
    ):
        super().__init__(source)
        self.context = context
        self.operator = Operator.of(source) if operator is None else operator
        self.is_static = True if context.get("static_count") else False
        self.world_saved_done = threading.Event()
        self.__waiting_world_save = False

    @property
    def id(self) -> str:
        return "create_backup"

    def is_abort_able(self) -> bool:
        return self.__waiting_world_save

    # -------------------------------------------------

    @contextlib.contextmanager
    def __autosave_disabler(self):

        cmd_auto_save_off = self.config.server.commands.auto_save_off
        cmd_auto_save_on = self.config.server.commands.auto_save_on

        applied_auto_save_off = False

        if (
            self.server.is_server_running()
            and self.config.server.turn_off_auto_save
            and len(cmd_auto_save_off) > 0
        ):
            self.server.execute(cmd_auto_save_off)
            applied_auto_save_off = True

        try:
            yield

        finally:
            if (
                applied_auto_save_off
                and self.server.is_server_running()
                and len(cmd_auto_save_on) > 0
            ):
                self.server.execute(cmd_auto_save_on)

    # -------------------------------------------------

    def __build_backup_info(self) -> Optional[BackupInfo]:

        ctx = self.context
        backup_info = BackupInfo()

        selector = defaultdict(list)

        data = None

        # radius模式
        if "radius" in ctx:
            data = ServerDataGetter().get_position_data(self.source.player)

            if not data:
                self.reply(tr("command.execute.timeout.data_getter_timeout"))
                return None

            if data["dimension"] not in self.config.backup.dimension:
                self.reply(self.tr("lack_dimension", dimension=data["dimension"]))
                return None

            backup_info.dimension = [data["dimension"]]

        else:
            backup_info.dimension = ctx["dimension"]

        # -------------------------------------------------
        # selector构造
        # -------------------------------------------------

        if "crood_1" in ctx:

            p1 = Point2D(ctx["crood_1"][0], ctx["crood_1"][1])
            p2 = Point2D(ctx["crood_2"][0], ctx["crood_2"][1])

            points = p1 + p2

            try:
                sel = points.to_chunk_selector(
                    max_chunk_size=self.config.backup.max_chunk_length
                )

            except MaxChunkLength as e:

                self.reply_tr(
                    "max_chunk_length",
                    default=e.max_chunk_size,
                    height=e.height,
                    width=e.width,
                )

                return None

            for dim in backup_info.dimension:
                selector[dim].append(sel)

        elif "radius" in ctx:

            point = data["position"].to_point2d()

            try:
                sel = point.to_chunk_selector(
                    ctx["radius"],
                    max_chunk_size=self.config.backup.max_chunk_length,
                )

            except MaxChunkRadius as e:

                self.reply_tr(
                    "max_chunk_radius",
                    default=e.max_chunk_size,
                    current_size=e.current_size,
                    radius=e.radius,
                )

                return None

            for dim in backup_info.dimension:
                selector[dim].append(sel)

            backup_info.player_position = {
                "x": data["position"].x,
                "y": data["position"].y,
                "z": data["position"].z,
            }

        else:

            for dim in backup_info.dimension:
                selector[dim].append("all")

        backup_info.is_static = self.is_static

        backup_info.selector = selector
        if ct.query_carpet():
            region_dict = ChunkSelector.to_block_rectangles_dict(selector)
            origion_dimension = list(selector.keys())
            player_data = ct.get_players_data_in_regions(region_dict, origion_dimension)
            if not player_data:
                if player_data is None:
                    self.broadcast(self.tr("no_carpet", self.tr("name").to_plain_text()))
                else:
                    self.broadcast(self.tr("no_player", self.tr("name").to_plain_text()))
            else:
                backup_info.player_data = player_data
        else:
            self.broadcast(self.tr("no_carpet", self.tr("name").to_plain_text()))
        # -------------------------------------------------
        # type
        # -------------------------------------------------

        if "dimensions" in ctx:
            backup_info.type = "region"

        else:
            backup_info.type = "chunk"

            rect = selector[backup_info.dimension[0]][0]._rectangles[0]

            backup_info.top_left = {"x": rect[0], "z": rect[3]}
            backup_info.top_right = {"x": rect[2], "z": rect[3]}
            backup_info.bottom_left = {"x": rect[0], "z": rect[1]}
            backup_info.bottom_right = {"x": rect[2], "z": rect[1]}

        # -------------------------------------------------
        # metadata
        # -------------------------------------------------

        backup_info.comment = ctx.get(
            "comment", self.tr("no_comment").to_plain_text()
        )

        backup_info.operator = (
            self.operator.name
            if self.operator.is_player()
            else tr("other.operator.console").to_plain_text()
        )

        backup_info.command = self.source.get_info().content

        backup_info.version_created = self.config.config_version
        backup_info.minecraft_version = self.config.minecraft_version

        return backup_info

    def run(self) -> Optional[int]:

        backup_info = self.__build_backup_info()

        if backup_info is None:
            return None

        self.broadcast(self.tr("start"))

        with contextlib.ExitStack() as exit_stack:
            exit_stack.enter_context(self.__autosave_disabler())

            timer = Timer()
            if self.server.is_server_running():

                if len(cmd_save_all_worlds := self.config.server.commands.save_all_worlds) > 0:
                    self.server.execute(cmd_save_all_worlds)

                if len(self.config.server.saved_world_regex) > 0:

                    self.__waiting_world_save = True

                    wait_world_saved_done_ok = self.world_saved_done.wait(
                        timeout=self.config.server.save_world_max_wait.value)

                    self.__waiting_world_save = False

                    if self.aborted_event.is_set():

                        self.broadcast(self.get_aborted_text())

                        return None
                    if not wait_world_saved_done_ok:

                        self.broadcast(self.tr('abort.save_wait_time_out').set_color(RColor.red))
                        return None

            if self.plugin_unloaded_event.is_set():
                self.broadcast(self.tr('abort.unloaded').set_color(RColor.red))
                return None

            cost_save_wait = timer.get_and_restart()

            log_task = LogTask()
            log_task.task = self.id
            log_task.operator = self.operator.name if self.operator.is_player() else tr("other.operator.console").to_plain_text()
            log_task.command = self.source.get_info().content

            with LogManager().task_logger(log_task):
                action = CreateBackupAction(
                    backup_info
                )

                action.run()
                backup_info.date = datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                if backup_info.player_data:
                    try:
                        uuid_dict = {}
                        for k, v in backup_info.player_data.items():
                            uuid_dict[k] = v["uuid"]
                        _data = PlayerDataFolderManager(list(uuid_dict.values()), is_static=self.is_static)
                        _data.backup_player_data()
                        backup_info.uuid_dict = uuid_dict
                    except Exception:
                        shutil.rmtree(_data.storage_root / _data.region_storage / _data.backup_slot / "players", ignore_errors=True)
                        self.broadcast(self.tr("backup_player_data_error", error=traceback.format_exc()))

                backup_info.save_json()

                cost_create = timer.get_elapsed()
                cost_total = cost_save_wait + cost_create

                self.broadcast(
                    self.tr(
                        'date', date=backup_info.date,
                        comment=self.context.get("comment", self.tr('no_comment').to_plain_text())
                    )
                )
                if backup_info.uuid_dict:
                    self.broadcast(self.tr("player_data_completed", total=len(backup_info.uuid_dict), type=self.tr("name").to_plain_text()))

                self.broadcast(
                    self.tr('completed', round(cost_total, 2))
                )

        return backup_info.total_size

    def on_event(self, event: TaskEvent):
        super().on_event(event)
        if event == TaskEvent.operation_aborted and self.__waiting_world_save:
            self.world_saved_done.set()
        if event == TaskEvent.plugin_unload:
            self.world_saved_done.set()
        elif event in [TaskEvent.world_save_done, TaskEvent.server_stopped]:
            self.world_saved_done.set()