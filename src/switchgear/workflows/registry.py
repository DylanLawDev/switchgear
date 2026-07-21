"""Named code plugins. Definitions reference these by name; an unknown name
makes the definition invalid at parse time — a definition can never invent
an executor."""


class WorkflowPlugins:
    def __init__(self):
        self._generators: dict[str, object] = {}
        self._executors: dict[str, object] = {}

    def register_generator(self, name: str, generator: object) -> None:
        self._generators[name] = generator

    def register_executor(self, name: str, executor: object) -> None:
        self._executors[name] = executor

    def generator(self, name: str) -> object:
        return self._generators[name]

    def executor(self, name: str) -> object:
        return self._executors[name]

    @property
    def generator_names(self):
        """Live view: names registered after this property is read (e.g. by a
        test wiring a fake plugin post-app-construction) are still visible."""
        return self._generators.keys()

    @property
    def executor_names(self):
        return self._executors.keys()
