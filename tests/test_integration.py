"""Hardware-free integration checks using both real vendor controllers."""
import csv
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox

from database import DatabaseManager
from instruments import Capture, InstrumentSession, MODELS, matching_resources
from main import MainWindow


KEYSIGHT = "USB0::0x0957::0x179B::MY123::INSTR"
SIGLENT = "USB0::0xF4EC::0x1015::SD123::INSTR"
IDNS = {KEYSIGHT: "KEYSIGHT TECHNOLOGIES,DSOX1102G,MY123,01.00",
        SIGLENT: "Siglent Technologies,SDS1202X HD,SD123,6.9.13"}


def ieee_block(payload):
    size = str(len(payload)).encode()
    return b"#" + str(len(size)).encode() + size + payload + b"\n"


class FakeScope:
    def __init__(self, resource, enabled=(1, 2), failing=False):
        self.resource, self.enabled, self.failing = resource, enabled, failing
        self.timeout = 10000
        self.chunk_size = 1024
        self.channel = 1
        self.commands = []
        self.closed = False
        self.last = ""

    def query(self, command):
        self.commands.append(command)
        if command == "*IDN?":
            return IDNS[self.resource]
        if command.endswith(":TRA?"):
            return f"C{command[1]}:TRA {'ON' if int(command[1]) in self.enabled else 'OFF'}"
        if command.endswith(":VDIV?"):
            return f"C{self.channel}:VDIV 0.2V"
        if command.endswith(":OFST?"):
            return "0.1V"
        if command == "TDIV?":
            return "1.0E-6S"
        return {":WAV:XINC?": "1e-9", ":WAV:XOR?": "-2e-9", ":WAV:YINC?": "0.01",
                ":WAV:YOR?": "0.1", ":WAV:YREF?": "128"}[command]

    def write(self, command):
        self.commands.append(command)
        self.last = command
        if command.startswith("WAV:SOUR C"):
            self.channel = int(command[-1])
        if command.startswith(":WAV:SOURCE CHAN"):
            self.channel = int(command[-1])

    def query_binary_values(self, command, **kwargs):
        self.commands.append(command)
        if self.failing:
            raise RuntimeError("Disconnected during transfer")
        return np.array([126, 128, 130, 132], dtype=np.uint8)

    def read_raw(self):
        if self.failing:
            raise RuntimeError("Disconnected during transfer")
        if self.last == "WAV:PRE?":
            payload = bytearray(188)
            struct.pack_into("<f", payload, 0xA4, 100.0)
            struct.pack_into("<H", payload, 0xAC, 12)
            struct.pack_into("<f", payload, 0xB0, 1e-8)
            struct.pack_into("<d", payload, 0xB4, 0.0)
            return ieee_block(payload)
        return ieee_block(np.array([-100, 0, 100, 200], dtype="<i2").tobytes())

    def close(self):
        self.closed = True


class FakeRM:
    opened = []
    enabled = (1, 2)
    failing = False

    def __init__(self):
        self.closed = False

    def list_resources(self):
        return (SIGLENT, KEYSIGHT)

    def open_resource(self, resource, **kwargs):
        scope = FakeScope(resource, self.enabled, self.failing)
        self.opened.append(scope)
        return scope

    def close(self):
        self.closed = True


