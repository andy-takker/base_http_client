import json
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Serializer:
    dumps: Callable
    content_type: str


JsonSerializer = Serializer(
    dumps=json.dumps,
    content_type="application/json",
)
