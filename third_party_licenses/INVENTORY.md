# Installed dependency license inventory

Collected from the build environment. This inventory includes installed packages
that may not be bundled in the executable, including development tools.
It is a collection for review, not a determination of licensing compliance.

Python: 3.13.9

| Package | Version | Notice files copied |
|---|---|---|
| altgraph | 0.17.5 | 1 |
| contourpy | 1.3.3 | 1 |
| cycler | 0.12.1 | 1 |
| fonttools | 4.61.1 | 2 |
| kiwisolver | 1.4.9 | 1 |
| matplotlib | 3.10.8 | 3 |
| numpy | 2.4.2 | 20 |
| packaging | 26.0 | 3 |
| pefile | 2024.8.26 | 1 |
| pillow | 12.1.1 | 1 |
| pip | 26.0.1 | 44 |
| pyinstaller | 6.19.0 | 1 |
| pyinstaller-hooks-contrib | 2026.2 | 1 |
| pyparsing | 3.3.2 | 1 |
| PySide6 | 6.10.2 | 1 |
| PySide6_Addons | 6.10.2 | 1 |
| PySide6_Essentials | 6.10.2 | 1 |
| python-dateutil | 2.9.0.post0 | 1 |
| PyVISA | 1.16.2 | 2 |
| PyVISA-py | 0.8.1 | 2 |
| pywin32-ctypes | 0.2.3 | 1 |
| setuptools | 82.0.0 | 17 |
| shiboken6 | 6.10.2 | 1 |
| six | 1.17.0 | 1 |
| typing_extensions | 4.15.0 | 1 |

## Outstanding review

- Compare this inventory against files actually bundled by PyInstaller.
- Check notices for bundled native libraries, fonts, and Python runtime components.
- Provide required corresponding library source or a valid source-access mechanism.
- Confirm users can replace or relink LGPL libraries and run the resulting application.
- Make notices accessible in the application and in the release download.

See LICENSE_INVENTORY.json for metadata, project URLs, and review notes.

