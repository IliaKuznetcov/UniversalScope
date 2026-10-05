import pyvisa
import numpy as np


class ScopeController:
    def __init__(self):
        self.rm = pyvisa.ResourceManager()
        self.scope = None

    def list_resources(self):
        return self.rm.list_resources()

    def connect(self, resource, progress=None):
        """Connect and optionally report the current connection stage."""
        report = progress if progress is not None else lambda message: None

        # Close any previous instrument session before reconnecting.
        self.close()

        report("Opening instrument connection...")
        scope = self.rm.open_resource(resource, open_timeout=10000)

        try:
            # VISA communication timeout is in milliseconds.
            scope.timeout = 10000

            report("Waiting for oscilloscope response...")
            idn = scope.query("*IDN?").strip()

            if not idn:
                raise RuntimeError(
                    "The oscilloscope returned an empty response."
                )

        except Exception:
            # Discard the incomplete connection so another attempt can retry.
            try:
                scope.close()
            except Exception:
                pass
            raise

        # Store the session only after the identification query succeeds.
        self.scope = scope
        return idn

    def close(self):
        if self.scope:
            self.scope.close()
            self.scope = None

    def capture_waveform(self, channel="CHAN1"):
        if not self.scope:
            raise RuntimeError("Scope not connected")

        self.scope.write(f":WAV:SOURCE {channel}")
        self.scope.write(":WAV:FORMAT BYTE")
        self.scope.write(":WAV:POINTS:MODE RAW")

        y = self.scope.query_binary_values(
            ":WAV:DATA?",
            datatype='B',
            container=np.array
        )

        # Scaling parameters
        x_increment = float(self.scope.query(":WAV:XINC?"))
        x_origin = float(self.scope.query(":WAV:XOR?"))
        y_increment = float(self.scope.query(":WAV:YINC?"))
        y_origin = float(self.scope.query(":WAV:YOR?"))
        y_reference = float(self.scope.query(":WAV:YREF?"))

        y = (y - y_reference) * y_increment + y_origin
        x = x_origin + np.arange(len(y)) * x_increment

        return x, y
