"""Injectable offline transport and optional Bleak adapter."""
from collections.abc import Callable
from typing import Protocol
from .protocol import WRITE_UUID, NOTIFY_UUID, TOY_NAME


class Transport(Protocol):
    async def connect(self, callback: Callable[[bytes], None]) -> None: ...
    async def write(self, data: bytes) -> None: ...
    async def disconnect(self) -> None: ...


class MockTransport:
    """Record packets; explicit emit() supplies simulated doll notifications."""
    def __init__(self):
        self.packets: list[bytes] = []
        self.connected = False
        self._callback = None

    async def connect(self, callback):
        self._callback = callback
        self.connected = True

    async def write(self, data):
        if not self.connected:
            raise ConnectionError("Transport is disconnected")
        self.packets.append(bytes(data))

    def emit(self, data: bytes):
        if not self.connected:
            raise ConnectionError("Transport is disconnected")
        self._callback(bytes(data))

    async def disconnect(self):
        self.connected = False
        self._callback = None


def _bleak():
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        raise RuntimeError('Install Bluetooth support: pip install "dance-code-belle[ble]"') from None
    return BleakClient, BleakScanner


async def discover(timeout: float = 10.0):
    """Scan for the exact source name; return BLEDevice objects without connecting."""
    _, scanner = _bleak()
    devices = await scanner.discover(timeout=timeout, return_adv=True)
    return [device for device, adv in devices.values()
            if (adv.local_name or device.name) == TOY_NAME]


class BleakTransport:
    def __init__(self, device, *, timeout: float = 10.0):
        self.device = device
        self.timeout = timeout
        self._client = None
        self._write_char = None

    async def connect(self, callback):
        if self._client is not None:
            raise RuntimeError("Already connected")
        client_type, _ = _bleak()
        client = client_type(self.device, timeout=self.timeout)
        try:
            await client.connect()
            write = client.services.get_characteristic(WRITE_UUID)
            notify = client.services.get_characteristic(NOTIFY_UUID)
            if write is None or notify is None:
                raise RuntimeError("Belle's characteristics were not found; no commands sent")
            if write.service_uuid.lower() != notify.service_uuid.lower():
                raise RuntimeError("Belle's characteristics must belong to the same service")
            if "write-without-response" not in write.properties:
                raise RuntimeError("Expected write-without-response characteristic")
            await client.start_notify(notify, lambda sender, data: callback(bytes(data)))
            self._client, self._write_char = client, write
        except BaseException:
            await client.disconnect()
            raise

    async def write(self, data):
        if self._client is None or not self._client.is_connected:
            raise ConnectionError("Bluetooth is disconnected")
        if not data or len(data) > 20:
            raise ValueError("Packet length must be 1–20 bytes")
        await self._client.write_gatt_char(self._write_char, data, response=False)

    async def disconnect(self):
        client, self._client = self._client, None
        self._write_char = None
        if client is not None:
            await client.disconnect()
