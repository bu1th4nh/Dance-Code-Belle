"""Names and wire IDs recovered from the supplied C# enum tables."""
import json
from dataclasses import dataclass
from enum import IntEnum
from importlib.resources import files
from types import MappingProxyType

_DATA = json.loads(files(__package__).joinpath("catalog.json").read_text())
AudioPhrase = IntEnum("AudioPhrase", {k: v["id"] for k, v in _DATA["audio"].items()}, module=__name__)
HighLevelSequence = IntEnum("HighLevelSequence", {k: v["id"] for k, v in _DATA["sequences"].items()}, module=__name__)


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    id: int
    duration: float


AUDIO = MappingProxyType({k: CatalogEntry(k, **v) for k, v in _DATA["audio"].items()})
SEQUENCES = MappingProxyType({k: CatalogEntry(k, **v) for k, v in _DATA["sequences"].items()})


def resolve(value: str | int, *, sequence: bool = False) -> CatalogEntry:
    """Accept an exact source name or a known zero-based wire ID; never guess."""
    catalog = SEQUENCES if sequence else AUDIO
    if isinstance(value, str):
        try:
            return catalog[value]
        except KeyError:
            raise ValueError(f"Unknown {'sequence' if sequence else 'phrase'}: {value}") from None
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Expected a catalog name or integer wire ID")
    # Reject an enum from the wrong namespace even if its value is in range.
    enum = HighLevelSequence if sequence else AudioPhrase
    if isinstance(value, IntEnum) and not isinstance(value, enum):
        raise TypeError("Audio and high-level sequence IDs are different namespaces")
    if value < 0 or value >= len(catalog):
        raise ValueError(f"Unknown wire ID: {value}")
    return tuple(catalog.values())[value]