class ControllerTests(unittest.TestCase):
    def setUp(self):
        FakeRM.opened, FakeRM.enabled, FakeRM.failing = [], (1, 2), False
        self.mock = patch("pyvisa.ResourceManager", FakeRM)
        self.mock.start()
        self.session = InstrumentSession()

    def tearDown(self):
        self.session.close()
        self.mock.stop()

    def test_keysight_decode_and_explicit_resource(self):
        self.assertEqual(matching_resources(MODELS[0], self.session.discover()), (KEYSIGHT,))
        self.session.connect(MODELS[0], KEYSIGHT)
        capture = self.session.capture((1, 2))
        x, y = capture.channels[1]
        np.testing.assert_allclose(x, [-2e-9, -1e-9, 0, 1e-9], atol=1e-20)
        np.testing.assert_allclose(y, [0.08, 0.1, 0.12, 0.14])
        self.assertIn(":WAV:SOURCE CHAN2", FakeRM.opened[-1].commands)
        self.assertEqual(capture.resource, KEYSIGHT)

    def test_siglent_decode_and_off_channel_skip(self):
        FakeRM.enabled = (2,)
        self.session.connect(MODELS[1], SIGLENT)
        capture = self.session.capture((1, 2))
        self.assertEqual(capture.skipped, (1,))
        self.assertEqual(tuple(capture.channels), (2,))
        x, y = capture.channels[2]
        np.testing.assert_allclose(x, -5e-6 + np.arange(4) * 1e-8)
        np.testing.assert_allclose(y, [-0.3, -0.1, 0.1, 0.3])
        self.assertNotIn("WAV:SOUR C1", FakeRM.opened[-1].commands)
        self.assertEqual(FakeRM.opened[-1].commands.count("C2:TRA?"), 1)

    def test_both_off_rejected_before_waveform_commands(self):
        FakeRM.enabled = ()
        self.session.connect(MODELS[1], SIGLENT)
        with self.assertRaisesRegex(RuntimeError, "All selected channels are OFF"):
            self.session.capture((1, 2))
        self.assertNotIn("WAV:PRE?", FakeRM.opened[-1].commands)

    def test_wrong_model_closes_session_before_capture(self):
        with self.assertRaisesRegex(RuntimeError, "identifies as"):
            self.session.connect(MODELS[0], SIGLENT)
        self.assertFalse(self.session.connected)
        self.assertTrue(FakeRM.opened[-1].closed)
        self.assertEqual(FakeRM.opened[-1].commands, ["*IDN?"])

    def test_switch_closes_previous_session(self):
        self.session.connect(MODELS[0], KEYSIGHT)
        first, manager = FakeRM.opened[-1], self.session.controller.rm
        self.session.connect(MODELS[1], SIGLENT)
        self.assertTrue(first.closed)
        self.assertTrue(manager.closed)
        self.assertEqual(self.session.model, MODELS[1])

    def test_siglent_unlocks_before_closing(self):
        self.session.connect(MODELS[1], SIGLENT)
        controller = self.session.controller
        scope, manager = controller.scope, controller.rm
        original_close = scope.close

        def check_unlock_then_close():
            self.assertEqual(scope.commands[-1], ":SYSTem:REMote OFF")
            original_close()

        with patch.object(scope, "close", side_effect=check_unlock_then_close):
            self.session.close()
        self.assertTrue(scope.closed)
        self.assertTrue(manager.closed)
        self.assertIsNone(controller.scope)
        self.assertIsNone(controller.idn)
        self.session.close()  # Repeated disconnect is harmless.
        self.assertEqual(scope.commands.count(":SYSTem:REMote OFF"), 1)

    def test_siglent_unlock_failure_still_cleans_up(self):
        self.session.connect(MODELS[1], SIGLENT)
        controller = self.session.controller
        scope, manager = controller.scope, controller.rm
        with patch.object(scope, "write", side_effect=RuntimeError("Unlock failed")):
            with self.assertRaisesRegex(RuntimeError, "Unlock failed"):
                self.session.close()
        self.assertTrue(scope.closed)
        self.assertTrue(manager.closed)
        self.assertIsNone(controller.scope)
        self.assertIsNone(controller.idn)
        self.assertFalse(self.session.connected)

    def test_siglent_selection_on_keysight_sends_no_unlock(self):
        with self.assertRaisesRegex(RuntimeError, "identifies as"):
            self.session.connect(MODELS[1], KEYSIGHT)
        self.assertEqual(FakeRM.opened[-1].commands, ["*IDN?"])
        self.assertTrue(FakeRM.opened[-1].closed)

    def test_keysight_disconnect_sends_no_siglent_unlock(self):
        self.session.connect(MODELS[0], KEYSIGHT)
        scope = FakeRM.opened[-1]
        self.session.close()
        self.assertNotIn(":SYSTem:REMote OFF", scope.commands)
        self.assertTrue(scope.closed)


