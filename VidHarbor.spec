# PyInstaller spec - build with:  pyinstaller --noconfirm VidHarbor.spec
# Produces dist/VidHarbor/VidHarbor.exe (one-folder build: starts fast, and
# the yt-dlp engine can be updated in place from inside the app).
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = [('assets/icon.png', 'assets')]
binaries = []
hiddenimports = collect_submodules('yt_dlp') + collect_submodules('yt_dlp_ejs')

# yt-dlp-ejs ships the JavaScript that solves YouTube's challenges
for pkg in ('yt_dlp_ejs', 'curl_cffi', 'certifi'):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:  # optional packages
        print(f'skipping {pkg}: {e}')

datas += copy_metadata('yt-dlp')  # lets the app compare bundled vs updated engine

a = Analysis(
    ['VidHarbor.pyw'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['tkinter', 'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
              'PySide6.QtQuick3D', 'PySide6.QtBluetooth', 'PySide6.QtSensors'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='VidHarbor',
    console=False,
    icon='assets/icon.ico' if sys.platform == 'win32' else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='VidHarbor', upx=False)
