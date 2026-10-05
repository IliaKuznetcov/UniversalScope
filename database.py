"""SQLite capture storage, including source instrument and independent axes."""
import sqlite3
from datetime import datetime

import numpy as np

from instruments import Capture


class DatabaseManager:
    def __init__(self, db_file="waveforms.db"):
        self.conn = sqlite3.connect(db_file)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS waveforms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, x BLOB, ch1 BLOB, ch2 BLOB, description TEXT,
                x2 BLOB, instrument TEXT, idn TEXT, resource TEXT
            )
        """)
        # Additive migration: existing Keysight captures remain readable.
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(waveforms)")}
        for name, kind in (("x", "BLOB"), ("x2", "BLOB"), ("instrument", "TEXT"),
                           ("idn", "TEXT"), ("resource", "TEXT")):
            if name not in columns:
                self.conn.execute(f"ALTER TABLE waveforms ADD COLUMN {name} {kind}")
        self.conn.commit()

    def insert_capture(self, capture, description=""):
        blobs = {}
        if not capture.channels:
            raise ValueError("At least one channel is required.")
        for channel, (x, y) in capture.channels.items():
            x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
            if channel not in (1, 2) or x.ndim != 1 or y.ndim != 1 or not x.size or x.size != y.size:
                raise ValueError("Each channel needs equally sized, nonempty time and voltage arrays.")
            blobs[channel] = (x.tobytes(), y.tobytes())
        x1, y1 = blobs.get(1, (None, None))
        x2, y2 = blobs.get(2, (None, None))
        # Preserve the original x field for CH2-only captures too.
        with self.conn:
            cursor = self.conn.execute("""
                INSERT INTO waveforms
                (timestamp, x, ch1, ch2, description, x2, instrument, idn, resource)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  x1 if x1 is not None else x2, y1, y2, description,
                  x2, capture.instrument, capture.idn, capture.resource))
        return cursor.lastrowid

    def insert_waveform(self, x, y1=None, y2=None, description=""):
        channels = {c: (x, y) for c, y in ((1, y1), (2, y2)) if y is not None}
        return self.insert_capture(Capture(channels, "", "", ""), description)

    def load_capture(self, waveform_id):
        row = self.conn.execute("""
            SELECT timestamp, x, ch1, ch2, description, x2, instrument, idn, resource
            FROM waveforms WHERE id=?
        """, (waveform_id,)).fetchone()
        if row is None:
            raise ValueError(f"Capture {waveform_id} was not found.")
        ts, blob_x, y1, y2, desc, blob_x2, instrument, idn, resource = row
        channels = {}
        for channel, xb, yb in ((1, blob_x, y1), (2, blob_x2 if blob_x2 is not None else blob_x, y2)):
            if yb is None:
                continue
            if xb is None:
                raise ValueError("This old capture has no saved time axis. Use a new capture.")
            x, y = np.frombuffer(xb, dtype=np.float64).copy(), np.frombuffer(yb, dtype=np.float64).copy()
            if x.size != y.size:
                raise ValueError("Stored time and voltage lengths do not match.")
            channels[channel] = (x, y)
        return ts, Capture(channels, instrument or "Legacy capture", idn or "", resource or ""), desc or ""

    def load_waveform(self, waveform_id):
        ts, capture, desc = self.load_capture(waveform_id)
        return ts, capture.channels.get(1), capture.channels.get(2), desc

    def get_all_waveforms(self):
        return self.conn.execute("""
            SELECT id, timestamp, COALESCE(instrument, 'Legacy capture'), description
            FROM waveforms ORDER BY id DESC
        """).fetchall()

    def delete_waveform(self, waveform_id):
        with self.conn:
            self.conn.execute("DELETE FROM waveforms WHERE id=?", (waveform_id,))

    def update_waveform_description(self, waveform_id, new_desc):
        with self.conn:
            self.conn.execute("UPDATE waveforms SET description=? WHERE id=?", (new_desc, waveform_id))

    def close(self):
        self.conn.close()
