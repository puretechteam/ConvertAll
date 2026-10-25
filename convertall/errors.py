class ConversionError(Exception):
    pass


class NoRouteError(ConversionError):
    pass


class EngineMissingError(ConversionError):
    def __init__(self, engine_keys: list[str]):
        from .engines import ENGINES
        self.engines = engine_keys
        names = ", ".join(ENGINES[k].name for k in engine_keys)
        super().__init__(f"Needs {names} (not installed)")
