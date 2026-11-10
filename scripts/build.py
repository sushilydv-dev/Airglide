"""Build a standalone Airglide app.

    python scripts/build.py          # app folder in dist/
    python scripts/build.py --dmg    # macOS: also make dist/Airglide-<version>.dmg
    python scripts/build.py --zip    # also zip the result (used by CI releases)
    python scripts/build.py --installer   # Windows: also make a setup .exe (needs Inno Setup)

Requires: pip install -r requirements-dev.txt
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


BUNDLE_ID = "com.airglide.app"
ENTITLEMENTS = os.path.join(ROOT, "packaging", "entitlements.plist")


def codesign_app(app):
    """Re-sign the .app so macOS privacy permissions survive rebuilds.

    PyInstaller signs ad hoc, which pins Accessibility / Camera permission to
    the exact binary hash: after any rebuild or update, System Settings still
    shows Airglide as allowed but macOS ignores it and silently drops every
    key press and mouse event a gesture sends. Signing with a designated
    requirement based on the bundle id keeps the permission valid across builds.

    Set AIRGLIDE_CODESIGN_IDENTITY to a certificate name (for example
    "Developer ID Application: Your Name (TEAMID)") to sign for distribution.
    """
    identity = os.environ.get("AIRGLIDE_CODESIGN_IDENTITY", "").strip()
    cmd = ["codesign", "--force", "--identifier", BUNDLE_ID]
    if identity:
        # Hardened runtime (needed for notarization) plus what Python and the
        # camera need under it. --deep signs every bundled library with the same identity.
        cmd += ["--deep", "--sign", identity, "--options", "runtime", "--timestamp",
                "--entitlements", ENTITLEMENTS]
    else:
        cmd += ["--sign", "-", f"--requirements==designated => identifier \"{BUNDLE_ID}\""]
    subprocess.check_call(cmd + [app])
    subprocess.check_call(["codesign", "--verify", "--strict", app])
    print(f"Signed {app} ({identity or 'ad hoc, stable designated requirement'})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dmg", action="store_true", help="macOS: build a .dmg disk image")
    parser.add_argument("--zip", action="store_true", help="zip the built app")
    parser.add_argument("--installer", action="store_true", help="Windows: build a setup .exe with Inno Setup")
    args = parser.parse_args()

    from packages import __version__
    from packages.hands import ensure_model

    # 1. Bundle the hand-tracking model so the installed app works offline.
    models = os.path.join(ROOT, "build", "models")
    os.makedirs(models, exist_ok=True)
    shutil.copy(ensure_model(), os.path.join(models, "hand_landmarker.task"))

    # 2. PyInstaller.
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build", "pyinstaller"),
        os.path.join(ROOT, "packaging", "airglide.spec"),
    ])

    dist = os.path.join(ROOT, "dist")
    target = os.path.join(dist, "Airglide.app" if sys.platform == "darwin" else "Airglide")
    if sys.platform == "darwin":
        codesign_app(target)
    print(f"\nBuilt {target}")

    plat = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    if args.dmg and sys.platform == "darwin":
        dmg = os.path.join(dist, f"Airglide-{__version__}-macos.dmg")
        if os.path.exists(dmg):
            os.remove(dmg)
        staging = os.path.join(ROOT, "build", "dmg")
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging)
        subprocess.check_call(["cp", "-R", target, staging])
        os.symlink("/Applications", os.path.join(staging, "Applications"))
        subprocess.check_call(["hdiutil", "create", "-volname", "Airglide", "-srcfolder", staging,
                               "-ov", "-format", "UDZO", dmg])
        print(f"Built {dmg}")
    if args.installer and sys.platform == "win32":
        iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if not os.path.exists(iscc):
            sys.exit("Inno Setup not found. Install it from https://jrsoftware.org/isdl.php")
        subprocess.check_call([iscc, f"/DAppVersion={__version__}", f"/DSourceDir={target}",
                               os.path.join(ROOT, "packaging", "airglide.iss")])
        print(f"Built {os.path.join(dist, f'Airglide-{__version__}-windows-setup.exe')}")
    if args.zip:
        archive = shutil.make_archive(os.path.join(dist, f"Airglide-{__version__}-{plat}"), "zip",
                                      dist, os.path.basename(target))
        print(f"Built {archive}")
    stable_names(dist, __version__)


def stable_names(dist, version):
    """Copy each installer to a name without the version (Airglide-macos.dmg, ...), so
    github.com/<repo>/releases/latest/download/<name> always serves the newest build.
    The website's download buttons link to these."""
    tag = f"-{version}-"
    for name in os.listdir(dist):
        if name.startswith("Airglide" + tag) and name.endswith((".dmg", ".exe", ".zip")):
            stable = name.replace(tag, "-", 1)
            shutil.copyfile(os.path.join(dist, name), os.path.join(dist, stable))
            print(f"Copied {name} -> {stable}")


if __name__ == "__main__":
    main()
