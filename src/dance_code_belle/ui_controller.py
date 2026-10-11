"""Persistent async worker for UI reruns. Never calls Streamlit from its thread."""
import asyncio
import atexit
from collections import deque
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
import threading
import time
import weakref

from .catalog import resolve
from .client import Belle
from . import protocol as p
from .transport import BleakTransport, MockTransport, discover

_WORKERS = weakref.WeakSet()
_DEVICE_OWNERS = {}
_DEVICE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ControllerState:
    connected: bool
    busy: bool
    blocked: bool
    mode: str
    status: str
    error: str
    volume: int | None
    closed: bool


class _RecordedTransport:
    def __init__(self, delegate, record, receive):
        self.delegate, self.record, self.receive = delegate, record, receive
        self._replies = set()

    async def connect(self, callback):
        def received(data):
            self.receive(data)
            callback(data)
        await self.delegate.connect(received)

    async def write(self, packet):
        await self.delegate.write(packet)
        self.record("Keep-alive" if packet == p.KEEP_ALIVE else "Sent", packet.hex(" "))
        # Simulated completion is clearly marked and only exists in mock mode.
        if isinstance(self.delegate, MockTransport):
            if packet in (p.STOP_QUEUE, p.STOP_ALL):
                for reply in self._replies:
                    reply.cancel()
                self._replies.clear()
            response = None
            if packet[0] == 0x10:
                response = packet
            elif packet[:2] == b"\x17\x02":
                response = packet
            elif packet == p.REQUEST_VOLUME:
                response = b"\x22\x03"
            elif packet[0] == 0x23:
                response = b"\x22" + packet[1:]
            elif packet == p.REQUEST_INPUT:
                response = b"\x20\x00\x00"
            if response is not None:
                def emit():
                    self._replies.discard(handle)
                    if self.delegate.connected:
                        self.record("Mock", "Simulated reply: " + response.hex(" "))
                        self.delegate.emit(response)
                handle = asyncio.get_running_loop().call_later(0.2, emit)
                self._replies.add(handle)

    async def disconnect(self):
        for reply in self._replies:
            reply.cancel()
        self._replies.clear()
        await self.delegate.disconnect()


