# PyInstaller spec for Airglide. Build with:  python scripts/build.py
# (the script downloads the hand model into build/models first)
import os
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH is set by PyInstaller
sys.path.insert(0, ROOT)
from packages import __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

datas = [
    (os.path.join(ROOT, "views"), "views"),
    (os.path.join(ROOT, "Assets"), "Assets"),
    (os.path.join(ROOT, "build", "models"), "models"),
]
binaries, hiddenimports = [], []
for pkg in ("mediapipe", "llama_cpp"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += ["pptx", "pypdf", "docx", "certifi"]
if IS_MAC:
    hiddenimports += ["AVFoundation", "AppKit", "PyObjCTools.AppHelper", "Quartz"]
if IS_WIN:
    hiddenimports += ["pystray._win32", "pynput.keyboard._win32", "pynput.mouse._win32", "winsound",
                      "win32com.client", "pythoncom"]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Airglide",
    console=False,
    icon=os.path.join(ROOT, "Assets", "icon.icns" if IS_MAC else "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Airglide")  # noqa: F821

if IS_MAC:
    app = BUNDLE(  # noqa: F821
        coll,
        name="Airglide.app",
        icon=os.path.join(ROOT, "Assets", "icon.icns"),
        bundle_identifier="com.airglide.app",
        info_plist={
            "CFBundleName": "Airglide",
            "CFBundleDisplayName": "Airglide",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSCameraUsageDescription":
                "Airglide uses the camera to track your hand gestures. Video never leaves your computer.",
            "NSAppleEventsUsageDescription":
                "Airglide sends key presses to your presentation app.",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
