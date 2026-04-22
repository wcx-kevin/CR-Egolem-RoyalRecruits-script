import argparse
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cr_bot.config.decks import DEFAULT_DECK_ID, list_decks, set_active_deck
from cr_bot.gameplay.battle_timing import (
    DIRECT_ELIXIR_STAGE_ENV,
    DIRECT_TIME_STAGE_ENV,
    normalize_elixir_stage,
    normalize_time_stage,
)


def _bootstrap_cli(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--deck", default=os.getenv("CR_DECK", DEFAULT_DECK_ID))
    parser.add_argument("--direct-battle", action="store_true")
    parser.add_argument("--list-decks", action="store_true")
    parser.add_argument("--time-stage", default=os.getenv(DIRECT_TIME_STAGE_ENV))
    parser.add_argument("--elixir-stage", default=os.getenv(DIRECT_ELIXIR_STAGE_ENV))
    return parser.parse_known_args(argv)


def _print_decks():
    for deck in list_decks():
        print(f"{deck.id}: {deck.display_name} - {deck.description}")


if __name__ == "__main__":
    bootstrap_args, remaining_args = _bootstrap_cli(sys.argv[1:])
    if bootstrap_args.list_decks:
        _print_decks()
        raise SystemExit(0)

    try:
        set_active_deck(bootstrap_args.deck)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)

    time_stage = normalize_time_stage(bootstrap_args.time_stage)
    elixir_stage = normalize_elixir_stage(bootstrap_args.elixir_stage)
    if bootstrap_args.time_stage and time_stage is None:
        print(f"Unsupported time stage '{bootstrap_args.time_stage}'.")
        raise SystemExit(1)
    if bootstrap_args.elixir_stage and elixir_stage is None:
        print(f"Unsupported elixir stage '{bootstrap_args.elixir_stage}'.")
        raise SystemExit(1)

    if time_stage is None:
        os.environ.pop(DIRECT_TIME_STAGE_ENV, None)
    else:
        os.environ[DIRECT_TIME_STAGE_ENV] = time_stage

    if elixir_stage is None:
        os.environ.pop(DIRECT_ELIXIR_STAGE_ENV, None)
    else:
        os.environ[DIRECT_ELIXIR_STAGE_ENV] = elixir_stage

    from cr_bot.app.main_loop import main

    forwarded_args = list(remaining_args)
    if bootstrap_args.direct_battle:
        forwarded_args.append("--direct-battle")
    main(forwarded_args)
