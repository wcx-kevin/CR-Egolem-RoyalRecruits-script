import argparse
from pathlib import Path
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


if __name__ == "__main__":
    bootstrap_args, remaining_args = _bootstrap_cli(sys.argv[1:])
    if bootstrap_args.deck:
        set_active_deck(bootstrap_args.deck)

    sys.argv = [sys.argv[0], *remaining_args]

    from cr_bot.tools.battle_debug_recorder import main

    main()
