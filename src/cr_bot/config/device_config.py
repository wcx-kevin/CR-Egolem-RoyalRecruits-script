import os
import shutil
import subprocess

DEFAULT_DEVICE_ID = "127.0.0.1:16384"
DEFAULT_PACKAGE_NAME = "com.tencent.tmgp.supercell.clashroyale"
DEFAULT_MUMU_ADB = r"E:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe"
DEFAULT_TENCENT_ADB = r"E:\Program Files\Tencent\GameAssist\Application\6.10.5410.485\adb.exe"


def _candidate_adb_paths():
    env_adb = os.getenv("CR_ADB_EXE") or os.getenv("ADB_EXE")
    if env_adb:
        yield env_adb

    which_adb = shutil.which("adb")
    if which_adb:
        yield which_adb

    if os.path.exists(DEFAULT_MUMU_ADB):
        yield DEFAULT_MUMU_ADB

    if os.path.exists(DEFAULT_TENCENT_ADB):
        yield DEFAULT_TENCENT_ADB

    yield "adb"


def resolve_adb_exe():
    for candidate in _candidate_adb_paths():
        if candidate == "adb" or os.path.exists(candidate):
            return candidate
    return "adb"


def list_adb_devices(adb_exe=None):
    adb_exe = adb_exe or resolve_adb_exe()
    try:
        output = subprocess.check_output(
            [adb_exe, "devices"],
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
    except Exception:
        return []

    devices = []
    for raw_line in output.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        devices.append((parts[0], parts[1]))
    return devices


def resolve_device_id(adb_exe=None):
    env_device_id = os.getenv("CR_DEVICE_ID")
    if env_device_id:
        return env_device_id

    devices = list_adb_devices(adb_exe)
    for serial, state in devices:
        if state == "device":
            return serial

    for serial, _ in devices:
        if serial.startswith("emulator-"):
            return serial

    return DEFAULT_DEVICE_ID


def adb_command(*args, device_id=None, adb_exe=None):
    adb_exe = adb_exe or ADB_EXE
    device_id = device_id or DEVICE_ID
    command = [adb_exe]
    if device_id:
        command.extend(["-s", device_id])
    command.extend(args)
    return command


ADB_EXE = resolve_adb_exe()
DEVICE_ID = resolve_device_id(ADB_EXE)
PACKAGE_NAME = os.getenv("CR_PACKAGE_NAME", DEFAULT_PACKAGE_NAME)
