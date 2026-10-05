# -*- mode: python ; coding: utf-8 -*-
# Build this on Windows after bench testing both instruments.
a = Analysis(
    ['main.py'],
    pathex=[], binaries=[],
    datas=[('LICENSE', '.'), ('third_party_licenses', 'third_party_licenses'), ('UniversalScope.ico', '.')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0,
)
unused_qt_files = {'qt6virtualkeyboard.dll', 'qtvirtualkeyboardplugin.dll'}


def keep_qt_file(entry):
    return entry[0].replace('\\', '/').rsplit('/', 1)[-1].lower() not in unused_qt_files


a.binaries = [entry for entry in a.binaries if keep_qt_file(entry)]
a.datas = [entry for entry in a.datas if keep_qt_file(entry)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='UniversalScope', icon='UniversalScope.ico', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
