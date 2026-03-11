import enum
import functools
from typing import Callable
from mcdreforged.api.types import PluginServerInterface, CommandSource, InfoCommandSource
from mcdreforged.api.command import CommandContext, Literal, Text, GreedyText, Integer, CountingLiteral, SimpleCommandBuilder
from mcdreforged.api.rtext import RColor
from chunk_backup.command.nodes import Position2D, IntegerList, IntegerRangeList
from chunk_backup.config.config import Config
from chunk_backup.task.backup.create_backup_task import CreateBackupTask
from chunk_backup.task.backup.delete_backup_task import DeleteBackupTask
from chunk_backup.task.backup.list_backup_task import ListBackupTask
from chunk_backup.task.backup.list_log_task import ListLogTask
from chunk_backup.task.backup.restore_backup_task import RestoreBackupTask
from chunk_backup.task.backup.show_backup_task import ShowBackupTask
from chunk_backup.task.backup.show_log_task import ShowLogTask
from chunk_backup.task.general.show_help_task import ShowHelpTask
from chunk_backup.task.general.show_welcome_task import ShowWelcomeTask
from chunk_backup.task_manager import TaskManager
from chunk_backup.task_queue import TaskQueue
from chunk_backup.utils.backup_utils import DimensionChecker, BackupFolderManager as Manager
from chunk_backup.utils.mcdr_utils import tr, reply_message, mkcmd


class CommandManagerState(enum.Enum):
    INITIAL = enum.auto()
    HOOKED = enum.auto()
    READY = enum.auto()
    DISABLED = enum.auto()


