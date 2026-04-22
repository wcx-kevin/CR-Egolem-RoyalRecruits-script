import time

from cr_bot.config.decks import get_deck_definition
from cr_bot.core.comCycle import CRCardCycle
from cr_bot.gameplay.battle_timing import BattleTimingSelection, read_direct_battle_selection
from cr_bot.gameplay.changeCycle import changeCycle
from cr_bot.gameplay.format2_elixir_golem import (
    format2_elixir_golem_1x,
    format2_elixir_golem_2x,
    format2_elixir_golem_3x,
)
from cr_bot.gameplay.format2_royal_recruits import (
    format2_royal_recruits_1x,
    format2_royal_recruits_2x,
    format2_royal_recruits_3x,
)
from cr_bot.gameplay.getCycle import init5
from cr_bot.gameplay.placeCard import sleep_with_runtime_checks
from cr_bot.gameplay.resource_state import set_battle_elixir_stage


cycle = CRCardCycle()


def _stop_requested(stop_event):
    if stop_event.is_set():
        print("Operation 2 received a stop signal.")
        return True
    return False


def _wait(stop_event, delay):
    deadline = time.perf_counter() + max(0.0, float(delay))
    while time.perf_counter() < deadline:
        if _stop_requested(stop_event):
            return False
        sleep_with_runtime_checks(min(0.25, deadline - time.perf_counter()))
    return not _stop_requested(stop_event)


def _run_lines(stop_event, handler, delay, max_line):
    for line in range(1, max_line + 1):
        if _stop_requested(stop_event):
            return False
        handler(delay, 1, line)
    return True


def _resolve_battle_timing(direct_battle):
    if direct_battle:
        return read_direct_battle_selection()
    return BattleTimingSelection()


def _run_elixir_golem_sequence(stop_event, direct_battle=False):
    timing = _resolve_battle_timing(direct_battle)
    print(f"Elixir Golem timing selection: {timing.describe()}")

    init5()
    cycle.show_all()

    if not changeCycle():
        print("Deck cycle adjustment timed out or recognition failed.")
        return

    cycle.show_all()

    if timing.start_elixir_stage == "single":
        set_battle_elixir_stage("single", reason="elixir_golem_1x", source="runtime")
        if not _run_lines(stop_event, format2_elixir_golem_1x, 4.5, 6):
            return
        for _ in range(2):
            if not _wait(stop_event, 3.0):
                return

        if timing.should_extend_single_stage:
            if not _run_lines(stop_event, format2_elixir_golem_1x, 4.0, 6):
                return
            for _ in range(2):
                if not _wait(stop_event, 2.5):
                    return
        else:
            for _ in range(2):
                if not _wait(stop_event, 2.5):
                    return

    if timing.start_elixir_stage in {"single", "double"}:
        set_battle_elixir_stage("double", reason="elixir_golem_2x", source="runtime")
        for _ in range(4):
            if not _wait(stop_event, 1.2):
                return
            if not _run_lines(stop_event, format2_elixir_golem_2x, 2.2, 7):
                return

    set_battle_elixir_stage("triple", reason="elixir_golem_3x", source="runtime")
    for _ in range(3):
        if not _run_lines(stop_event, format2_elixir_golem_3x, 1.4, 10):
            return


def _run_royal_recruits_sequence(stop_event, direct_battle=False):
    timing = _resolve_battle_timing(direct_battle)
    print(f"Royal Recruits timing selection: {timing.describe()}")

    init5()
    cycle.show_all()

    if not changeCycle():
        print("Deck cycle adjustment timed out or recognition failed.")
        return

    cycle.show_all()

    if timing.start_elixir_stage == "single":
        set_battle_elixir_stage("single", reason="royal_recruits_1x", source="runtime")
        if not _run_lines(stop_event, format2_royal_recruits_1x, 3.2, 5):
            return

    if timing.start_elixir_stage in {"single", "double"}:
        set_battle_elixir_stage("double", reason="royal_recruits_2x", source="runtime")
        for _ in range(2):
            if not _wait(stop_event, 1.1):
                return
            if not _run_lines(stop_event, format2_royal_recruits_2x, 2.0, 7):
                return

    set_battle_elixir_stage("triple", reason="royal_recruits_3x", source="runtime")
    for _ in range(2):
        if not _wait(stop_event, 0.8):
            return
        if not _run_lines(stop_event, format2_royal_recruits_3x, 1.5, 8):
            return


def run_selected_deck(stop_event, direct_battle=False):
    deck = get_deck_definition()
    print(f"Running deck routine: {deck.display_name} ({deck.id})")

    if deck.strategy == "elixir_golem_autoplay":
        _run_elixir_golem_sequence(stop_event, direct_battle=direct_battle)
        return
    if deck.strategy == "royal_recruits_autoplay":
        _run_royal_recruits_sequence(stop_event, direct_battle=direct_battle)
        return

    init5()
    cycle.show_all()
    print(f"Deck '{deck.display_name}' does not have an autoplay runtime.")
