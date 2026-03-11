import contextlib
import functools
import threading
import time
from typing import Optional
from mcdreforged.api.types import PluginServerInterface, Info
from chunk_backup import mcdr_globals
from chunk_backup.config.config import Config, set_config_instance
from chunk_backup.config.backup_config import BackupConfig
from chunk_backup.task_manager import TaskManager
from chunk_backup.command.commands import CommandManager

config: Optional[Config] = None
task_manager: Optional[TaskManager] = None
command_manager: Optional[CommandManager] = None
mcdr_globals.load()
init_thread: Optional[threading.Thread] = None


def _try_upgrade_config(server: PluginServerInterface, cfg: Config, from_startup: bool = False) -> bool:
    """
    尝试升级配置（版本升级 + 维度升级）。
    返回 True 表示配置被修改，需要保存。
    """
    modified = False
    plugin_version = str(server.get_self_metadata().version)

    # 1. 配置文件版本升级（仅在 on_load 阶段）
    if not from_startup:
        if cfg.upgrade_version(plugin_version):
            server.logger.info(f'Config version upgraded: {cfg.config_version} -> {plugin_version}')
            modified = True

    # 2. 维度与玩家数据结构升级（仅当能获取到有效 Minecraft 版本时）
    server_version = server.get_server_information().version
    if server_version:   # 只有非空字符串才尝试
        if BackupConfig.upgrade_all(cfg, server_version):
            server.logger.info(f'Dimension and Playerdata structure updated for Minecraft {server_version}')
            modified = True

    return modified


def on_load(server: PluginServerInterface, old):
    @contextlib.contextmanager
    def handle_init_error():
        try:
            yield
        except Exception:
            server.logger.error(f'{server.get_self_metadata().name} initialization failed and will be disabled')
            server.schedule_task(functools.partial(on_unload, server))
            raise

    def init():
        with handle_init_error():
            task_manager.start()
            command_manager.construct_command_tree()
        server.logger.debug(f'{mcdr_globals.metadata.name} init done')

    global config, task_manager, command_manager
    with handle_init_error():
        # ---------- 1. 加载配置文件 ----------
        config = server.load_config_simple(target_class=Config, failure_policy='raise', echo_in_console=False)
        set_config_instance(config)  # 立即设置单例

        # ---------- 2. 尝试升级配置（版本 + 可能同时升级维度）----------
        need_save = _try_upgrade_config(server, config, from_startup=False)

        # ---------- 3. 初始化管理器 ----------
        task_manager = TaskManager()
        command_manager = CommandManager(server, task_manager)

        # ---------- 4. 注册命令和帮助 ----------
        command_manager.register_command_node()
        server.register_help_message(config.command.prefix, mcdr_globals.metadata.get_description_rtext())

        # ---------- 5. 保存配置（如果需要）----------
        if need_save:
            server.save_config_simple(config)
            server.logger.info('Config saved due to upgrade')

        # ---------- 6. 启动初始化线程 ----------
        global init_thread
        init_thread = threading.Thread(target=init, name="CB@init", daemon=True)
        init_thread.start()
        init_thread_start_ts = time.time()
        init_thread.join(timeout=2)
        if init_thread.is_alive():
            server.logger.debug('Init thread still alive after 2s')
        else:
            server.logger.debug(f'Init thread terminated in {time.time() - init_thread_start_ts:.2f}s')


def on_server_startup(server: PluginServerInterface):
    global config
    need_save = _try_upgrade_config(server, config, from_startup=True)
    if need_save:
        server.save_config_simple(config)
        server.logger.info('Config saved after server startup upgrade')


def on_server_stop(server: PluginServerInterface, server_return_code: int):
    if task_manager:
        task_manager.on_server_stopped()


def on_info(server: PluginServerInterface, info: Info):
    if not info.is_user and config is not None:
        for pattern in config.server.saved_world_regex:
            if pattern.fullmatch(info.content):
                task_manager.on_world_saved()
                break


_has_unload = False
_has_unload_lock = threading.Lock()


def on_unload(server: PluginServerInterface):
    with _has_unload_lock:
        global _has_unload
        if _has_unload:
            return
        _has_unload = True

    server.logger.info('Shutting down everything...')
    global task_manager

    def shutdown():
        global task_manager
        try:
            if init_thread is not None:
                init_thread.join()
            if command_manager is not None:
                command_manager.close_the_door()
            """if crontab_manager is not None:"""
            """	crontab_manager.shutdown()"""
            """	crontab_manager = None"""
            if task_manager is not None:
                task_manager.shutdown()
                task_manager = None

        finally:
            shutdown_event.set()

    shutdown_event = threading.Event()
    thread = threading.Thread(target=shutdown, name="CB@shutdown", daemon=True)
    thread.start()

    start_time = time.time()
    for i, delay in enumerate([10, 60, 300, 600, None]):
        elapsed = time.time() - start_time
        if i > 0:
            server.logger.info(f'Waiting for manager shutdown ... time elapsed {elapsed:.1f}s')
            if init_thread is not None and init_thread.is_alive():
                server.logger.info('init_thread is still running')
            elif (tm := task_manager) is not None:
                server.logger.info('task_manager is still alive')
                server.logger.info('task worker heavy: queue size %s current %s', tm.worker_heavy.task_queue.qsize(),
                                   tm.worker_heavy.task_queue.current_item)
                server.logger.info('task worker light: queue size %s current %s', tm.worker_light.task_queue.qsize(),
                                   tm.worker_heavy.task_queue.current_item)

        shutdown_event.wait(max(0.0, delay - elapsed) if delay is not None else delay)
        if shutdown_event.is_set():
            break
    server.logger.info('Shutdown completes')
