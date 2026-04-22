import argparse
import json
import os
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2

from cr_bot.config.decks import get_deck_definition
from cr_bot.config.device_config import DEVICE_ID
from cr_bot.paths import DEBUG_OUTPUT_DIR
from cr_bot.recognition.checkType import GameStateDetector
from cr_bot.recognition.finalGetCards import CRCardRecognizer


def build_parser():
    parser = argparse.ArgumentParser(description="Low-overhead Clash Royale battle recorder.")
    parser.add_argument("--device-id", default=DEVICE_ID, help="ADB/uiautomator2 device id")
    parser.add_argument("--duration", type=float, default=900.0, help="Max run duration in seconds")
    parser.add_argument("--interval", type=float, default=2.0, help="Sampling interval in seconds")
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.fspath(DEBUG_OUTPUT_DIR), "battle_records"),
        help="Base directory for recorder output",
    )
    parser.add_argument(
        "--save-policy",
        choices=("all", "events", "changes", "none"),
        default="changes",
        help="When to save full screenshots",
    )
    parser.add_argument(
        "--save-crops",
        action="store_true",
        help="Also save cropped hand-card regions for saved screenshots",
    )
    parser.add_argument(
        "--capture-outside-battle",
        action="store_true",
        help="Record cards even when not in battle",
    )
    parser.add_argument("--vote-frames", type=int, default=1, help="Recognizer frames per sample")
    parser.add_argument("--vote-interval", type=float, default=0.0, help="Delay between recognizer frames")
    parser.add_argument("--unknown-retries", type=int, default=0, help="Extra retries for Unknown cards")
    return parser


def ensure_output_paths(base_dir):
    run_stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(base_dir, run_stamp)
    logs_dir = os.path.join(run_dir, "logs")
    screenshots_dir = os.path.join(run_dir, "screenshots")
    crops_dir = os.path.join(run_dir, "crops")
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(screenshots_dir, exist_ok=True)
    os.makedirs(crops_dir, exist_ok=True)
    return run_dir, logs_dir, screenshots_dir, crops_dir


def serialize_cards(cards):
    return [
        {
            "position": card["position"],
            "name": card["name"],
            "confidence": round(float(card["confidence"]), 4),
        }
        for card in cards
    ]


def count_known_cards(cards):
    return sum(1 for card in cards if card["name"] != "Unknown")


def cards_signature(cards):
    return tuple((str(card["position"]), card["name"]) for card in cards)


def save_json(path, payload):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def save_screenshot(path, screenshot):
    if screenshot is not None:
        cv2.imwrite(path, screenshot)


def save_card_crops(base_path, screenshot, recognizer):
    if screenshot is None:
        return []

    saved_paths = []
    for index, (x, y, w, h) in enumerate(recognizer.card_regions, start=1):
        crop = screenshot[y:y + h, x:x + w]
        crop_path = f"{base_path}_hand_{index}.png"
        cv2.imwrite(crop_path, crop)
        saved_paths.append(crop_path)

    x, y, w, h = recognizer.next_card_region
    next_crop = screenshot[y:y + h, x:x + w]
    next_crop_path = f"{base_path}_next.png"
    cv2.imwrite(next_crop_path, next_crop)
    saved_paths.append(next_crop_path)
    return saved_paths


def should_save_screenshot(save_policy, event_name, in_battle, cards_changed):
    if save_policy == "none":
        return False
    if save_policy == "all":
        return True
    if save_policy == "events":
        return event_name != "sample"
    return event_name != "sample" or cards_changed or in_battle


