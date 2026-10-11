import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from dance_code_belle import Belle, MockTransport
from dance_code_belle import protocol as p
from dance_code_belle.ui_controller import UIController


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Worker did not reach expected state")
        time.sleep(.01)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.transport = MockTransport()
        self.worker = UIController(transport_factory=lambda mode, address: self.transport)

    def tearDown(self):
        self.worker.shutdown()

    def test_actions_share_worker_loop_and_thread(self):
        identities = []
        class Tracked(MockTransport):
            async def connect(self, callback):
                identities.append((threading.get_ident(), id(asyncio.get_running_loop())))
                await super().connect(callback)
            async def write(self, data):
                identities.append((threading.get_ident(), id(asyncio.get_running_loop())))
                await super().write(data)
        tracked = Tracked()
        self.worker._factory = lambda mode, address: tracked
        self.worker.connect()
        self.worker.control("read_volume")
        self.worker.stop()
        self.worker.disconnect()
        self.assertEqual(len(set(identities)), 1)
        self.assertNotEqual(identities[0][0], threading.get_ident())

    def test_busy_blocks_second_send_and_mock_completes(self):
        self.worker.connect()
        self.worker.send("audio", "eP008")
        with self.assertRaises(RuntimeError):
            self.worker.send("audio", "eP001")
        until(lambda: not self.worker.snapshot().busy)
        self.assertEqual(self.transport.packets.count(p.play_audio("eP008")), 1)
        self.assertNotIn(p.play_audio("eP001"), self.transport.packets)
        self.assertTrue(any(e["Event"] == "Completed" and e["Detail"].startswith("Simulated") for e in self.worker.events()))

    def test_routines_require_movement_and_correct_packet(self):
        self.worker.connect()
        with self.assertRaises(PermissionError):
            self.worker.send("sequence", "eHLS_DanceInstruct_1")
        self.worker.send("sequence", "eHLS_DanceInstruct_1", allow_movement=True)
        until(lambda: not self.worker.snapshot().busy)
        self.assertIn(bytes.fromhex("17 02 3b 00"), self.transport.packets)

    def test_stop_during_playback_and_disconnect(self):
        self.worker.connect()
        self.worker.send("audio", "eP001")
        self.worker.stop()
        self.assertFalse(self.worker.snapshot().busy)
        self.assertEqual(self.transport.packets[-2:], [p.STOP_QUEUE, p.STOP_ALL])
        self.worker.disconnect()
        self.assertFalse(self.transport.connected)
        self.assertEqual(self.transport.packets[-1], p.END_APP_MODE)

    def test_completion_timeout_blocks_without_repeating(self):
        class SilentTransport:
            def __init__(self):
                self.packets = []
            async def connect(self, callback):
                pass
            async def write(self, packet):
                self.packets.append(packet)
            async def disconnect(self):
                pass
        silent = SilentTransport()
        self.worker._factory = lambda mode, address: silent
        original = Belle.speak
        async def short_timeout(belle, name):
            return await original(belle, name, timeout=.02)
        self.worker.connect()
        with patch.object(Belle, "speak", short_timeout):
            self.worker.send("audio", "eP001")
            until(lambda: not self.worker.snapshot().busy)
        self.assertTrue(self.worker.snapshot().blocked)
        self.assertEqual(silent.packets.count(p.play_audio("eP001")), 1)
        self.assertEqual(silent.packets[-2:], [p.STOP_QUEUE, p.STOP_ALL])
        with self.assertRaises(RuntimeError):
            self.worker.send("audio", "eP001")
        self.worker.stop()
        self.assertFalse(self.worker.snapshot().blocked)

    def test_volume_and_input_routes(self):
        self.worker.connect()
        self.worker.control("volume", 4)
        until(lambda: self.worker.snapshot().volume == 4)
        self.worker.control("read_input")
        self.assertIn(bytes.fromhex("23 04"), self.transport.packets)
        self.assertIn(p.REQUEST_INPUT, self.transport.packets)
        with self.assertRaises(ValueError):
            self.worker.control("raw", 0)
        with self.assertRaises(ValueError):
            self.worker.send("audio", "eP007")

    def test_single_device_owner_and_release(self):
        other = UIController(transport_factory=lambda mode, address: MockTransport())
        try:
            self.worker.connect("bluetooth", "FAKE-DEVICE")
            with self.assertRaises(RuntimeError):
                other.connect("bluetooth", "fake-device")
            self.worker.disconnect()
            other.connect("bluetooth", "fake-device")
            self.assertTrue(other.snapshot().connected)
        finally:
            other.shutdown()

    def test_abandoned_session_stops_and_disconnects(self):
        transport = MockTransport()
        worker = UIController(lease_seconds=.3, transport_factory=lambda mode, address: transport)
        try:
            worker.connect()
            until(lambda: worker.snapshot().closed)
            self.assertFalse(transport.connected)
            self.assertIn(p.STOP_ALL, transport.packets)
            self.assertIn(p.END_APP_MODE, transport.packets)
        finally:
            worker.shutdown()

    def test_failed_connect_releases_device(self):
        class Broken(MockTransport):
            async def connect(self, callback):
                raise ConnectionError("pairing failed")
        self.worker._factory = lambda mode, address: Broken()
        with self.assertRaises(ConnectionError):
            self.worker.connect("bluetooth", "test-device")
        self.worker._factory = lambda mode, address: self.transport
        self.worker.connect("bluetooth", "test-device")
        self.assertTrue(self.worker.snapshot().connected)

    def test_keepalive_failure_closes_connection(self):
        class BrokenHeartbeat(MockTransport):
            async def write(self, packet):
                if packet == p.KEEP_ALIVE and p.KEEP_ALIVE in self.packets:
                    raise ConnectionError("lost Bluetooth link")
                await super().write(packet)
        transport = BrokenHeartbeat()
        self.worker._factory = lambda mode, address: transport
        self.worker.connect()
        until(lambda: self.worker.snapshot().status == "Connection lost")
        self.assertFalse(transport.connected)
        self.assertFalse(self.worker.snapshot().connected)
        self.assertIn("lost Bluetooth link", self.worker.snapshot().error)
