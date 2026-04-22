import argparse
import json
import os
import subprocess
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2
import numpy as np

from cr_bot.config.device_config import DEVICE_ID, adb_command
from cr_bot.paths import DEBUG_OUTPUT_DIR

try:
    import uiautomator2 as u2
except ImportError:
    u2 = None


def parse_args():
    parser = argparse.ArgumentParser(description="Capture a full screenshot every N seconds.")
    parser.add_argument("--device-id", default=DEVICE_ID, help="ADB/uiautomator2 device id")
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Seconds between screenshots",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Total run duration in seconds, 0 means run until Ctrl+C",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.fspath(DEBUG_OUTPUT_DIR), "screenshot_records"),
        help="Base output directory",
    )
    return parser.parse_args()


def connect_device(device_id):
    if u2 is None:
        return None

    try:
        return u2.connect(device_id)
    except Exception:
        return None


def take_screenshot(device, device_id):
    if device is not None:
        try:
            screenshot = device.screenshot(format="opencv")
            if screenshot is not None:
                return screenshot
        except Exception:
            pass

    try:
        adb_cmd = adb_command("exec-out", "screencap", "-p", device_id=device_id)
        result = subprocess.run(
            adb_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        if result.stderr:
            return None

        nparr = np.frombuffer(result.stdout, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def build_output_dirs(base_output_dir):
    session_id = time.strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(base_output_dir, session_id)
    screenshots_dir = os.path.join(session_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    return session_id, session_dir, screenshots_dir


def write_meta(session_dir, args, started_at):
    meta = {
        "device_id": args.device_id,
        "interval": args.interval,
        "duration": args.duration,
        "started_at": started_at,
    }
    meta_path = os.path.join(session_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)


def main():
    args = parse_args()
    interval = max(0.1, float(args.interval))
    duration = max(0.0, float(args.duration))

    device = connect_device(args.device_id)
    session_id, session_dir, screenshots_dir = build_output_dirs(args.output_dir)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    write_meta(session_dir, args, started_at)

    print(f"session: {session_id}")
    print(f"output: {session_dir}")
    print(f"interval: {interval:.2f}s")
    if duration > 0:
        print(f"duration: {duration:.1f}s")
    else:
        print("duration: until Ctrl+C")

    started_monotonic = time.monotonic()
    sample_index = 0

    try:
        while True:
            if duration > 0 and (time.monotonic() - started_monotonic) >= duration:
                break

            loop_started = time.monotonic()
            screenshot = take_screenshot(device, args.device_id)
            if screenshot is None:
                print(f"[{sample_index:05d}] screenshot failed")
            else:
                file_name = f"{sample_index:05d}.png"
                file_path = os.path.join(screenshots_dir, file_name)
                cv2.imwrite(file_path, screenshot)
                print(f"[{sample_index:05d}] saved {file_path}")
                sample_index += 1

            elapsed = time.monotonic() - loop_started
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        print("stopped by user")

    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    summary = {
        "session_id": session_id,
        "saved_screenshots": sample_index,
        "finished_at": finished_at,
    }
    summary_path = os.path.join(session_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print(f"finished: {finished_at}")
    print(f"saved_screenshots: {sample_index}")


if __name__ == "__main__":
    main()
