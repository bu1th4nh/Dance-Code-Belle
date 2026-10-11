import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dance_code_belle.transport import BleakTransport, discover
from dance_code_belle.protocol import WRITE_UUID, NOTIFY_UUID


class FakeClient:
    instances = []
    missing = False
    def __init__(self, device, **kwargs):
        self.instances.append(self)
        self.is_connected = False
        self.writes = []
        self.services = SimpleNamespace(get_characteristic=self.get_characteristic)
    def get_characteristic(self, uuid):
        if self.missing:
            return None
        return SimpleNamespace(uuid=uuid, service_uuid="verified-service", properties=["write-without-response", "notify"])
    async def connect(self):
        self.is_connected = True
    async def start_notify(self, char, callback):
        self.notify_char, self.callback = char, callback
    async def write_gatt_char(self, char, data, response):
        self.writes.append((char.uuid, data, response))
    async def disconnect(self):
        self.is_connected = False


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_bleak_notification_and_write_contract(self):
        transport = BleakTransport("explicit-device")
        events = []
        with patch("dance_code_belle.transport._bleak", return_value=(FakeClient, None)):
            await transport.connect(events.append)
        client = transport._client
        self.assertEqual(client.notify_char.uuid, NOTIFY_UUID)
        self.assertEqual(client.writes, [])
        client.callback(None, bytearray.fromhex("22 05"))
        self.assertEqual(events, [bytes.fromhex("22 05")])
        await transport.write(bytes.fromhex("10 00 00"))
        self.assertEqual(client.writes, [(WRITE_UUID, bytes.fromhex("10 00 00"), False)])
        with self.assertRaises(ValueError):
            await transport.write(bytes(21))
        await transport.disconnect()
        self.assertFalse(client.is_connected)

    async def test_missing_characteristics_disconnect_without_writes(self):
        transport = BleakTransport("wrong-device")
        with patch.object(FakeClient, "missing", True), patch("dance_code_belle.transport._bleak", return_value=(FakeClient, None)):
            with self.assertRaises(RuntimeError):
                await transport.connect(lambda data: None)
        client = FakeClient.instances[-1]
        self.assertFalse(client.is_connected)
        self.assertEqual(client.writes, [])

    async def test_scan_filters_advertised_name(self):
        belle = SimpleNamespace(name=None, address="one")
        other = SimpleNamespace(name="Makers", address="two")
        class Scanner:
            @staticmethod
            async def discover(**kwargs):
                return {"one": (belle, SimpleNamespace(local_name="DanceCD")),
                        "two": (other, SimpleNamespace(local_name="Makers"))}
        with patch("dance_code_belle.transport._bleak", return_value=(None, Scanner)):
            self.assertEqual(await discover(), [belle])
