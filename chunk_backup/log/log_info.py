from mcdreforged.api.utils import Serializable


class LogTask(Serializable):
    date: str = ""
    task: str = ""
    command: str = ""
    operator: str = ""
    task_done: bool = False

    def serialize(self) -> dict:
        data = super().serialize()
        if self.task == "backup_restore":
            if hasattr(self, "pre_backup_done"):
                data["pre_backup_done"] = self.pre_backup_done

            if hasattr(self, "pre_restore_done"):
                data["pre_restore_done"] = self.pre_restore_done

        return data