class CommandManager:
    def __init__(self, server: PluginServerInterface, task_manager: TaskManager):
        self.server = server
        self.task_manager = task_manager
        self.config = Config.get()
        self.__state = CommandManagerState.INITIAL
        self.__root_node = Literal(self.config.command.prefix)

    def close_the_door(self):
        self.__state = CommandManagerState.DISABLED

    # =============================== Command Callback ===============================

    def cmd_welcome(self, source: CommandSource, _: CommandContext):
        self.task_manager.add_task(ShowWelcomeTask(source))

    def cmd_help(self, source: CommandSource, context: dict):
        what = context.get('what')
        if what is not None and what not in ShowHelpTask.COMMANDS_WITH_DETAILED_HELP:
            reply_message(source, tr('command.help.no_help', mkcmd(what)))
            return

        self.task_manager.add_task(ShowHelpTask(source, what))

    def cmd_make(self, source: InfoCommandSource, context: CommandContext):
        if not source.is_player and "radius" in context:
            reply_message(source, tr("task.backup_create.only_player"))
            return

        current = self.task_manager.worker_heavy.task_queue.peek_first_unfinished_item()
        if current is not TaskQueue.NONE:
            reply_message(source, tr("task._many", tr(f"task.{current.task.id}.name").to_plain_text()))
            return

        checker = DimensionChecker.create(source, self.config.backup.dimension)

        if not checker:
            return

        if "dimensions" in context:
            dimensions = context["dimensions"]

        elif "dimension" in context:
            # 单个维度，直接包装为列表（即使是 0 也会正确包装）
            dimensions = [context["dimension"]]

        if "radius" not in context:
            ids = checker.get_integer_ids()
            for dimension in dimensions:
                if dimension not in ids:
                    reply_message(source, tr("task.backup_create.lack_integer_id", integer_id=dimension))
                    return

            context["dimension"] = [checker.get_by_id(dimension) for dimension in dimensions]

        self.task_manager.add_task(CreateBackupTask(source, context))

    def cmd_del(self, source: InfoCommandSource, context: CommandContext):
        current = self.task_manager.worker_heavy.task_queue.peek_first_unfinished_item()
        if current is not TaskQueue.NONE:
            reply_message(source, tr("task._many", tr(f"task.{current.task.id}.name").to_plain_text()))
            return

        manager = Manager(is_static=True if context.get("static_count") else False)
        all_slots = manager.get_all_slot_name(integer=True)
        slots = context.get("slot_range")

        if context.get("all_count") and not all_slots:
            reply_message(source, tr("other.ui.list_empty"))
            return

        elif context.get("all_count"):
            context["slot_range"] = all_slots
            self.task_manager.add_task(DeleteBackupTask(source, context, manager))
            return

        all_slots_set = set(all_slots)

        active_slots = [slot for slot in slots if slot in all_slots_set]

        if not active_slots:
            if len(slots) == 1:
                reply_message(source, tr("task.delete_backup.no_id", id=slots[0]))
            else:
                reply_message(source, tr("task.delete_backup.no_range_id"))
            return

        context["slot_range"] = active_slots

        self.task_manager.add_task(DeleteBackupTask(source, context, manager))

    def cmd_list(self, source: CommandSource, context: CommandContext):
        self.task_manager.add_task(ListBackupTask(source, context))

    def cmd_show(self, source: CommandSource, context: CommandContext):
        self.task_manager.add_task(ShowBackupTask(source, context))

    def cmd_list_log(self, source: CommandSource, context: CommandContext):
        self.task_manager.add_task(ListLogTask(source, context))

    def cmd_show_log(self, source: CommandSource, context: CommandContext):
        self.task_manager.add_task(ShowLogTask(source, context))

    def cmd_restore(self, source: InfoCommandSource, context: CommandContext):
        context["pre_restore"] = 1
        self.cmd_back(source, context)

    def cmd_back(self, source: InfoCommandSource, context: CommandContext):
        current = self.task_manager.worker_heavy.task_queue.peek_first_unfinished_item()
        if current is not TaskQueue.NONE:
            reply_message(source, tr("task._many", tr(f"task.{current.task.id}.name").to_plain_text()))
            return
        self.task_manager.add_task(RestoreBackupTask(source, context))

    def cmd_confirm(self, source: CommandSource, _: CommandContext):
        self.task_manager.do_confirm(source)

    def cmd_abort(self, source: CommandSource, _: CommandContext):
        self.task_manager.do_abort(source)

    def cmd_reload(self, source: CommandSource, _: CommandContext):
        current = self.task_manager.worker_heavy.task_queue.peek_first_unfinished_item()
        if current is not TaskQueue.NONE:
            reply_message(source, tr("task._many", tr(f"task.{current.task.id}.name").to_plain_text()))
            return
        source.get_server().reload_plugin("chunk_backup")
        reply_message(source, tr("task.reload_plugin.completed"))

    # ============================ Command Callback ends =============================

    def register_command_node(self):
        if self.__state != CommandManagerState.INITIAL:
            raise AssertionError(self.__state)

        self.__root_node.requires(
            lambda: self.__state == CommandManagerState.READY,
            lambda: tr(
                'error.disabled' if self.__state == CommandManagerState.DISABLED else 'error.initializing').set_color(
                RColor.red),
        )
        self.server.register_command(self.__root_node)
        self.__state = CommandManagerState.HOOKED

    def construct_command_tree(self):
        if self.__state != CommandManagerState.HOOKED:
            raise AssertionError(self.__state)

        # --------------- common utils ---------------

        permissions = self.config.command.permission

        def get_permission_checker(literal: str) -> Callable[[CommandSource], bool]:
            return functools.partial(CommandSource.has_permission, level=permissions.get(literal))

        def get_permission_denied_text():
            return tr('other.error.permission_denied').set_color(RColor.red)

        def create_subcommand(literal: str) -> Literal:
            node = Literal(literal)
            node.requires(get_permission_checker(literal), get_permission_denied_text)
            return node

        # --------------- commands ---------------

        builder = SimpleCommandBuilder()

        # help
        builder.command('help', self.cmd_help)
        builder.command('help <what>', self.cmd_help)
        builder.arg('what', Text).suggests(lambda: ShowHelpTask.COMMANDS_WITH_DETAILED_HELP)

        # operations
        builder.command('confirm', self.cmd_confirm)
        builder.command('abort', self.cmd_abort)

        builder.command('reload', self.cmd_reload)

        for name, level in permissions.items():
            builder.literal(name).requires(get_permission_checker(name), get_permission_denied_text)

        root = (
            self.__root_node
                .requires(get_permission_checker('root'), get_permission_denied_text)
                .runs(self.cmd_welcome)
        )
        builder.add_children_for(root)

        # ==================== 自定义命令构建 ====================

        def make_make_cmd() -> Literal:
            node = create_subcommand('make')
            arg_radius = Integer('radius').at_min(0).runs(self.cmd_make)

            # 静态标志
            static_flag = CountingLiteral(['--static', '-s'], 'static_count')
            static_flag.runs(self.cmd_make)
            arg_comment_after_static = GreedyText('comment').runs(functools.partial(self.cmd_make, is_static=True))
            static_flag.then(arg_comment_after_static)

            # 注释（无静态）
            arg_comment_no_static = GreedyText('comment').runs(self.cmd_make)

            arg_radius.then(static_flag)
            arg_radius.then(arg_comment_no_static)

            node.then(arg_radius)
            return node

        def make_pmake_cmd() -> Literal:
            node = create_subcommand('pmake')
            arg_crood1 = Position2D('crood_1')
            arg_crood2 = Position2D('crood_2')
            literal_in = Literal('in')
            arg_dim = Integer('dimension')

            chain = arg_crood1.then(arg_crood2.then(literal_in.then(arg_dim)))
            node.then(chain)

            arg_dim.runs(self.cmd_make)

            static_flag = CountingLiteral(['--static', '-s'], 'static_count')
            static_flag.runs(self.cmd_make)
            arg_comment_after_static = GreedyText('comment').runs(functools.partial(self.cmd_make))
            static_flag.then(arg_comment_after_static)

            arg_comment_no_static = GreedyText('comment').runs(self.cmd_make)

            arg_dim.then(static_flag)
            arg_dim.then(arg_comment_no_static)

            return node

        def make_dmake_cmd() -> Literal:
            node = create_subcommand('dmake')
            arg_dimensions = IntegerList('dimensions')
            node.then(arg_dimensions)

            arg_dimensions.runs(self.cmd_make)

            static_flag = CountingLiteral(['--static', '-s'], 'static_count')
            static_flag.runs(self.cmd_make)
            arg_comment_after_static = GreedyText('comment').runs(functools.partial(self.cmd_make))
            static_flag.then(arg_comment_after_static)

            arg_comment_no_static = GreedyText('comment').runs(self.cmd_make)

            arg_dimensions.then(static_flag)
            arg_dimensions.then(arg_comment_no_static)

            return node

        def make_list_cmd() -> Literal:
            node = create_subcommand('list')
            node.runs(self.cmd_list)

            # 静态标志（无参数）
            static_flag = CountingLiteral(['--static', '-s'], 'static_count')
            static_flag.runs(self.cmd_list)
            static_flag.redirects(node)

            # 每页选项（带参数）
            per_page_arg = Integer('per_page').at_min(1)
            per_page_arg.runs(self.cmd_list)
            per_page_arg.redirects(node)  # 参数节点重定向回根节点
            per_page_node = Literal(['-p', '--per-page']).then(per_page_arg)

            # 隐藏多余ui选项（无参数）
            hide_ui_flag = CountingLiteral(['--hide', '-h'], 'hide_count')
            hide_ui_flag.runs(self.cmd_list)
            hide_ui_flag.redirects(node)

            # 页码节点（无参数）
            page_node = Integer('page').at_min(1)
            page_node.runs(self.cmd_list)
            page_node.redirects(node)

            # 根节点直接挂载所有选项
            node.then(static_flag)
            node.then(per_page_node)
            node.then(page_node)
            node.then(hide_ui_flag)

            return node

        def make_show_cmd() -> Literal:
            node = create_subcommand('show')
            overwrite_node = CountingLiteral("overwrite", "pre_backup")
            overwrite_node.runs(self.cmd_show)
            node.then(overwrite_node)

            # 槽位节点（必需参数）
            arg_slot = Integer('backup_id').at_min(1)
            arg_slot.runs(self.cmd_show)

            # 静态标志（无参数）
            static_flag = CountingLiteral(['--static', '-s'], 'static_count')
            static_flag.runs(self.cmd_show)

            # 数据标志（带参数）
            data_flag = CountingLiteral(['-d', '--data'], 'data_count')
            data_flag.runs(self.cmd_show)
            arg_page = Integer('page').at_min(1)
            arg_page.runs(self.cmd_show)

            # 数据标志后可跟页码
            data_flag.then(arg_page)

            # 页码后可以跟静态（用于数据+静态顺序）
            arg_page.then(static_flag)

            # 静态后可以跟数据（用于静态+数据顺序）
            static_flag.then(data_flag)

            # 槽位后可以跟静态或数据
            arg_slot.then(static_flag)
            arg_slot.then(data_flag)

            # overwrite 后只能跟数据标志，不能跟静态标志
            overwrite_node.then(data_flag)  # 保留数据标志，移除静态标志

            node.then(arg_slot)
            return node

        def make_log_cmd() -> Literal:
            node = create_subcommand("log")
            node.runs(self.cmd_list_log)
            list_node = Literal("list")
            show_node = Literal("show")
            arg_page = Integer('page').at_min(1)
            arg_name = Text('name')
            node.then(list_node.runs(self.cmd_list_log).then(arg_page.redirects(node)))
            list_node.then(Literal(['-p', '--per-page']).then(Integer("per_page").at_min(1).redirects(list_node)))  # 修正拼写
            node.then(show_node.runs(self.cmd_show_log).then(arg_name.runs(self.cmd_show_log)))
            return node

        def make_back_cmd() -> Literal:
            node = create_subcommand('back')
            node.runs(self.cmd_back)  # 无槽位时执行

            # 槽位节点（必需参数）
            arg_slot = Integer('backup_id').at_min(1)
            arg_slot.runs(self.cmd_back)

            # 定义可选标志（无参数）
            data_flag = CountingLiteral(['-d', '--data'], 'data_count')
            confirm_flag = CountingLiteral(['-c', '--confirm'], 'confirm_count')
            static_flag = CountingLiteral(['--static', '-s'], 'static_count')

            for flag in [data_flag, confirm_flag, static_flag]:
                flag.runs(self.cmd_back)
                flag.redirects(node)  # 解析完标志后回到 node，继续解析其他标志

            # 将标志也挂载到 node（无槽位情况）
            node.then(data_flag)
            node.then(confirm_flag)
            node.then(static_flag)

            # 槽位后可以跟任意标志
            arg_slot.then(data_flag)
            arg_slot.then(confirm_flag)
            arg_slot.then(static_flag)

            node.then(arg_slot)
            return node

        def make_restore_cmd() -> Literal:
            node = create_subcommand('restore')
            node.runs(self.cmd_restore)

            data_flag = CountingLiteral(['-d', '--data'], 'data_count')
            confirm_flag = CountingLiteral(['-c', '--confirm'], 'confirm_count')

            for flag in [data_flag, confirm_flag]:
                flag.redirects(node)
                node.then(flag)

            return node

        def make_delete_cmd() -> Literal:
            node = create_subcommand('del')
            node.runs(self.cmd_del)

            static_flag = CountingLiteral(['--static', '-s'], 'static_count')
            static_flag.runs(self.cmd_del)

            all_node = CountingLiteral('all', 'all_count')
            all_node.runs(self.cmd_del)

            arg_slot = IntegerRangeList('slot_range')
            arg_slot.runs(self.cmd_del)

            # 根节点后可以跟 all 或槽位
            node.then(all_node)
            node.then(arg_slot)

            # 静态节点后可以跟 all 或槽位
            static_flag.then(all_node)
            static_flag.then(arg_slot)

            # 槽位节点后可以跟静态
            arg_slot.then(static_flag)

            # all 节点后也可以跟静态（!!cb del all -s 生效）
            all_node.then(static_flag)

            return node

        # 将所有子命令挂载到根节点
        root.then(make_make_cmd())
        root.then(make_pmake_cmd())
        root.then(make_dmake_cmd())
        root.then(make_list_cmd())
        root.then(make_show_cmd())
        root.then(make_back_cmd())
        root.then(make_delete_cmd())
        root.then(make_log_cmd())
        root.then(make_restore_cmd())

        self.__state = CommandManagerState.READY