class UIController:
    """One worker per browser session, with a 75-second browser activity lease.

    All Bluetooth operations and keep-alives use one long-lived asyncio loop.
    A closed browser stops refreshing touch(); the worker stops and disconnects.
    """
    def __init__(self, *, lease_seconds=75.0, transport_factory=None):
        if lease_seconds <= 0:
            raise ValueError("Lease must be positive")
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._lease = lease_seconds
        self._seen = time.monotonic()
        self._factory = transport_factory
        self._events = deque(maxlen=200)
        self._connected = self._busy = self._blocked = self._closed = False
        self._mode = "mock"
        self._status, self._error = "Disconnected", ""
        self._volume = None
        self._belle = self._task = None
        self._devices = {}
        self._address = None
        self._thread = threading.Thread(target=self._worker, name="Belle controller", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("Controller worker did not start")
        _WORKERS.add(self)

    def _worker(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._watchdog())
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self._loop)
            for task in tasks:
                task.cancel()
            self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self._loop.close()
            with self._lock:
                self._closed = True

    def _set(self, **values):
        with self._lock:
            for key, value in values.items():
                setattr(self, "_" + key, value)

    def _record(self, kind, detail):
        with self._lock:
            self._events.append({"Time": datetime.now().strftime("%H:%M:%S"), "Event": kind, "Detail": detail})

    def _receive(self, data):
        try:
            event = p.parse_notification(data)
        except ValueError as exc:
            self._record("Malformed reply", str(exc))
            return
        self._record("Received", bytes(data).hex(" "))
        if event.opcode == 0x22:
            self._set(volume=event.value)

    def touch(self):
        with self._lock:
            self._seen = time.monotonic()

    def snapshot(self):
        with self._lock:
            return ControllerState(self._connected, self._busy, self._blocked, self._mode,
                                   self._status, self._error, self._volume, self._closed)

    def events(self, *, include_keepalive=False):
        with self._lock:
            return [dict(event) for event in reversed(self._events)
                    if include_keepalive or event["Event"] != "Keep-alive"]

    async def _invoke(self, action, *args):
        return await action(*args)

    def _call(self, action, *args, timeout=20):
        if self.snapshot().closed or not self._thread.is_alive():
            raise RuntimeError("Controller expired; refresh the page to reconnect")
        self.touch()
        future = asyncio.run_coroutine_threadsafe(self._invoke(action, *args), self._loop)
        try:
            return future.result(timeout)
        except FutureTimeout:
            if future.done():
                raise
            future.cancel()
            raise TimeoutError("Operation timed out; do not repeat a playback command") from None

    def scan(self):
        return self._call(self._scan)

    async def _scan(self):
        if self._belle is not None:
            raise RuntimeError("Disconnect before scanning")
        devices = await discover()
        self._devices = {device.address: device for device in devices}
        self._record("Scan", f"Found {len(devices)} DanceCD device(s)")
        return [{"address": device.address, "name": device.name or "DanceCD"} for device in devices]

    def connect(self, mode="mock", address=""):
        return self._call(self._connect, mode, address)

    async def _connect(self, mode, address):
        if self._belle is not None:
            raise RuntimeError("Already connected or connecting")
        if mode not in ("mock", "bluetooth"):
            raise ValueError("Unknown connection mode")
        if mode == "bluetooth":
            address = address.strip()
            if not address.strip():
                raise ValueError("Choose or enter Belle's device address")
            with _DEVICE_LOCK:
                if address.lower() in _DEVICE_OWNERS:
                    raise RuntimeError("This Belle is already controlled by another app session")
                _DEVICE_OWNERS[address.lower()] = self
            self._address = address.lower()
        self._set(mode=mode, status="Connecting", error="", volume=None)
        try:
            delegate = (self._factory(mode, address) if self._factory else
                        MockTransport() if mode == "mock" else
                        BleakTransport(self._devices.get(address, address)))
            transport = _RecordedTransport(delegate, self._record, self._receive)
            self._belle = Belle(transport)
            await self._belle.connect()
            await self._belle.start_remote_mode()
            self._set(connected=True, blocked=False, status="Connected to mock" if mode == "mock" else "Connected to Belle")
            self._record("Connected", "Offline mock" if mode == "mock" else address)
        except BaseException:
            try:
                if self._belle is not None:
                    await self._belle.close()
            finally:
                self._belle = None
                self._release_device()
                self._set(connected=False, status="Connection failed")
            raise

    def send(self, kind, name, *, allow_movement=False):
        return self._call(self._launch, kind, name, allow_movement)

    async def _launch(self, kind, name, allow_movement):
        if self._belle is None or not self._connected:
            raise ConnectionError("Connect first")
        if self._busy:
            raise RuntimeError("Playback is already active; wait or press Stop")
        if self._blocked:
            raise RuntimeError("Playback was not confirmed; press Stop before sending again")
        if kind not in ("audio", "sequence"):
            raise ValueError("Unknown command group")
        resolve(name, sequence=kind == "sequence")
        if kind == "sequence" and not allow_movement:
            raise PermissionError("Enable high-level routines before sending; they may move Belle")
        self._belle.allow_sequences = allow_movement
        self._set(busy=True, error="", status="Playing " + name)
        self._task = asyncio.create_task(self._play(kind, name))

    async def _play(self, kind, name):
        try:
            if kind == "audio":
                await self._belle.speak(name)
            else:
                await self._belle.play_sequence(name)
            self._set(status="Completed " + name)
            self._record("Completed", ("Simulated: " if self._mode == "mock" else "") + name)
        except asyncio.CancelledError:
            self._record("Cancelled", name)
        except Exception as exc:
            self._set(blocked=True, error=str(exc), status="Playback unconfirmed")
            self._record("Error", str(exc))
            with suppress(Exception):
                await self._belle.stop()
        finally:
            self._set(busy=False)
            self._task = None

    def stop(self):
        return self._call(self._stop)

    async def _cancel_playback(self):
        task = self._task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _stop(self):
        if self._belle is None:
            raise ConnectionError("Connect first")
        await self._cancel_playback()
        await self._belle.stop()
        self._set(busy=False, blocked=False, error="", status="Stop sent")
        self._record("Stopped", "Queue and active-sequence stop commands sent")

    def control(self, action, value=None):
        return self._call(self._control, action, value)

    async def _control(self, action, value):
        if self._belle is None:
            raise ConnectionError("Connect first")
        if action == "volume":
            await self._belle.set_volume(value)
        elif action == "read_volume":
            await self._belle.request_volume()
        elif action == "read_input":
            await self._belle.request_input()
        else:
            raise ValueError("Unknown control")

    def disconnect(self):
        return self._call(self._disconnect)

    def _release_device(self):
        with _DEVICE_LOCK:
            if self._address is not None:
                _DEVICE_OWNERS.pop(self._address, None)
                self._address = None

    async def _disconnect(self):
        belle = self._belle
        try:
            await self._cancel_playback()
            if belle is not None:
                try:
                    await belle.stop()
                finally:
                    await belle.close()
        finally:
            self._belle = None
            self._release_device()
            self._set(connected=False, busy=False, blocked=False, status="Disconnected")
            self._record("Disconnected", "Connection closed")

    async def _watchdog(self):
        while True:
            await asyncio.sleep(0.1)
            with self._lock:
                expired = time.monotonic() - self._seen > self._lease
            if self._belle is not None and self._belle.connection_error is not None:
                error = str(self._belle.connection_error)
                with suppress(Exception):
                    await self._disconnect()
                self._set(error="Connection lost: " + error, status="Connection lost")
            if expired:
                with suppress(Exception):
                    await self._disconnect()
                self._set(closed=True, status="Browser session expired")
                self._loop.call_soon(self._loop.stop)
                return

    def shutdown(self):
        if self.snapshot().closed or not self._thread.is_alive():
            return
        try:
            self._call(self._disconnect, timeout=5)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


@atexit.register
def _close_workers():
    for worker in tuple(_WORKERS):
        worker.shutdown()
