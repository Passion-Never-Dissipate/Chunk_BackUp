import threading
import candy_tools as ct
from chunk_backup.types.point import Point3D
from chunk_backup.config.config import Config


class ServerDataGetter:
    def __init__(self):
        self.config = Config.get()

    def get_position_data(self, name: str):
        if cmd := self.config.server.commands.get_entity_data:
            results = {
                'position': None,
                'dimension': None
            }

            def match_position():
                match = ct.execute_and_wait_match(
                    command=cmd.format(name=name, path="Pos"),
                    pattern=self.config.server.data_getter_regex.get("crood_getter").pattern.format(name=name)
                )
                results["position"] = match if match is not None else None

            def match_dimension():
                match = ct.execute_and_wait_match(
                    command=cmd.format(name=name, path="Dimension"),
                    pattern=self.config.server.data_getter_regex.get("dimension_getter").pattern.format(name=name)
                )
                results["dimension"] = match if match is not None else None

            thread_1 = threading.Thread(target=match_position, daemon=True)
            thread_2 = threading.Thread(target=match_dimension, daemon=True)

            thread_1.start()
            thread_2.start()

            thread_1.join(timeout=5)
            thread_2.join(timeout=5)

            if None in results.values():
                return
            # noinspection PyUnresolvedReferences
            return \
                {"position": Point3D(results["position"].group("x"), results["position"].group("y"), results["position"].group("z")),
                 "dimension": results["dimension"].group("dimension")}
