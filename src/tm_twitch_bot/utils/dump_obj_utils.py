import json, logging, inspect, dataclasses, attr


def dump_obj(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if attr.has(type(obj)):
        return attr.asdict(obj)
    # attrs / dataclass 都不是 → fallback
    return {s: getattr(obj, s) for s in getattr(obj, "__slots__", [])} or str(obj)