def main():
    args = build_parser().parse_args()
    deck = get_deck_definition()
    run_dir, logs_dir, screenshots_dir, crops_dir = ensure_output_paths(args.output_dir)
    log_path = os.path.join(logs_dir, "battle_log.jsonl")
    summary_path = os.path.join(logs_dir, "summary.json")
    meta_path = os.path.join(logs_dir, "meta.json")

    recognizer = CRCardRecognizer(
        device_id=args.device_id,
        vote_frames=args.vote_frames,
        vote_interval=args.vote_interval,
        unknown_retry_attempts=args.unknown_retries,
        unknown_retry_interval=max(args.interval * 0.25, 0.05),
    )
    detector = GameStateDetector(device_id=args.device_id, debug=False)

    meta = {
        "deck_id": deck.id,
        "deck_name": deck.display_name,
        "device_id": args.device_id,
        "duration": args.duration,
        "interval": args.interval,
        "save_policy": args.save_policy,
        "save_crops": args.save_crops,
        "capture_outside_battle": args.capture_outside_battle,
        "vote_frames": args.vote_frames,
        "vote_interval": args.vote_interval,
        "unknown_retries": args.unknown_retries,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_json(meta_path, meta)

    summary = {
        "samples": 0,
        "battle_start_events": 0,
        "battle_end_events": 0,
        "battle_signal_loss_events": 0,
        "screenshot_failures": 0,
        "saved_screenshots": 0,
        "max_known_cards": 0,
    }

    started_at = time.time()
    sample_index = 0
    last_in_battle = False
    last_cards_signature = None

    print(f"Recording to: {run_dir}")

    with open(log_path, "w", encoding="utf-8") as log_file:
        while time.time() - started_at < args.duration:
            screenshot = detector.take_screenshot()
            now = time.time()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            summary["samples"] += 1

            if screenshot is None:
                summary["screenshot_failures"] += 1
                record = {
                    "timestamp": timestamp,
                    "sample_index": sample_index,
                    "event": "screenshot_failed",
                }
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                log_file.flush()
                time.sleep(args.interval)
                sample_index += 1
                continue

            in_battle = detector.detect_game_start(screenshot)
            end_detected = detector.detect_game_end(screenshot) if in_battle else False
            event_name = "sample"
            if in_battle and not last_in_battle:
                event_name = "battle_start"
                summary["battle_start_events"] += 1
            elif end_detected:
                event_name = "battle_end"
                summary["battle_end_events"] += 1
            elif last_in_battle and not in_battle:
                event_name = "battle_lost_signal"
                summary["battle_signal_loss_events"] += 1

            cards = []
            if in_battle or args.capture_outside_battle:
                cards = recognizer.get_all_cards_from_screenshot(screenshot, retry_unknown=False)

            current_signature = cards_signature(cards)
            cards_changed = current_signature != last_cards_signature
            last_cards_signature = current_signature

            summary["max_known_cards"] = max(summary["max_known_cards"], count_known_cards(cards))

            screenshot_path = None
            crop_paths = []
            if should_save_screenshot(args.save_policy, event_name, in_battle, cards_changed):
                screenshot_name = f"{sample_index:05d}_{event_name}.png"
                screenshot_path = os.path.join(screenshots_dir, screenshot_name)
                save_screenshot(screenshot_path, screenshot)
                summary["saved_screenshots"] += 1

                if args.save_crops:
                    crop_base = os.path.join(crops_dir, f"{sample_index:05d}_{event_name}")
                    crop_paths = save_card_crops(crop_base, screenshot, recognizer)

            record = {
                "timestamp": timestamp,
                "sample_index": sample_index,
                "event": event_name,
                "in_battle": in_battle,
                "end_detected": end_detected,
                "known_cards": count_known_cards(cards),
                "cards_changed": cards_changed,
                "cards": serialize_cards(cards),
                "screenshot": screenshot_path,
                "crops": crop_paths,
            }
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            log_file.flush()

            print(
                f"[{timestamp}] event={event_name} in_battle={in_battle} "
                f"known_cards={record['known_cards']} saved={bool(screenshot_path)}"
            )

            last_in_battle = in_battle and not end_detected
            time.sleep(args.interval)
            sample_index += 1

    summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_json(summary_path, summary)
    print(f"Done. Log saved to: {log_path}")


if __name__ == "__main__":
    main()
