"""UniversalScope GUI. Run with: python main.py"""
import csv
import math
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from database import DatabaseManager
from instruments import MODELS, InstrumentSession, matching_resources
from plot_widgets import HelpDialog, MplCanvas


class InstrumentThread(QThread):
    """Perform one operation; the GUI reads the result after finished."""
    progress = Signal(str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.action(self.progress.emit)
        except Exception as exc:
            self.error = str(exc)


class MainWindow(QMainWindow):
    def __init__(self, db_file=None, auto_discover=True):
        super().__init__()
        self.session = InstrumentSession()
        # Keep data beside this app, independent of the shell working folder.
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        self.db = DatabaseManager(db_file if db_file is not None else base / "waveforms.db")
        self.worker = None
        self._close_requested = False
        self.resources = ()
        self.help_dialog = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.auto_capture)
        self.setWindowTitle("UniversalScope — Keysight / Siglent")
        self.resize(1400, 820)

        self.model_combo = QComboBox()
        self.model_combo.addItems(MODELS)
        self.resource_combo = QComboBox()
        self.resource_combo.setEditable(True)
        self.resource_combo.setMinimumWidth(420)
        self.resource_combo.setToolTip("Select a discovered VISA resource, or enter a USB/TCPIP resource directly.")
        self.scan_btn = QPushButton("Scan")
        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")
        connection_layout = QHBoxLayout()
        for widget in (QLabel("Instrument:"), self.model_combo, QLabel("VISA resource:"),
                       self.resource_combo, self.scan_btn, self.connect_btn, self.disconnect_btn):
            connection_layout.addWidget(widget)
        connection_layout.addStretch()
        connection_group = QGroupBox("Connection")
        connection_group.setLayout(connection_layout)

        self.interval_edit = QLineEdit("1.0")
        self.interval_edit.setMaximumWidth(75)
        self.ch1_check, self.ch2_check = QCheckBox("CH1"), QCheckBox("CH2")
        self.ch1_check.setChecked(True)
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Label for new captures")
        self.capture_btn = QPushButton("Manual Capture")
        self.auto_btn = QPushButton("Start Auto")
        self.plot_btn = QPushButton("Plot Selected")
        self.export_btn = QPushButton("Export Selected")
        self.delete_btn = QPushButton("Delete Selected")
        capture_layout = QHBoxLayout()
        for widget in (self.capture_btn, self.auto_btn, QLabel("Interval (s):"), self.interval_edit,
                       self.ch1_check, self.ch2_check, QLabel("Description:"), self.description_edit):
            capture_layout.addWidget(widget)
        capture_group = QGroupBox("Acquisition")
        capture_group.setLayout(capture_layout)

        self.canvas = MplCanvas()
        self.plot_toolbar = NavigationToolbar(self.canvas, self)
        self.keep_view_check, self.time_only_check = QCheckBox("Keep view"), QCheckBox("Time only")
        self.keep_view_check.setChecked(True)
        self.time_only_check.setChecked(True)
        self.keep_view_check.toggled.connect(self.canvas.set_keep_view)
        self.time_only_check.toggled.connect(self.canvas.set_time_only)
        self.help_btn = QPushButton("Help")
        self.help_btn.setShortcut("F1")
        view_layout = QHBoxLayout()
        view_layout.addWidget(self.keep_view_check)
        view_layout.addWidget(self.time_only_check)
        view_layout.addStretch()
        view_layout.addWidget(self.help_btn)
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(self.plot_toolbar)
        plot_layout.addLayout(view_layout)
        plot_layout.addWidget(self.canvas)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "Timestamp", "Instrument", "Description"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumWidth(470)
        saved_buttons = QHBoxLayout()
        for button in (self.plot_btn, self.export_btn, self.delete_btn):
            saved_buttons.addWidget(button)
        saved_layout = QVBoxLayout()
        saved_layout.addWidget(self.table)
        saved_layout.addLayout(saved_buttons)
        split_layout = QHBoxLayout()
        split_layout.addLayout(plot_layout, 3)
        split_layout.addLayout(saved_layout, 2)
        layout = QVBoxLayout()
        layout.addWidget(connection_group)
        layout.addWidget(capture_group)
        layout.addLayout(split_layout)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.connection_status = QLabel("Disconnected")
        self.connection_progress = QProgressBar()
        self.connection_progress.setRange(0, 0)
        self.connection_progress.setFixedWidth(120)
        self.connection_progress.hide()
        self.statusBar().addWidget(self.connection_status, 1)
        self.statusBar().addPermanentWidget(self.connection_progress)

        self.model_combo.currentTextChanged.connect(self.populate_resources)
        self.scan_btn.clicked.connect(self.scan_resources)
        self.connect_btn.clicked.connect(self.connect_scope)
        self.disconnect_btn.clicked.connect(self.disconnect_scope)
        self.capture_btn.clicked.connect(self.manual_capture)
        self.auto_btn.clicked.connect(self.toggle_auto)
        self.plot_btn.clicked.connect(self.plot_selected)
        self.export_btn.clicked.connect(self.export_selected)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.table.cellClicked.connect(self.load_from_db)
        self.table.cellChanged.connect(self.update_description_from_table)
        self.help_btn.clicked.connect(self.show_help)
        self.refresh_table()
        self.update_controls()
        if auto_discover:
            QTimer.singleShot(0, self.scan_resources)

    def update_controls(self):
        busy, connected, auto = self.worker is not None, self.session.connected, self.timer.isActive()
        selectable = not busy and not connected and not self._close_requested
        for widget in (self.model_combo, self.resource_combo, self.scan_btn):
            widget.setEnabled(selectable)
        self.connect_btn.setEnabled(not busy and not auto and not self._close_requested)
        self.connect_btn.setText("Reconnect" if connected else "Connect")
        self.disconnect_btn.setEnabled(connected and not busy and not self._close_requested)
        self.capture_btn.setEnabled(connected and not busy and not auto and not self._close_requested)
        # Stop Auto remains available during a long transfer.
        self.auto_btn.setEnabled(not self._close_requested and connected and (auto or not busy))
        self.auto_btn.setText("Stop Auto" if auto else "Start Auto")
        for widget in (self.interval_edit, self.ch1_check, self.ch2_check):
            widget.setEnabled(not busy and not auto and not self._close_requested)

    def start_operation(self, action, completed, title, status):
        if self.worker is not None or self._close_requested:
            return
        self.connection_status.setText(status)
        self.connection_progress.show()
        worker = InstrumentThread(action, self)
        self.worker = worker
        worker.progress.connect(self.connection_status.setText)

        def finish():
            self.worker = None
            self.connection_progress.hide()
            error = worker.error
            result = worker.result
            worker.deleteLater()
            if self._close_requested:
                self.close()
                return
            try:
                if error is not None:
                    raise RuntimeError(error)
                completed(result)
            except Exception as exc:
                self.timer.stop()
                self.connection_status.setText(f"{title}: {exc}")
                self.update_controls()
                QMessageBox.warning(self, title, str(exc))
            self.update_controls()

        worker.finished.connect(finish)
        self.update_controls()
        worker.start()

    def scan_resources(self):
        if self.session.connected:
            return
        self.start_operation(lambda report: self.session.discover(), self.resources_found,
                             "VISA discovery failed", "Searching for instruments...")

    def resources_found(self, resources):
        self.resources = resources
        self.populate_resources()
        self.connection_status.setText(f"Found {len(resources)} VISA resource(s). Select an instrument and connect.")

    def populate_resources(self, *args):
        old = self.resource_combo.currentText()
        matches = matching_resources(self.model_combo.currentText(), self.resources)
        self.resource_combo.clear()
        self.resource_combo.addItems(list(matches) + [r for r in self.resources if r not in matches])
        # A sole matching USB resource is safe to suggest. Multiple resources
        # require an explicit choice; Connect never guesses resources[0].
        self.resource_combo.setCurrentIndex(-1)
        if len(matches) == 1:
            self.resource_combo.setCurrentText(matches[0])
        elif old and old not in self.resources:
            self.resource_combo.setCurrentText(old)

    def connect_scope(self):
        resource = self.resource_combo.currentText().strip()
        if not resource:
            QMessageBox.warning(self, "Choose a resource", "Select or enter the scope's VISA resource first.")
            return
        model = self.model_combo.currentText()
        self.start_operation(lambda report: self.session.connect(model, resource, report),
                             lambda idn: self.connection_status.setText(f"Connected: {idn}"),
                             "Connection failed", "Opening instrument connection...")

    def disconnect_scope(self):
        self.timer.stop()
        self.start_operation(lambda report: self.session.close(),
                             lambda result: self.connection_status.setText("Disconnected"),
                             "Disconnect failed", "Closing instrument connection...")

    def selected_channels(self):
        return tuple(c for c, box in ((1, self.ch1_check), (2, self.ch2_check)) if box.isChecked())

    def request_capture(self, show_plot):
        if self.worker is not None or self._close_requested:
            return
        channels = self.selected_channels()
        if not channels:
            self.timer.stop()
            self.update_controls()
            QMessageBox.warning(self, "No Channel Selected", "Select CH1, CH2, or both before capturing.")
            return
        description = self.description_edit.text()

        def captured(capture):
            capture_id = self.db.insert_capture(capture, description)
            self.refresh_table()
            if show_plot:
                self.plot_capture(capture, f"#{capture_id} — {capture.instrument}")
            samples = ", ".join(f"CH{c}: {len(y):,} samples" for c, (x, y) in capture.channels.items())
            skipped = f"; skipped OFF channel(s): {', '.join('CH'+str(c) for c in capture.skipped)}" if capture.skipped else ""
            self.connection_status.setText(f"Saved #{capture_id} — {samples}{skipped}")

        self.start_operation(lambda report: self.session.capture(channels, report), captured,
                             "Acquisition failed", "Acquiring selected channels...")

    def manual_capture(self):
        self.request_capture(show_plot=True)

    def auto_capture(self):
        # Timer ticks during transfers are skipped, preventing queued captures.
        self.request_capture(show_plot=False)

    def toggle_auto(self):
        if self.timer.isActive():
            self.timer.stop()
            self.connection_status.setText("Auto capture stopped; any active transfer will finish and save.")
        else:
            if not self.selected_channels():
                QMessageBox.warning(self, "No Channel Selected", "Select at least one channel.")
                return
            try:
                interval = float(self.interval_edit.text())
                if not math.isfinite(interval) or not 0.001 <= interval <= 2147483:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Invalid interval", "Enter an interval between 0.001 and 2147483 seconds.")
                return
            self.timer.start(max(1, int(interval * 1000)))
            self.auto_capture()
        self.update_controls()

    def plot_capture(self, capture, label_suffix=""):
        view = self.canvas.begin_plot()
        self.add_capture_to_plot(capture, label_suffix)
        self.canvas.finish_plot(view)

    def add_capture_to_plot(self, capture, label_suffix):
        for channel in self.selected_channels():
            if channel in capture.channels:
                x, y = capture.channels[channel]
                self.canvas.ax.plot(x, y, linewidth=0.8, label=f"CH{channel} {label_suffix}")

    def selected_ids(self):
        return [int(self.table.item(row, 0).text()) for row in sorted({i.row() for i in self.table.selectedIndexes()})]

    def plot_selected(self):
        ids = self.selected_ids()
        if not ids:
            QMessageBox.warning(self, "Select captures", "Select at least one saved capture.")
            return
        try:
            captures = [(i, self.db.load_capture(i)) for i in ids]
            view = self.canvas.begin_plot()
            for i, (ts, capture, desc) in captures:
                self.add_capture_to_plot(capture, f"#{i} — {capture.instrument} — {desc}")
            self.canvas.finish_plot(view)
        except Exception as exc:
            QMessageBox.warning(self, "Could not plot capture", str(exc))

    def export_selected(self):
        ids = self.selected_ids()
        if not ids:
            QMessageBox.warning(self, "Select captures", "Select at least one saved capture.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if not filename:
            return
        try:
            columns, headers = [], []
            for i in ids:
                ts, capture, desc = self.db.load_capture(i)
                label = f"#{i} | {ts} | {capture.instrument} | {capture.idn} | {capture.resource} | {desc}"
                for c, (x, y) in sorted(capture.channels.items()):
                    headers.extend([f"CH{c} Time (s) [{label}]", f"CH{c} Voltage (V) [{label}]"])
                    columns.extend([x, y])
            with open(filename, "w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(headers)
                for row in range(max((len(c) for c in columns), default=0)):
                    writer.writerow([c[row] if row < len(c) else "" for c in columns])
            self.connection_status.setText(f"Exported {len(ids)} capture(s) to {Path(filename).name}")
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def refresh_table(self):
        # Populating cells must not trigger database description updates.
        previous = self.table.blockSignals(True)
        try:
            rows = self.db.get_all_waveforms()
            self.table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for col_index, value in enumerate(row):
                    item = QTableWidgetItem("" if value is None else str(value))
                    if col_index != 3:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row_index, col_index, item)
            self.table.resizeColumnToContents(0)
            self.table.resizeColumnToContents(1)
        finally:
            self.table.blockSignals(previous)

    def load_from_db(self, row, column):
        try:
            i = int(self.table.item(row, 0).text())
            ts, capture, desc = self.db.load_capture(i)
            self.plot_capture(capture, f"#{i} — {capture.instrument} — {desc}")
            self.connection_status.setText(f"Viewing #{i} — {capture.idn or capture.instrument} — {capture.resource}")
        except Exception as exc:
            QMessageBox.warning(self, "Could not load capture", str(exc))

    def delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, "Delete captures", f"Permanently delete {len(ids)} selected capture(s)?") != QMessageBox.Yes:
            return
        for i in ids:
            self.db.delete_waveform(i)
        self.refresh_table()

    def update_description_from_table(self, row, column):
        if column == 3 and self.table.item(row, 0) is not None:
            self.db.update_waveform_description(int(self.table.item(row, 0).text()), self.table.item(row, column).text())

    def show_help(self):
        if self.help_dialog is None:
            self.help_dialog = HelpDialog(self)
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def closeEvent(self, event):
        self.timer.stop()
        if self.worker is not None:
            self._close_requested = True
            self.connection_status.setText("Finishing instrument operation before closing...")
            self.update_controls()
            event.ignore()
            return
        try:
            self.session.close()
        except Exception:
            pass
        self.db.close()
        event.accept()


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IliaKuznetcov.UniversalScope")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "UniversalScope.ico")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
