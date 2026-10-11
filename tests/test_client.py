import asyncio
import unittest
from unittest.mock import patch
from dance_code_belle import Belle, MockTransport
from dance_code_belle import protocol as p


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_close_no_application_commands(self):
        transport = MockTransport()
        async with Belle(transport):
            self.assertTrue(transport.connected)
        self.assertFalse(transport.connected)
        self.assertEqual(transport.packets, [])

    async def test_offline_transcript(self):
        transport = MockTransport()
        async with Belle(transport) as belle:
            await belle.start_remote_mode()
            await belle.speak("eP008", wait=False)
            await belle.stop()
        self.assertEqual(transport.packets, [p.KEEP_ALIVE, bytes.fromhex("10 06 00"), p.STOP_QUEUE, p.STOP_ALL, p.END_APP_MODE])

    async def test_requires_remote_and_movement_opt_in(self):
        transport = MockTransport()
        async with Belle(transport) as belle:
            with self.assertRaises(RuntimeError):
                await belle.speak("eP001", wait=False)
            await belle.start_remote_mode()
            with self.assertRaises(PermissionError):
                await belle.play_sequence("eHLS_Wake_1", wait=False)
        self.assertNotIn(p.play_sequence("eHLS_Wake_1"), transport.packets)

    async def test_matching_completion_only(self):
        transport = MockTransport()
        async with Belle(transport) as belle:
            await belle.start_remote_mode()
            task = asyncio.create_task(belle.speak("eP008", timeout=1))
            await asyncio.sleep(0)
            transport.emit(bytes.fromhex("10 05 00"))
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            transport.emit(bytes.fromhex("10 06 00"))
            self.assertEqual((await task).value, 6)
            self.assertEqual(belle._waiters, [])

    async def test_synchronous_completion_not_lost(self):
        class InstantTransport(MockTransport):
            async def write(self, data):
                await super().write(data)
                if data[0] == 0x10:
                    self.emit(data)
        transport = InstantTransport()
        async with Belle(transport) as belle:
            await belle.start_remote_mode()
            self.assertEqual((await belle.speak("eP001", timeout=.1)).value, 0)

    async def test_timeout_does_not_retry(self):
        transport = MockTransport()
        async with Belle(transport) as belle:
            await belle.start_remote_mode()
            with self.assertRaises(TimeoutError):
                await belle.speak("eP001", timeout=.01)
            self.assertEqual(transport.packets.count(p.play_audio("eP001")), 1)
            self.assertEqual(belle._waiters, [])

    async def test_stop_cancels_wait(self):
        transport = MockTransport()
        async with Belle(transport) as belle:
            await belle.start_remote_mode()
            task = asyncio.create_task(belle.speak("eP001", timeout=1))
            await asyncio.sleep(0)
            await belle.stop()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_movement_completion_uses_type_and_id(self):
        transport = MockTransport()
        async with Belle(transport, allow_sequences=True) as belle:
            await belle.start_remote_mode()
            task = asyncio.create_task(belle.play_sequence("eHLS_Wake_1", timeout=1))
            await asyncio.sleep(0)
            transport.emit(bytes.fromhex("17 01 00 00"))
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            transport.emit(bytes.fromhex("17 02 00 00"))
            self.assertEqual((await task).sequence_type, 2)

    async def test_malformed_and_bounded_event_queue(self):
        transport = MockTransport()
        async with Belle(transport) as belle:
            transport.emit(b"\x10")
            self.assertEqual(belle.malformed_notifications, 1)
            for _ in range(140):
                transport.emit(bytes.fromhex("22 05"))
            self.assertEqual(belle.notifications.qsize(), 128)

    async def test_keepalive_failure_blocks_playback_but_disconnects(self):
        class FailingTransport(MockTransport):
            async def write(self, data):
                if data == p.KEEP_ALIVE and self.packets:
                    raise ConnectionError("lost link")
                await super().write(data)
        transport = FailingTransport()
        async with Belle(transport) as belle:
            await belle.start_remote_mode()
            # Exercise the actual heartbeat without waiting for its one-second timer.
            belle._keepalive.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await belle._keepalive
            async def no_delay(_):
                return None
            with patch("dance_code_belle.client.asyncio.sleep", no_delay):
                await belle._heartbeat()
            with self.assertRaises(ConnectionError):
                await belle.speak("eP001", wait=False)
        self.assertFalse(transport.connected)

    async def test_close_disconnects_even_when_end_mode_fails(self):
        class FailingTransport(MockTransport):
            async def write(self, data):
                if data == p.END_APP_MODE:
                    raise ConnectionError("lost link")
                await super().write(data)
        transport = FailingTransport()
        belle = Belle(transport)
        await belle.connect()
        await belle.start_remote_mode()
        with self.assertRaises(ConnectionError):
            await belle.close()
        self.assertFalse(belle.connected)
        self.assertFalse(transport.connected)
