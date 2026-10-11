"""Small async controller with explicit remote mode and no automatic choreography."""
import asyncio
from contextlib import suppress
from . import protocol as p
from .catalog import resolve
from .transport import Transport


class Belle:
    def __init__(self, transport: Transport, *, allow_sequences: bool = False):
        self.transport = transport
        self.allow_sequences = allow_sequences
        self.connected = False
        self._remote = False
        self._keepalive = None
        self._health_error = None
        self._write_lock = asyncio.Lock()
        self._play_lock = asyncio.Lock()
        self._waiters = []
        self.notifications: asyncio.Queue[p.Notification] = asyncio.Queue(maxsize=128)
        self.malformed_notifications = 0

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            await self.close()
        except Exception:
            if exc_type is None:
                raise

    async def connect(self):
        if self.connected:
            raise RuntimeError("Already connected")
        await self.transport.connect(self._on_notification)
        self.connected = True
        self._health_error = None

    def _on_notification(self, data):
        try:
            event = p.parse_notification(data)
        except ValueError:
            self.malformed_notifications += 1
            return
        if self.notifications.full():
            self.notifications.get_nowait()
        self.notifications.put_nowait(event)
        for match, future in tuple(self._waiters):
            if not future.done() and match(event):
                future.set_result(event)

    async def _send(self, packet, *, cleanup=False):
        if not self.connected:
            raise ConnectionError("Belle is not connected")
        if self._health_error is not None and not cleanup:
            raise ConnectionError("Keep-alive failed; close and reconnect before sending") from self._health_error
        async with self._write_lock:
            await self.transport.write(packet)

    async def start_remote_mode(self):
        """Send 50 8d and maintain it every second, as in BLEToyAPI.Update."""
        if self._remote:
            if self._health_error is not None:
                raise ConnectionError("Keep-alive failed; close and reconnect") from self._health_error
            return
        await self._send(p.KEEP_ALIVE)
        self._remote = True
        self._keepalive = asyncio.create_task(self._heartbeat())

    async def _heartbeat(self):
        try:
            while True:
                await asyncio.sleep(1.0)
                await self._send(p.KEEP_ALIVE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._health_error = exc

    async def end_remote_mode(self):
        if self._keepalive is not None:
            self._keepalive.cancel()
            with suppress(asyncio.CancelledError):
                await self._keepalive
            self._keepalive = None
        if self._remote:
            try:
                await self._send(p.END_APP_MODE, cleanup=True)
            finally:
                self._remote = False

    def _require_remote(self):
        if not self._remote:
            raise RuntimeError("Call start_remote_mode() before playback")

    async def speak(self, phrase: str | int, *, wait: bool = True, timeout: float | None = None):
        """Play an existing phrase, not arbitrary text. Wait for matching completion."""
        entry = resolve(phrase)
        self._require_remote()
        async with self._play_lock:
            return await self._play(p.play_audio(phrase),
                                    lambda event: event.opcode == 0x10 and event.value == entry.id,
                                    wait, timeout if timeout is not None else max(5.0, entry.duration + 3.0))

    async def play_sequence(self, sequence: str | int, *, wait: bool = True, timeout: float | None = None):
        """A named high-level routine can move motors; requires allow_sequences=True."""
        if not self.allow_sequences:
            raise PermissionError("High-level routines may move Belle; set allow_sequences=True")
        entry = resolve(sequence, sequence=True)
        self._require_remote()
        async with self._play_lock:
            return await self._play(p.play_sequence(sequence),
                                    lambda event: event.opcode == 0x17 and event.sequence_type == 2 and event.value == entry.id,
                                    wait, timeout if timeout is not None else max(5.0, entry.duration + 3.0))

    async def _play(self, packet, match, wait, timeout):
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        if not wait:
            await self._send(packet)
            return None
        future = asyncio.get_running_loop().create_future()
        waiter = (match, future)
        self._waiters.append(waiter)
        try:
            await self._send(packet)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._waiters.remove(waiter)
            if not future.done():
                future.cancel()

    async def request_input(self):
        await self._send(p.REQUEST_INPUT)

    async def request_volume(self):
        await self._send(p.REQUEST_VOLUME)

    async def set_volume(self, volume: int):
        await self._send(p.set_volume(volume))

    async def stop(self):
        """Stop queued and active sequences; completion waits are cancelled."""
        for _, future in tuple(self._waiters):
            if not future.done():
                future.cancel()
        try:
            await self._send(p.STOP_QUEUE, cleanup=True)
        finally:
            await self._send(p.STOP_ALL, cleanup=True)

    async def close(self):
        if not self.connected:
            return
        for _, future in tuple(self._waiters):
            if not future.done():
                future.cancel()
        try:
            await self.end_remote_mode()
        finally:
            try:
                await self.transport.disconnect()
            finally:
                self.connected = False
