"""Plot navigation and help reused from the original Keysight application."""
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.backend_bases import MouseButton
from matplotlib.figure import Figure


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self):
        self.fig = Figure()
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)

        self.keep_view = True
        self.time_only = True
        self._pan_state = None

        self.mpl_connect("scroll_event", self._on_scroll)
        self.mpl_connect("button_press_event", self._on_press)
        self.mpl_connect("motion_notify_event", self._on_motion)
        self.mpl_connect("button_release_event", self._on_release)
        self.mpl_connect("figure_leave_event", self._on_release)

    def set_keep_view(self, checked):
        self.keep_view = checked

    def set_time_only(self, checked):
        self.time_only = checked

    def begin_plot(self):
        """Remember the current view before replacing the plotted data."""
        self._on_release(None)
        view = None
        if self.keep_view and self.ax.has_data():
            view = (self.ax.get_xlim(), self.ax.get_ylim())
        self.ax.clear()
        return view

    def finish_plot(self, view):
        """Set the full-data Home view, then restore any preserved view."""
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Voltage (V)")
        if self.ax.lines:
            self.ax.legend()

        self.ax.relim()
        self.ax.autoscale_view()

        if self.toolbar is not None:
            self.toolbar.update()
            self.toolbar.push_current()

        if view is not None:
            self.ax.set_xlim(view[0])
            self.ax.set_ylim(view[1])
            if self.toolbar is not None:
                self.toolbar.push_current()

        self.draw_idle()

    def _toolbar_active(self):
        return self.toolbar is not None and bool(self.toolbar.mode)

    def _on_scroll(self, event):
        if (
            event.inaxes is not self.ax
            or not self.ax.has_data()
            or self._toolbar_active()
            or self._pan_state is not None
            or event.xdata is None
            or event.ydata is None
        ):
            return

        factor = 1.2 ** (-event.step)
        x0, x1 = self.ax.get_xlim()
        self.ax.set_xlim(
            event.xdata + (x0 - event.xdata) * factor,
            event.xdata + (x1 - event.xdata) * factor,
        )

        if not self.time_only:
            y0, y1 = self.ax.get_ylim()
            self.ax.set_ylim(
                event.ydata + (y0 - event.ydata) * factor,
                event.ydata + (y1 - event.ydata) * factor,
            )

        if self.toolbar is not None:
            self.toolbar.push_current()
        self.draw_idle()

    def _on_press(self, event):
        if (
            event.button != MouseButton.MIDDLE
            or event.inaxes is not self.ax
            or not self.ax.has_data()
            or self._toolbar_active()
        ):
            return

        self._pan_state = (
            event.x,
            event.y,
            self.ax.get_xlim(),
            self.ax.get_ylim(),
            self.ax.transData.frozen().inverted(),
            self.time_only,
        )

    def _on_motion(self, event):
        if self._pan_state is None or event.x is None or event.y is None:
            return

        px, py, xlim, ylim, inverse, time_only = self._pan_state
        start = inverse.transform((px, py))
        current = inverse.transform((event.x, event.y))
        dx, dy = current - start

        self.ax.set_xlim(xlim[0] - dx, xlim[1] - dx)
        if not time_only:
            self.ax.set_ylim(ylim[0] - dy, ylim[1] - dy)
        self.draw_idle()

    def _on_release(self, event):
        if self._pan_state is not None:
            self._pan_state = None
            if self.toolbar is not None:
                self.toolbar.push_current()

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("UniversalScope — Help")
        self.resize(650, 650)

        browser = QTextBrowser()
        browser.setHtml("""
            <h2>UniversalScope Controller — User Guide</h2>

            <h3>Connect and capture</h3>
            <ul>
                <li><b>Connect / Reconnect:</b> Select the scope model and VISA resource, then connect. Use Scan to refresh USB resources, or enter a resource directly. Disconnect before switching models.
                    Allow the instrument to finish starting.
                    Connection progress appears at the bottom of the app.</li>
                <li><b>CH1 / CH2:</b> Choose which channels to acquire
                    and display.</li>
                <li><b>Description:</b> Enter a label for new captures,
                    such as the sample name and probe orientation.</li>
                <li><b>Manual Capture:</b> Acquire the selected channels,
                    display the waveform, and save it to the database.</li>
                <li><b>Start Auto / Stop Auto:</b> Start or stop repeated
                    captures. These are saved to the database;
                    the plot does not update automatically.</li>
                <li><b>Interval (s):</b> Set the requested time between
                    automatic captures, in seconds.</li>
            </ul>

            <p>The app connects to one scope at a time. Siglent channels that are OFF are skipped; enable at least one selected channel on the scope. Channel reads are sequential and are not guaranteed to share a trigger event. For a stable two-channel comparison, stop the scope before capture. Every channel retains its own time axis.</p><h3>Inspect a waveform</h3>
            <ul>
                <li><b>Mouse wheel:</b> Scroll up to zoom in around the
                    cursor; scroll down to zoom out.</li>
                <li><b>Middle-button drag:</b> Hold the mouse wheel button
                    and drag to pan through the waveform.</li>
                <li><b>Time only:</b> Restrict wheel zoom and middle-button
                    panning to the time axis. Uncheck it to navigate
                    both time and voltage.</li>
                <li><b>Toolbar Zoom:</b> Select the magnifying glass,
                    then drag a rectangle around the region of interest.</li>
                <li><b>Toolbar Pan:</b> Select the hand, then drag
                    to move the view.</li>
                <li><b>Home:</b> Restore the full view of the currently
                    plotted waveform or group of waveforms.</li>
                <li><b>Back / Forward:</b> Move through the viewing
                    history for the current plot.</li>
            </ul>
            <p><b>Mouse controls:</b> Turn off the toolbar's Zoom and Pan
                modes to use wheel zoom and middle-button panning.
                The Time only checkbox applies to these mouse controls.</p>

            <h3>Keep view</h3>
            <p>When checked, loading or plotting another capture preserves
                the current time window and voltage scale.</p>
            <p>For example, zoom into a suspected S-wave arrival, then
                switch between captures recorded at different probe angles.
                Keeping both scales fixed helps you compare arrival times
                and amplitudes.</p>
            <p>When unchecked, the next capture is fitted to the plot.
                Changing the checkbox alone does not change the current view.
                Home restores the full view at any time.</p>

            <h3>Saved captures</h3>
            <ul>
                <li><b>View:</b> Click a table row to display that capture.</li>
                <li><b>Select several:</b> Hold Ctrl and click rows.
                    Use Shift-click to select a range.</li>
                <li><b>Plot Selected:</b> Overlay the selected captures
                    on the same plot.</li>
                <li><b>Edit a description:</b> Double-click its Description
                    cell, edit the text, and press Enter.</li>
                <li><b>Export Selected:</b> Save the selected captures'
                    time and voltage samples to CSV.</li>
                <li><b>Delete Selected:</b> Permanently remove the selected
                    captures from the database.</li>
                <li><b>Toolbar Save:</b> Save an image of the current plot.
                    Use Export Selected to save numerical samples.</li>
            </ul>

            <p>Time is measured in seconds and voltage in volts.
                Zoom changes the displayed view; it does not change
                the stored samples.</p>
        """)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        buttons.rejected.connect(self.reject)

        tabs = QTabWidget()
        tabs.addTab(browser, "User Guide")
        tabs.addTab(self._create_licenses_tab(), "Licenses")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)


    def _create_licenses_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        notice = QLabel(
            "Original UniversalScope application code is licensed under MIT. "
            "This application uses Qt and PySide6 under LGPLv3. "
            "Other components retain their own licenses. "
            "The collection also includes build-tool notices."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        layout.addWidget(QLabel("Choose a license or notice:"))
        picker = QComboBox()
        picker.setMinimumContentsLength(30)
        picker.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        layout.addWidget(picker)

        viewer = QTextBrowser()
        viewer.setReadOnly(True)
        viewer.setAccessibleName("License text")
        layout.addWidget(viewer, 1)

        # Works from source and inside the PyInstaller executable.
        base_dir = Path(__file__).resolve().parent
        licenses_dir = base_dir / "third_party_licenses"

        documents = [
            ("Application — MIT", base_dir / "LICENSE"),
            (
                "Qt — LGPLv3",
                licenses_dir / "Qt" / "LGPL-3.0-only.txt",
            ),
            (
                "Qt — GPLv3 (incorporated by LGPLv3)",
                licenses_dir / "Qt" / "GPL-3.0-only.txt",
            ),
        ]
        included = {path for _, path in documents}

        if licenses_dir.is_dir():
            for path in sorted(licenses_dir.rglob("*")):
                if (
                    not path.is_file()
                    or path in included
                    or path.suffix.lower() == ".json"
                ):
                    continue

                label = path.relative_to(licenses_dir).as_posix()
                documents.append((label, path))

        for label, path in documents:
            picker.addItem(label, str(path))

        def show_license(index):
            filename = picker.itemData(index)
            if filename is None:
                viewer.setPlainText("No license file selected.")
                return

            try:
                text = Path(filename).read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                viewer.setPlainText(
                    "This license file is missing or could not be read. "
                    "Please obtain a complete copy of the application."
                )
                return

            viewer.setPlainText(text)
            viewer.verticalScrollBar().setValue(0)

        picker.currentIndexChanged.connect(show_license)
        show_license(picker.currentIndex())
        return page

