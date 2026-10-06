# UniversalScope

One PySide6 desktop application for the **Keysight DSO-X 1102G** and
**Siglent SDS1202X HD** oscilloscopes. Connect to one instrument at a time,
capture CH1/CH2, save waveforms in SQLite, inspect or overlay saved captures,
and export numerical samples to CSV.

## Quick start on Windows

Download **UniversalScope.v1.0.0.exe** from the
[v1.0.0 release](https://github.com/IliaKuznetcov/UniversalScope/releases/tag/v1.0.0).
Place it in a writable folder and run it. This is a portable executable;
Python is not required.

Install **NI-VISA** separately before connecting a physical scope. The
executable does not include the VISA driver. Both scopes were tested over USB
on Windows on October 5, 2026.

The app creates `waveforms.db` beside the executable and saves captures there.
Keep the executable in a writable folder, and back up the database when needed.
The source app and an executable in a different folder use separate databases.

## Run from source

Clone this repository, then create a dedicated environment
(Python 3.13 recommended):

```powershell
git clone https://github.com/IliaKuznetcov/UniversalScope.git
cd UniversalScope
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

PyVISA uses the installed native VISA backend. Installing PyVISA alone does
not install NI-VISA. No extra Python package is needed for NI-VISA USB access.

## Using the application

1. Let both scopes finish booting and connect their USB cables.
2. Select **Keysight DSO-X 1102G** and click **Scan**. A single matching USB
   resource is suggested automatically. Choose the intended resource if more
   than one is available. Click **Connect**; confirm the instrument identity
   shown at the bottom.
3. Select CH1, CH2, or both, enter a description, and click **Manual Capture**.
   Check the plot against the scope display and check the sample count in the
   status bar. The capture is also saved automatically.
4. Click **Disconnect**, select **Siglent SDS1202X HD**, and **Scan / Connect**.
   Repeat the capture. Selected Siglent channels that are OFF on the instrument
   are skipped and reported; acquisition fails clearly if all selected channels
   are OFF. The app does not turn channels on for you.
5. Hold Ctrl to select saved captures from either scope, then use
   **Plot Selected** or **Export Selected**. Test **Start Auto / Stop Auto**
   after manual capture succeeds on each instrument.

Only the selected instrument is accessed. Both may stay plugged in. The
instrument model is checked against `*IDN?` before any capture commands are sent.
TCPIP resources can also be entered directly in the editable VISA resource box;
USB discovery and USB bench testing are the main intended path.

## Acquisition and data behavior

- Connections and waveform transfers run in a background thread. The GUI
  prevents overlapping instrument operations. Stop Auto remains available
  during a transfer; that in-flight capture finishes and saves.
- Automatic capture starts immediately. Timer ticks during a transfer are
  skipped. The interval is a requested schedule, not a guaranteed sampling
  period. Automatic captures are saved without replacing the displayed plot.
- CH1/CH2 reads are sequential. They are **not guaranteed to represent the
  same trigger event** while the instrument is running. Stop the scope on its
  front panel first when comparing a stable two-channel record.
- Each channel preserves its own time array, even when the axes or sample
  counts differ. Time is stored in seconds and voltage in volts, as float64.
- `waveforms.db` is created beside `main.py` (or beside the packaged executable).
  Instrument model, full identification response, and VISA resource are saved
  with each new capture. Large captures can produce a large database.
- The schema extends the previous Keysight database without deleting data.
  To review existing captures here, close the old app and **copy** its database
  into this folder before starting UniversalScope. Keep the original copy.
  Captures from older versions that did not save time axes cannot be plotted.
- CSV exports include separate time/voltage columns for every saved channel,
  with source metadata in the headers. Unequal lengths are padded with blank
  cells; samples are not resampled or interpolated.
- Export preserves all samples. Plotting and CSV writing still run in the GUI
  thread, so displaying/exporting millions of samples may briefly take time.
- Closing during a VISA operation waits for the worker to finish. For a capture
  you want to keep, wait for the **Saved #...** status before closing.
- Siglent disconnect sends `:SYSTem:REMote OFF` before closing VISA, releasing
  the instrument's remote panel lock. This also applies when switching scopes
  or closing the app. If the unlock fails, Disconnect reports the error while
  still closing the VISA session; exiting the app remains best effort.

## Plot controls

Mouse wheel zooms, middle-button drag pans, and **Time only** restricts those
actions to the time axis. Turn off toolbar Pan/Zoom to use these mouse controls.
**Keep view** preserves the current axes when switching captures. **Home** fits
the complete plotted data. The toolbar Save button exports a plot image.
Press **F1** for the guide and license viewer. Double-click a Description cell
to edit its saved label.

## Code layout

| File | Responsibility |
| --- | --- |
| `main.py` | GUI, background operations, capture workflow, CSV export |
| `instruments.py` | Shared instrument session, model checks, channel capture results |
| `keysight_controller.py` | Original Keysight SCPI and waveform conversion |
| `siglent_controller.py` | Latest Siglent SCPI, enabled-channel checks, waveform conversion |
| `database.py` | SQLite schema migration, metadata, per-channel time axes |
| `plot_widgets.py` | Existing Matplotlib navigation and help/license viewer |
| `tests/test_integration.py` | Hardware-free integration tests with simulated VISA responses |

The vendor acquisition code comes from the source repositories. The Siglent
controller additionally releases remote mode on disconnect. The integration
adds the common session and GUI around them, keeping vendor protocol details
separate for later review and debugging.

## Validation

### Automated integration tests

Run from this folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The package passed 16 tests using simulated VISA sessions and the real
controller decoding code: both scope protocols, wrong-model rejection,
connection cleanup on switching, disabled Siglent channels, independent time
axes, legacy database migration, GUI capture/save/edit/overlay/export,
auto-capture transfer errors, stopping auto during a transfer, and closing
while a worker is active, plus Siglent unlock ordering, cleanup after unlock
failure, and protection against sending its unlock command to a Keysight.
The GUI was also launched and visually inspected during initial integration.
Validation used PySide6 6.10.2, Matplotlib 3.10.8, PyVISA 1.16.2, and NumPy 2.3.5
in Linux; requirements retain NumPy 2.4.2 from the existing Windows app.

### Physical instrument testing

Physical testing was completed on **October 5, 2026**, with a
**Keysight DSO-X 1102G** and **Siglent SDS1202X HD** connected over USB on Windows.
The source application and the PyInstaller executable were tested with both
instruments. The user also confirmed that disconnect restores local operation
on the Siglent.

The saved square-wave comparison contains **12 captures**: three captures for
each instrument/channel combination, with the signal tested on CH1 and CH2 in
turn. Both channels were stored in each capture. Capture descriptions record
**1.00 V/div** and **5 ms/div**; the stored time axes cover approximately **50 ms**.

| Instrument | Signal channel | Captures | Samples per channel | Sample interval | Measured period | Plateau amplitude range |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Keysight DSO-X 1102G | CH1 | 3 | 62,500 | 0.8 us | approx. 10 ms | 3.377 V |
| Keysight DSO-X 1102G | CH2 | 3 | 62,500 | 0.8 us | approx. 10 ms | 3.337-3.377 V |
| Siglent SDS1202X HD | CH1 | 3 | 10,000 | 5.0 us | approx. 10 ms | 3.319-3.321 V |
| Siglent SDS1202X HD | CH2 | 3 | 10,000 | 5.0 us | approx. 10 ms | 3.325-3.327 V |

The analysis used the channel identified in each capture description.
Plateau amplitude is the difference between median high and low levels,
rather than the noise-sensitive absolute maximum minus minimum; the table
shows the range across the three captures. Period was estimated from the median
spacing between rising crossings of a mid-level threshold, with linear
interpolation between samples. Results are rounded to avoid implying calibrated
timing precision.

The database passed SQLite's quick integrity check. All 24 stored channel
records had matching time/voltage lengths, finite values, and strictly
increasing time axes. Both instruments reproduced approximately **100 Hz**.
Median plateau amplitudes differed by approximately **1.5-1.7%** between the
instruments. This comparison supports consistent acquisition, storage, and
gross voltage/time scaling; it does not establish absolute voltage accuracy
because the database contains no calibrated reference value.

The raw test database is retained separately and is not committed to the
source repository. The database does not record transfer durations or prove
error-recovery behavior; the automated tests cover the simulated failure cases
described above.

## Development and data files

UniversalScope is maintained as a separate repository. Its original Keysight
and Siglent source repositories remain separate. The database, virtual
environment, build directories, generated executables, and the local test CSV
are ignored by Git.

## Build the Windows executable

Build on Windows from the application's virtual environment. Close the app
before rebuilding. The following notice-collection commands assume that
`third_party_licenses_reference` does not already exist; retain an earlier
backup separately before repeating them:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.19.0
Rename-Item .\third_party_licenses third_party_licenses_reference
.\.venv\Scripts\python.exe collect_license_files.py
Copy-Item .\third_party_licenses_reference\Qt .\third_party_licenses\Qt -Recurse
.\.venv\Scripts\python.exe -m PyInstaller --clean UniversalScope.spec
```

The source package includes the original third-party notices for the UI and
runtime packages. Recollect notices from the actual Windows build environment
before distributing a newly built executable. The application code carries
the existing MIT license; third-party components retain their own licenses.

## Source versions

- `IliaKuznetcov/DSOx1102G`, main: `9766dd518db300805690755a80e6b1790ebc52c6`
- `IliaKuznetcov/Siglent-SDS1202X-HD`, main: `cc32c14ec42681f134191bd1df1140dad43de6d1`

Retrieved and integrated on October 5, 2026.
