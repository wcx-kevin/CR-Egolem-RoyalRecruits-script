from __future__ import annotations

import argparse
import statistics
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


BATTLE_RECORDS_DIR = PROJECT_ROOT / "debug_output" / "battle_records" / "20260413_201928" / "screenshots"
GROUND_TRUTH = {
    "00038_battle_start.png": {
        1: "arrows",
        3: "GMachine",
        4: "Ksk",
        "next": "sk",
    },
    "00039_battle_lost_signal.png": {
        1: "arrows",
        2: "sk",
        3: "GMachine",
        4: "Ksk",
        "next": "NWitch",
    },
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
        device_id="offline-benchmark",
        vote_frames=1,
        vote_interval=0.0,
        unknown_retry_attempts=0,
    )


def load_dataset():
    dataset = []
    for file_name, labels in GROUND_TRUTH.items():
        image_path = BATTLE_RECORDS_DIR / file_name
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"unable to load screenshot: {image_path}")
        dataset.append((file_name, image, labels))
    return dataset


def evaluate(recognizer, dataset):
    details = []
    correct = 0
    total = 0

    for file_name, image, labels in dataset:
        results = recognizer.get_all_cards_from_screenshot(image, retry_unknown=False)
        by_position = {item["position"]: item for item in results}

        screenshot_hits = []
        for position, expected_name in labels.items():
            predicted = by_position.get(position, {"name": "Missing", "confidence": 0.0})
            normalized_expected = expected_name if expected_name == "Unknown" else normalize_card_name(expected_name)
            hit = predicted["name"] == normalized_expected
            correct += int(hit)
            total += 1
            screenshot_hits.append(
                {
                    "position": position,
                    "expected": normalized_expected,
                    "predicted": predicted["name"],
                    "confidence": predicted["confidence"],
                    "correct": hit,
                }
            )

        details.append(
            {
                "screenshot": file_name,
                "results": results,
                "judgements": screenshot_hits,
            }
        )

    return {
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total else 0.0,
        "details": details,
    }


def benchmark(recognizer, dataset, iterations):
    timings_ms = []
    for _ in range(iterations):
        for _, image, _ in dataset:
            start = time.perf_counter()
            recognizer.get_all_cards_from_screenshot(image, retry_unknown=False)
            timings_ms.append((time.perf_counter() - start) * 1000.0)

    return {
        "iterations": iterations,
        "calls": len(timings_ms),
        "avg_ms": statistics.fmean(timings_ms),
        "median_ms": statistics.median(timings_ms),
        "min_ms": min(timings_ms),
        "max_ms": max(timings_ms),
    }


def main():
    parser = argparse.ArgumentParser(description="Offline battle-record screenshot evaluation")
    parser.add_argument("--iterations", type=int, default=200, help="timing iterations per screenshot")
    args = parser.parse_args()

    dataset = load_dataset()
    recognizer = build_recognizer()
    metrics = evaluate(recognizer, dataset)
    timing = benchmark(recognizer, dataset, args.iterations)

    print(f"Accuracy: {metrics['correct']}/{metrics['total']} = {metrics['accuracy']:.4f}")
    print(
        "Timing(ms): "
        f"avg={timing['avg_ms']:.3f}, median={timing['median_ms']:.3f}, "
        f"min={timing['min_ms']:.3f}, max={timing['max_ms']:.3f}, calls={timing['calls']}"
    )

    for detail in metrics["details"]:
        print(f"\n[{detail['screenshot']}]")
        for result in detail["results"]:
            print(
                f"  result pos={result['position']}: "
                f"{result['name']} ({result['confidence']:.4f})"
            )
        for item in detail["judgements"]:
            status = "OK" if item["correct"] else "MISS"
            print(
                f"  {status} pos={item['position']}: "
                f"expected={item['expected']}, predicted={item['predicted']}, "
                f"confidence={item['confidence']:.4f}"
            )


if __name__ == "__main__":
    main()
