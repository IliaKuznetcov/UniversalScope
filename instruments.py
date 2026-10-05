"""Shared operations used by the GUI; vendor SCPI stays in each controller."""
from dataclasses import dataclass
import re

import numpy as np
import pyvisa

from keysight_controller import ScopeController as KeysightController
from siglent_controller import SiglentController


MODELS = ("Keysight DSO-X 1102G", "Siglent SDS1202X HD")
USB_VENDOR_IDS = {MODELS[0]: ("0X0957", "0X2A8D"), MODELS[1]: ("0XF4EC",)}


def matching_resources(model, resources):
    """Hints for USB selection only; *IDN? verifies the actual model."""
    return tuple(r for r in resources if any(
        vendor in r.upper() for vendor in USB_VENDOR_IDS[model]
    ))


def validate_identity(model, idn):
    fields = idn.split(",")
    actual = re.sub(r"[^A-Z0-9]", "", fields[1].upper()) if len(fields) > 1 else ""
    expected = "DSOX1102G" if model == MODELS[0] else "SDS1202XHD"
    if actual != expected:
        raise RuntimeError(
            f"Selected {model}, but this resource identifies as:\n{idn}\n"
            "Choose the matching model and VISA resource."
        )


@dataclass
class Capture:
    # Each channel retains its own time axis, even if lengths differ.
    channels: dict
    instrument: str
    idn: str
    resource: str
    skipped: tuple = ()


class InstrumentSession:
    """One active instrument; GUI workers serialize every VISA operation."""
    def __init__(self):
        self.controller = None
        self.model = ""
        self.idn = ""
        self.resource = ""

    @property
    def connected(self):
        return self.controller is not None and self.controller.scope is not None

    def discover(self):
        manager = pyvisa.ResourceManager()
        try:
            return tuple(manager.list_resources())
        finally:
            manager.close()

    def connect(self, model, resource, progress=None):
        if model not in MODELS:
            raise ValueError(f"Unsupported model: {model}")
        if not resource.strip():
            raise ValueError("Choose or enter a VISA resource first.")
        self.close()
        factory = KeysightController if model == MODELS[0] else SiglentController
        controller = factory()
        try:
            idn = controller.connect(resource.strip(), progress=progress)
            validate_identity(model, idn)
        except Exception:
            try:
                controller.close()
            finally:
                controller.rm.close()
            raise
        self.controller = controller
        self.model, self.idn, self.resource = model, idn, resource.strip()
        return idn

    def capture(self, channels, progress=None):
        if not self.connected:
            raise RuntimeError("Connect an oscilloscope first.")
        channels = tuple(channels)
        if not channels or any(c not in (1, 2) for c in channels):
            raise ValueError("Select CH1, CH2, or both.")
        report = progress if progress is not None else lambda message: None
        enabled = channels
        if self.model == MODELS[1]:
            report("Checking selected channel states...")
            enabled = self.controller.enabled_channels(channels)
        skipped = tuple(c for c in channels if c not in enabled)
        if not enabled:
            raise RuntimeError("All selected channels are OFF on the oscilloscope. Enable a channel and retry.")
        waveforms = {}
        for channel in enabled:
            report(f"Transferring CH{channel} waveform...")
            if self.model == MODELS[1]:
                x, y = self.controller.capture_waveform(channel, check_enabled=False)
            else:
                x, y = self.controller.capture_waveform(f"CHAN{channel}")
            x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
            if x.ndim != 1 or y.ndim != 1 or x.size == 0 or x.size != y.size:
                raise RuntimeError(f"CH{channel}: invalid waveform dimensions or sample count.")
            if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
                raise RuntimeError(f"CH{channel}: waveform contains nonfinite samples.")
            if x.size > 1 and np.any(np.diff(x) <= 0):
                raise RuntimeError(f"CH{channel}: sample times must increase.")
            waveforms[channel] = (x, y)
        return Capture(waveforms, self.model, self.idn, self.resource, skipped)

    def close(self):
        controller, self.controller = self.controller, None
        self.model = self.idn = self.resource = ""
        if controller is not None:
            try:
                controller.close()
            finally:
                controller.rm.close()
