import re
import struct

import numpy as np
import pyvisa
from pyvisa.errors import VisaIOError


class SiglentController:
    """
    VISA controller for SIGLENT SDS1000X HD-series oscilloscopes.

    The controller provides:
        - VISA resource discovery
        - instrument connection/disconnection
        - channel-state queries
        - waveform acquisition
        - conversion of raw ADC data to volts
        - construction of the waveform time axis
    """

    def __init__(self):
        self.rm = pyvisa.ResourceManager()
        self.scope = None
        self.idn = None

    def list_resources(self):
        """Return VISA resources visible to PyVISA."""
        return self.rm.list_resources()

    def connect(self, resource, progress=None):
        """
        Connect to an oscilloscope.

        Parameters
        ----------
        resource : str
            VISA resource string.
        progress : callable, optional
            Callback accepting a status message.

        Returns
        -------
        str
            Instrument identification response.
        """
        report = progress if progress is not None else lambda message: None

        # Close an existing session before reconnecting.
        self.close()

        report("Opening instrument connection...")

        scope = self.rm.open_resource(
            resource,
            open_timeout=10000,
        )

        try:
            # Communication timeout in milliseconds.
            scope.timeout = 15000

            # Allow large waveform transfers.
            scope.chunk_size = 50 * 1024 * 1024

            report("Waiting for oscilloscope response...")
            idn = scope.query("*IDN?").strip()

            if not idn:
                raise RuntimeError(
                    "The oscilloscope returned an empty identification response."
                )

        except Exception:
            try:
                scope.close()
            except Exception:
                pass
            raise

        self.scope = scope
        self.idn = idn
        return idn

    def close(self):
        """Release the Siglent front panel, then close the VISA connection."""
        if self.scope is not None:
            try:
                # Only send vendor commands to the model this application supports.
                fields = (self.idn or "").split(",")
                model = re.sub(r"[^A-Z0-9]", "", fields[1].upper()) if len(fields) > 1 else ""
                if model == "SDS1202XHD":
                    self.scope.write(":SYSTem:REMote OFF")
            finally:
                # A failed unlock must still release all local session state.
                try:
                    self.scope.close()
                finally:
                    self.scope = None
                    self.idn = None

    def _require_connection(self):
        """Raise a clear error when no oscilloscope is connected."""
        if self.scope is None:
            raise RuntimeError("Oscilloscope is not connected.")

    @staticmethod
    def _extract_ieee_block(raw):
        """
        Remove an IEEE 488.2 binary-block header.

        Example
        -------
        #9XXXXXXXXX<data>

        Returns
        -------
        bytes
            Binary payload only.
        """
        if not raw.startswith(b"#"):
            return raw

        if len(raw) < 2:
            raise RuntimeError("Invalid IEEE binary block.")

        try:
            n_digits = int(chr(raw[1]))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Invalid IEEE binary block header.") from exc

        length_start = 2
        length_end = length_start + n_digits

        if len(raw) < length_end:
            raise RuntimeError("Incomplete IEEE binary block header.")

        try:
            payload_length = int(raw[length_start:length_end])
        except ValueError as exc:
            raise RuntimeError("Invalid IEEE binary block payload length.") from exc

        payload_start = length_end
        payload_end = payload_start + payload_length

        if payload_end > len(raw):
            raise RuntimeError("Incomplete IEEE binary block payload.")

        return raw[payload_start:payload_end]

    def _query_binary(self, command):
        """Send a SCPI query and return its binary payload."""
        self._require_connection()

        self.scope.write(command)
        raw = self.scope.read_raw()

        return self._extract_ieee_block(raw)

    def _query_text(self, command, timeout_ms=None):
        """
        Send a text SCPI query, optionally with a temporary short timeout.

        The original VISA timeout is always restored before returning.
        """
        self._require_connection()

        if timeout_ms is None:
            return self.scope.query(command).strip()

        original_timeout = self.scope.timeout

        try:
            self.scope.timeout = int(timeout_ms)
            return self.scope.query(command).strip()
        finally:
            self.scope.timeout = original_timeout

    @staticmethod
    def _parse_numeric_response(response):
        """
        Extract the final floating-point value from a SIGLENT response.

        Examples
        --------
        C1:VDIV 1.00E-01V
        C1:OFST -3.33E-03V
        5.00E-06S
        """
        numbers = re.findall(
            r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[Ee][-+]?\d+)?",
            response,
        )

        if not numbers:
            raise ValueError(
                f"Could not extract numerical value from: {response}"
            )

        return float(numbers[-1])

    @staticmethod
    def _normalize_channel(channel):
        """
        Normalize common channel identifiers.

        Accepted examples
        -----------------
        1, "1", "C1", "CH1", "CHAN1", "CHANNEL1"
        and equivalent forms for channel 2.
        """
        text = str(channel).strip().upper()

        aliases = {
            "1": 1,
            "C1": 1,
            "CH1": 1,
            "CHAN1": 1,
            "CHANNEL1": 1,
            "2": 2,
            "C2": 2,
            "CH2": 2,
            "CHAN2": 2,
            "CHANNEL2": 2,
        }

        if text not in aliases:
            raise ValueError(f"Unsupported channel: {channel}")

        return aliases[text]

    def is_channel_enabled(self, channel, timeout_ms=2000):
        """
        Return True if an analog channel is enabled on the oscilloscope.

        SIGLENT documents ``C<n>:TRA?`` / ``C<n>:TRACE?`` as the query
        for the channel display state. A short temporary timeout is used
        so a failed state query cannot stall the application for the full
        waveform-transfer timeout.

        Parameters
        ----------
        channel : int or str
            Channel identifier.
        timeout_ms : int, optional
            Maximum time allowed for the channel-state query.

        Returns
        -------
        bool
            True for ON, False for OFF.
        """
        channel_number = self._normalize_channel(channel)

        try:
            response = self._query_text(
                f"C{channel_number}:TRA?",
                timeout_ms=timeout_ms,
            ).upper()
        except VisaIOError as exc:
            raise RuntimeError(
                f"Timed out while querying whether CH{channel_number} is enabled."
            ) from exc

        # Expected forms include:
        #   C1:TRACE ON
        #   C1:TRA ON
        #   ON
        # and the equivalent OFF responses.
        tokens = response.replace(":", " ").split()

        if "ON" in tokens:
            return True

        if "OFF" in tokens:
            return False

        raise RuntimeError(
            f"Unexpected channel-state response for CH{channel_number}: "
            f"{response!r}"
        )

    def enabled_channels(self, channels=(1, 2), timeout_ms=2000):
        """
        Return a tuple containing only the enabled channels.

        Example
        -------
        (2,) means CH1 is OFF and CH2 is ON.
        """
        enabled = []

        for channel in channels:
            channel_number = self._normalize_channel(channel)
            if self.is_channel_enabled(channel_number, timeout_ms=timeout_ms):
                enabled.append(channel_number)

        return tuple(enabled)

    def capture_waveform(self, channel="CHAN1", check_enabled=True):
        """
        Acquire one waveform from the oscilloscope.

        Parameters
        ----------
        channel : str or int
            Channel identifier.
        check_enabled : bool, optional
            When True (default), refuse acquisition from a disabled channel.
            Set False only when the caller has already checked the channel.

        Returns
        -------
        time_axis : numpy.ndarray
            Sample times in seconds.
        voltage : numpy.ndarray
            Sample voltages in volts.
        """
        self._require_connection()

        channel_number = self._normalize_channel(channel)

        if check_enabled and not self.is_channel_enabled(channel_number):
            raise RuntimeError(
                f"CH{channel_number} is disabled; "
                "waveform acquisition was not attempted."
            )

        # -----------------------------------------------------
        # Select waveform source and acquisition mode
        # -----------------------------------------------------
        self.scope.write(f"WAV:SOUR C{channel_number}")
        self.scope.write("WAV:MODE NORM")

        # -----------------------------------------------------
        # Read channel/display settings
        # -----------------------------------------------------
        vdiv = self._parse_numeric_response(
            self.scope.query(f"C{channel_number}:VDIV?").strip()
        )

        offset = self._parse_numeric_response(
            self.scope.query(f"C{channel_number}:OFST?").strip()
        )

        timebase = self._parse_numeric_response(
            self.scope.query("TDIV?").strip()
        )

        # -----------------------------------------------------
        # Read SIGLENT waveform descriptor
        # -----------------------------------------------------
        preamble = self._query_binary("WAV:PRE?")

        if len(preamble) < 188:
            raise RuntimeError(
                "Waveform preamble is unexpectedly short: "
                f"{len(preamble)} bytes."
            )

        # Descriptor fields established during SDS1202X HD testing:
        # 0xA4 = code per vertical division
        # 0xAC = waveform bit width
        # 0xB0 = sample interval
        # 0xB4 = horizontal delay
        code_per_div = struct.unpack_from("<f", preamble, 0xA4)[0]
        waveform_bits = struct.unpack_from("<H", preamble, 0xAC)[0]
        interval = struct.unpack_from("<f", preamble, 0xB0)[0]
        delay = struct.unpack_from("<d", preamble, 0xB4)[0]

        if code_per_div == 0:
            raise RuntimeError(
                "code_per_div returned zero; cannot calculate voltage."
            )

        if interval <= 0:
            raise RuntimeError(
                f"Invalid waveform sample interval: {interval}"
            )

        # -----------------------------------------------------
        # Select waveform transfer width
        # -----------------------------------------------------
        if waveform_bits > 8:
            # SDS1202X HD:
            # 12-bit acquisition -> 16-bit WORD transfer.
            self.scope.write("WAV:WIDT WORD")
            dtype = "<i2"
            bytes_per_sample = 2
        else:
            self.scope.write("WAV:WIDT BYTE")
            dtype = np.int8
            bytes_per_sample = 1

        # -----------------------------------------------------
        # Retrieve waveform data
        # -----------------------------------------------------
        waveform_bytes = self._query_binary("WAV:DATA?")

        if not waveform_bytes:
            raise RuntimeError("No waveform data received.")

        if len(waveform_bytes) % bytes_per_sample != 0:
            raise RuntimeError(
                "Waveform payload size is incompatible with "
                f"{bytes_per_sample}-byte samples. "
                f"Received {len(waveform_bytes)} bytes."
            )

        # -----------------------------------------------------
        # Binary waveform -> ADC samples
        # -----------------------------------------------------
        adc = np.frombuffer(
            waveform_bytes,
            dtype=dtype,
        ).astype(np.float64)

        # -----------------------------------------------------
        # ADC samples -> volts
        # -----------------------------------------------------
        voltage = adc / code_per_div * vdiv - offset

        # -----------------------------------------------------
        # Construct time axis
        #
        # SDS1000X HD display width = 10 divisions.
        # -----------------------------------------------------
        grid_divisions = 10

        start_time = delay - timebase * grid_divisions / 2

        time_axis = start_time + np.arange(len(adc)) * interval

        return time_axis, voltage
