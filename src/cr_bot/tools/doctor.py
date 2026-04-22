import argparse
import os
import subprocess
import sys

import cv2
import numpy as np

from cr_bot.config.decks import get_deck_definition
from cr_bot.config.device_config import ADB_EXE, DEVICE_ID, PACKAGE_NAME, adb_command, list_adb_devices
from cr_bot.core.card_config import card_key, get_card_template_groups
from cr_bot.paths import TEMPLATES_DIR, get_cards_dir, get_cards_full_dir

EXPECTED_SIZE = "1440x2560"


def run_command(command, timeout=15):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
        )
    except Exception as exc:
        return None, str(exc), 1

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    return stdout, stderr, result.returncode


def print_section(title):
    print(f"\n[{title}]")


def _image_stems(directory):
    if not os.path.isdir(directory):
        return set()

    stems = set()
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        if not os.path.isfile(file_path):
            continue

        stem, ext = os.path.splitext(file_name)
        if ext.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            continue
        stems.add(card_key(stem))
    return stems


def ensure_device_online():
    devices = list_adb_devices(ADB_EXE)
    online = {serial for serial, state in devices if state == "device"}
    if DEVICE_ID in online:
        return True

    if ":" in DEVICE_ID:
        stdout, stderr, returncode = run_command([ADB_EXE, "connect", DEVICE_ID])
        if stdout:
            print(stdout)
        if stderr:
            print(stderr)
        if returncode != 0:
            return False

    devices = list_adb_devices(ADB_EXE)
    return any(serial == DEVICE_ID and state == "device" for serial, state in devices)


def main():
    parser = argparse.ArgumentParser(description="Project preflight checks for ADB/uiautomator2.")
    parser.add_argument("--strict-resolution", action="store_true", help="Fail if wm size is not 1440x2560.")
    args = parser.parse_args()
    deck = get_deck_definition()
    card_template_groups = get_card_template_groups(deck.id)
    cards_dir = get_cards_dir(deck.id)
    cards_full_dir = get_cards_full_dir(deck.id)

    failures = []
    warnings = []

    print_section("config")
    print(f"ADB_EXE={ADB_EXE}")
    print(f"DEVICE_ID={DEVICE_ID}")
    print(f"PACKAGE_NAME={PACKAGE_NAME}")
    print(f"DECK={deck.id} ({deck.display_name})")

    print_section("adb")
    if not ensure_device_online():
        failures.append(f"ADB device {DEVICE_ID} is not online.")
    else:
        print(f"device {DEVICE_ID} is online")

    devices = list_adb_devices(ADB_EXE)
    print(f"devices={devices}")

    stdout, stderr, returncode = run_command(adb_command("shell", "getprop", "sys.boot_completed"))
    if returncode != 0 or stdout.strip() != "1":
        failures.append(f"boot_completed check failed: stdout={stdout!r} stderr={stderr!r}")
    else:
        print("boot_completed=1")

    stdout, stderr, returncode = run_command(adb_command("shell", "wm", "size"))
    if returncode != 0:
        failures.append(f"wm size failed: {stderr or stdout}")
        wm_size = None
    else:
        print(stdout)
        wm_size = stdout.replace("Physical size:", "").strip()
        if wm_size != EXPECTED_SIZE:
            message = f"wm size is {wm_size}, expected {EXPECTED_SIZE}"
            if args.strict_resolution:
                failures.append(message)
            else:
                warnings.append(message)

    print_section("screenshot")
    try:
        result = subprocess.run(
            adb_command("exec-out", "screencap", "-p"),
            capture_output=True,
            timeout=20,
            check=True,
        )
        screenshot = cv2.imdecode(np.frombuffer(result.stdout, np.uint8), cv2.IMREAD_COLOR)
    except Exception as exc:
        screenshot = None
        failures.append(f"screenshot failed: {exc}")

    if screenshot is not None:
        print(f"shape={screenshot.shape}")
        if screenshot.shape[:2] != (2560, 1440):
            message = f"screenshot shape is {screenshot.shape}, expected (2560, 1440, 3)"
            if args.strict_resolution:
                failures.append(message)
            else:
                warnings.append(message)

    print_section("uiautomator2")
    try:
        import uiautomator2 as u2

        device = u2.connect(DEVICE_ID)
        print(f"window_size={device.window_size()}")
        current_app = device.app_current()
        print(f"app_current={current_app}")
        current_package = current_app.get("package")
        if current_package != PACKAGE_NAME:
            warnings.append(
                f"foreground package is {current_package!r}, expected {PACKAGE_NAME!r}. "
                "Open Clash Royale before running main.py."
            )
    except Exception as exc:
        failures.append(f"uiautomator2 check failed: {exc}")

    print_section("assets")
    required_paths = [
        os.fspath(cards_dir),
        os.fspath(cards_full_dir),
        os.fspath(TEMPLATES_DIR / "game_end_template.png"),
    ]
    for path in required_paths:
        exists = os.path.exists(path)
        print(f"{path} -> {exists}")
        if not exists:
            failures.append(f"missing required path: {path}")

    cards_stems = _image_stems(os.fspath(cards_dir))
    full_cards_stems = _image_stems(os.fspath(cards_full_dir))
    missing_cards = []
    missing_full_cards = []
    for canonical_name, aliases in card_template_groups.items():
        alias_keys = {card_key(canonical_name), *(card_key(alias) for alias in aliases)}
        if not (cards_stems & alias_keys):
            missing_cards.append(canonical_name)
        if not (full_cards_stems & alias_keys):
            missing_full_cards.append(canonical_name)

    if missing_cards:
        failures.append(f"missing cards templates: {', '.join(missing_cards)}")
    if missing_full_cards:
        failures.append(f"missing cards_full templates: {', '.join(missing_full_cards)}")

    if warnings:
        print_section("warnings")
        for warning in warnings:
            print(f"- {warning}")

    if failures:
        print_section("failures")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print_section("result")
    print("preflight passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
