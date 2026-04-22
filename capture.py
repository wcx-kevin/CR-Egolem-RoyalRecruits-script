import argparse
from pathlib import Path
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cr_bot.config.decks import set_active_deck


def _bootstrap_cli(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--deck")
    return parser.parse_known_args(argv)


bootstrap_args, remaining_args = _bootstrap_cli(sys.argv[1:])
if bootstrap_args.deck:
    set_active_deck(bootstrap_args.deck)
sys.argv = [sys.argv[0], *remaining_args]

from cr_bot.config.device_config import DEVICE_ID
from cr_bot.paths import TEMPLATES_DIR
from cr_bot.tools.capture import capture_region


def main():
    region = capture_region(
        device_id=DEVICE_ID,
        x1=625,
        y1=2200,
        x2=800,
        y2=2300,
        save_path=os.path.join(os.fspath(TEMPLATES_DIR), "screenshot_region.png"),
    )
    if region is not None:
        print(f"Captured region shape: {region.shape}")
        return 0

    print("Failed to capture region.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
