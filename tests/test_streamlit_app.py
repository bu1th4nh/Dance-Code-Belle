from pathlib import Path
import time
import unittest

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, "Install the ui extra to test the Streamlit app")
class AppTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py")).run()

    def tearDown(self):
        self.app.session_state.belle_controller.shutdown()

    def button(self, label):
        return next(button for button in self.app.button if button.label == label)

    def test_default_mock_and_grid_preview_never_transmit(self):
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key="connection_mode").value, "Mock · offline")
        self.assertFalse(self.button("Connect").disabled)
        self.app.button(key="grid_audio_eP008").click().run()
        self.assertEqual(self.app.code[0].value, "10 06 00")
        self.assertTrue(self.app.button(key="send_selected").disabled)
        self.assertEqual(self.app.session_state.belle_controller.events(), [])

    def test_connect_send_and_disconnect_persist_worker(self):
        worker = self.app.session_state.belle_controller
        self.button("Connect").click().run()
        self.assertIs(self.app.session_state.belle_controller, worker)
        self.assertTrue(worker.snapshot().connected)
        self.app.text_input(key="filter").set_value("eP008").run()
        self.app.button(key="grid_audio_eP008").click().run()
        self.app.button(key="send_selected").click().run()
        time.sleep(.3)
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any(e["Event"] == "Sent" and e["Detail"] == "10 06 00" for e in worker.events()))
        self.button("Disconnect").click().run()
        self.assertFalse(worker.snapshot().connected)

    def test_routine_grid_send_is_locked_without_opt_in(self):
        self.button("Connect").click().run()
        self.app.radio(key="group").set_value("High-level routines").run()
        self.app.text_input(key="filter").set_value("DanceInstruct_1").run()
        self.app.button(key="grid_sequence_eHLS_DanceInstruct_1").click().run()
        self.assertEqual(self.app.code[0].value, "17 02 3b 00")
        self.assertTrue(self.app.button(key="send_selected").disabled)
        self.app.checkbox(key="allow_movement").check().run()
        self.assertFalse(self.app.button(key="send_selected").disabled)

    def test_bluetooth_requires_target_and_does_not_auto_connect(self):
        self.app.radio(key="connection_mode").set_value("Bluetooth · physical Belle").run()
        self.assertTrue(self.button("Connect").disabled)
        self.assertFalse(self.app.session_state.belle_controller.snapshot().connected)
        self.assertFalse(self.app.exception)

    def test_direct_grid_send_keeps_stop_available(self):
        self.button("Connect").click().run()
        self.app.toggle(key="direct_send").set_value(True).run()
        self.app.button(key="grid_audio_eP008").click().run()
        worker = self.app.session_state.belle_controller
        self.assertTrue(any(e["Event"] == "Sent" and e["Detail"] == "10 06 00" for e in worker.events()))
        self.assertFalse(self.app.button(key="stop").disabled)
        self.app.button(key="stop").click().run()
        self.assertFalse(worker.snapshot().busy)