class DatabaseTests(unittest.TestCase):
    def test_roundtrip_independent_channel_axes_and_metadata(self):
        db = DatabaseManager(":memory:")
        try:
            capture = Capture({1: (np.arange(3) * 1e-9, np.arange(3) * 0.1),
                               2: (np.arange(5) * 2e-9, np.arange(5) * -0.2)},
                              MODELS[1], IDNS[SIGLENT], SIGLENT)
            i = db.insert_capture(capture, "sample")
            ts, restored, desc = db.load_capture(i)
            self.assertEqual(restored.idn, capture.idn)
            self.assertEqual(restored.resource, SIGLENT)
            for c in (1, 2):
                np.testing.assert_array_equal(restored.channels[c], capture.channels[c])
            self.assertEqual(desc, "sample")
        finally:
            db.close()

    def test_old_keysight_schema_migrates_without_losing_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "old.db")
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE waveforms (id INTEGER PRIMARY KEY, timestamp TEXT, x BLOB, ch1 BLOB, ch2 BLOB, description TEXT)")
            x, y = np.arange(3, dtype=float), np.arange(3, dtype=float) * 0.1
            conn.execute("INSERT INTO waveforms VALUES (1, 'old', ?, ?, ?, 'original')", (x.tobytes(), y.tobytes(), y.tobytes()))
            conn.commit()
            conn.close()
            db = DatabaseManager(path)
            try:
                ts, capture, desc = db.load_capture(1)
                self.assertEqual((ts, desc), ("old", "original"))
                np.testing.assert_array_equal(capture.channels[2][0], x)
                self.assertEqual(capture.instrument, "Legacy capture")
                self.assertEqual(db.get_all_waveforms()[0][-1], "original")
            finally:
                db.close()

    def test_ch2_only_roundtrip(self):
        db = DatabaseManager(":memory:")
        try:
            i = db.insert_capture(Capture({2: (np.arange(3), np.arange(3))}, MODELS[1], "idn", SIGLENT))
            ts, capture, desc = db.load_capture(i)
            self.assertEqual(tuple(capture.channels), (2,))
        finally:
            db.close()


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeRM.opened, FakeRM.enabled, FakeRM.failing = [], (1, 2), False
        self.mock = patch("pyvisa.ResourceManager", FakeRM)
        self.mock.start()
        self.warnings = patch.object(QMessageBox, "warning")
        self.warning = self.warnings.start()
        self.window = MainWindow(":memory:", auto_discover=False)
        self.window.show()

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.app.processEvents()
        self.warnings.stop()
        self.mock.stop()

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.app.processEvents()
        self.assertIsNone(self.window.worker, "Worker did not finish")

    def connect_scope(self, model):
        self.window.model_combo.setCurrentText(model)
        self.window.scan_resources()
        self.wait_idle()
        expected = KEYSIGHT if model == MODELS[0] else SIGLENT
        self.assertEqual(self.window.resource_combo.currentText(), expected)
        self.window.connect_scope()
        self.wait_idle()
        self.assertTrue(self.window.session.connected)

    def test_capture_switch_overlay_csv_and_edit_description(self):
        self.connect_scope(MODELS[0])
        self.window.ch2_check.setChecked(True)
        self.window.description_edit.setText("Keysight sample")
        self.window.manual_capture()
        self.wait_idle()
        self.assertEqual(len(self.window.canvas.ax.lines), 2)
        self.window.disconnect_scope()
        self.wait_idle()
        self.connect_scope(MODELS[1])
        FakeRM.opened[-1].enabled = (2,)
        self.window.description_edit.setText("Siglent sample")
        self.window.manual_capture()
        self.wait_idle()
        self.assertEqual(self.window.table.rowCount(), 2)
        self.assertIn("skipped OFF", self.window.connection_status.text())
        self.window.table.item(0, 3).setText("Edited label")
        self.assertEqual(self.window.db.load_capture(2)[2], "Edited label")
        self.window.table.selectAll()
        self.window.plot_selected()
        self.assertEqual(len(self.window.canvas.ax.lines), 3)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "export.csv")
            with patch("main.QFileDialog.getSaveFileName", return_value=(path, "CSV")):
                self.window.export_selected()
            with open(path, newline="", encoding="utf-8-sig") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(len(rows), 5)
            self.assertEqual(len(rows[0]), 6)
            self.assertIn(SIGLENT, rows[0][0])
            self.assertIn("Edited label", rows[0][0])
        self.assertFalse(self.warning.called)

    def test_auto_transfer_failure_stops_timer(self):
        self.connect_scope(MODELS[1])
        FakeRM.opened[-1].failing = True
        self.window.toggle_auto()
        self.wait_idle()
        self.assertFalse(self.window.timer.isActive())
        self.assertEqual(self.window.auto_btn.text(), "Start Auto")
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertTrue(self.warning.called)

    def test_stop_auto_during_transfer_saves_only_inflight_capture(self):
        self.connect_scope(MODELS[0])
        release = threading.Event()
        original = self.window.session.capture

        def delayed(channels, progress=None):
            release.wait(timeout=3)
            return original(channels, progress)

        with patch.object(self.window.session, "capture", side_effect=delayed):
            self.window.toggle_auto()
            self.assertIsNotNone(self.window.worker)
            self.assertTrue(self.window.auto_btn.isEnabled())
            active_worker = self.window.worker
            self.window.auto_capture()
            self.assertIs(self.window.worker, active_worker)
            self.window.toggle_auto()
            self.assertFalse(self.window.timer.isActive())
            release.set()
            self.wait_idle()
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertFalse(self.warning.called)

    def test_close_waits_for_active_worker(self):
        self.connect_scope(MODELS[0])
        release = threading.Event()
        original = self.window.session.capture

        def delayed(channels, progress=None):
            release.wait(timeout=3)
            return original(channels, progress)

        with patch.object(self.window.session, "capture", side_effect=delayed):
            self.window.manual_capture()
            self.window.close()
            self.assertTrue(self.window._close_requested)
            self.assertTrue(self.window.isVisible())
            release.set()
            self.wait_idle()
        self.assertFalse(self.window.isVisible())
        self.assertTrue(FakeRM.opened[-1].closed)
        # A closed window must not be closed twice in tearDown.
        self.window = MainWindow(":memory:", auto_discover=False)


if __name__ == "__main__":
    unittest.main()
