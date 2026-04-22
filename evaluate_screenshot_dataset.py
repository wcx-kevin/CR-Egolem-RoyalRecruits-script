from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import cr_bot.recognition.finalGetCards as recognition_module
from cr_bot.core.card_config import normalize_card_name


DATASET_DIR = PROJECT_ROOT / "debug_output" / "screenshot_records" / "20260415_122601" / "screenshots"
LABELS = {
    "00020.png": {1: "rage", 2: "Ksk", 3: "arrows", 4: "EGolem", "next": "sk"},
    "00040.png": {1: "rage", 2: "Unknown", 3: "arrows", 4: "Ksk", "next": "sk"},
    "00060.png": {1: "Ksk", 2: "GMachine", 3: "arrows", 4: "sk", "next": "archer"},
    "00100.png": {1: "archer", 2: "sk", 3: "GMachine", 4: "rage", "next": "NWitch"},
    "00140.png": {1: "rage", 2: "arrows", 3: "archer", 4: "Ksk", "next": "GMachine"},
    "00160.png": {1: "arrows", 2: "EGolem", 3: "GMachine", 4: "Unknown", "next": "Ksk"},
    "00180.png": {1: "Unknown", 2: "GMachine", 3: "archer", 4: "sk", "next": "Ksk"},
    "00220.png": {1: "Ksk", 2: "GMachine", 3: "sk", 4: "arrows"},
    "00240.png": {1: "sk", 2: "GMachine", 3: "rage", 4: "arrows", "next": "Ksk"},
}


class DummyDevice:
    def window_size(self):
        return (1440, 2560)

    def app_current(self):
        return {"package": "com.tencent.tmgp.supercell.clashroyale"}

    def app_start(self, package):
        return None

    def screenshot(self, format="opencv"):
        return None


def build_recognizer():
    recognition_module.u2.connect = lambda *args, **kwargs: DummyDevice()
    return recognition_module.CRCardRecognizer(
        device_id="offline-eval",
        vote_frames=1,
        vote_interval=0.0,
        unknown_retry_attempts=0,
    )


def main():
    recognizer = build_recognizer()
    total = 0
    correct = 0
    timings_ms = []

    for file_name, truth in LABELS.items():
        image_path = DATASET_DIR / file_name
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"missing screenshot: {image_path}")

        started_at = time.perf_counter()
        results = recognizer.get_all_cards_from_screenshot(image, retry_unknown=False)
        timings_ms.append((time.perf_counter() - started_at) * 1000.0)
        by_position = {item["position"]: item for item in results}

        print(f"\n[{file_name}]")
        for position, expected_name in truth.items():
            predicted = by_position[position]
            normalized_expected = expected_name if expected_name == "Unknown" else normalize_card_name(expected_name)
            ok = predicted["name"] == normalized_expected
            correct += int(ok)
            total += 1
            status = "OK" if ok else "MISS"
            print(
                f"  {status} pos={position}: expected={normalized_expected}, "
                f"predicted={predicted['name']}, confidence={predicted['confidence']:.4f}"
            )

    avg_ms = sum(timings_ms) / len(timings_ms)
    print(f"\nAccuracy: {correct}/{total} = {correct / total:.4f}")
    print(f"Average time per screenshot: {avg_ms:.3f} ms")


if __name__ == "__main__":
    main()
