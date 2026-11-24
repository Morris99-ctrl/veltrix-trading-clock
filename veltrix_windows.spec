# PyInstaller one-folder build for Windows 10/11 Core Edition.
# Run from the project directory: python -m PyInstaller --clean --noconfirm veltrix_windows.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()
ICON = ROOT / "assets" / "veltrix.ico"

app_datas = [
    (str(ROOT / "config.json"), "."),
    (str(ICON), "assets"),
]
app_datas += collect_data_files("tzdata")

hidden_imports = []
try:
    hidden_imports += collect_submodules("windows_toasts")
except Exception:
    # The adapter is optional on non-Windows development builds.
    pass

try:
    hidden_imports += collect_submodules("pygame")
except Exception:
    pass

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=app_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "IPython", "jupyter", "matplotlib", "numpy", "pandas"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VeltrixTradingClock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(ROOT / "veltrix_version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Veltrix Trading Clock",
)
