"""Pure packet encoding. No Bluetooth or physical side effects."""
from dataclasses import dataclass
import struct
from .catalog import resolve

TOY_NAME = "DanceCD"
WRITE_UUID = "51901383-030f-4859-b643-256b0b2f5562"
NOTIFY_UUID = "51901382-030f-4859-b643-256b0b2f5562"
KEEP_ALIVE = bytes.fromhex("50 8d")
END_APP_MODE = bytes.fromhex("50 8c")
STOP_QUEUE = b"\x12"
STOP_ALL = bytes.fromhex("18 ff")
REQUEST_INPUT = b"\x20"
REQUEST_VOLUME = b"\x22"


def play_audio(phrase: str | int) -> bytes:
    return b"\x10" + struct.pack("<H", resolve(phrase).id)


def play_sequence(sequence: str | int) -> bytes:
    return b"\x17\x02" + struct.pack("<H", resolve(sequence, sequence=True).id)


def set_volume(volume: int) -> bytes:
    if not isinstance(volume, int) or isinstance(volume, bool) or not 0 <= volume <= 5:
        raise ValueError("Volume must be an integer between 0 and 5")
    return bytes((0x23, volume))


@dataclass(frozen=True)
class Notification:
    opcode: int
    raw: bytes
    value: int | None = None
    sequence_type: int | None = None


def parse_notification(data: bytes) -> Notification:
    raw = bytes(data)
    if not raw:
        raise ValueError("Empty notification")
    opcode = raw[0]
    lengths = {0x10: 3, 0x13: 2, 0x17: 4, 0x20: 3, 0x22: 2, 0x50: 2}
    if len(raw) < lengths.get(opcode, 1):
        raise ValueError(f"Truncated notification for opcode 0x{opcode:02x}")
    if opcode == 0x10:
        return Notification(opcode, raw, int.from_bytes(raw[1:3], "little"))
    if opcode == 0x17:
        return Notification(opcode, raw, int.from_bytes(raw[2:4], "little"), raw[1])
    if opcode == 0x20:
        return Notification(opcode, raw, int.from_bytes(raw[1:3], "little"))
    return Notification(opcode, raw, raw[1] if opcode in (0x13, 0x22, 0x50) else None)
