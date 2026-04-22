import time

from cr_bot.config.decks import get_deck_definition
from cr_bot.core.comCycle import CRCardCycle
from cr_bot.gameplay.getCycle import init5
from cr_bot.gameplay.placeCard import placeCardN, refresh_cycle_from_screen, sleep_with_runtime_checks


cycle = CRCardCycle()

CYCLE_TIMEOUT_SECONDS = 90.0
UNKNOWN_RETRY_LIMIT = 4


def _find_first(card_name):
    matches = cycle.find_card(card_name, [])
    return matches[0] if matches else None


def _is_available(card_name):
    match = _find_first(card_name)
    return match is not None and match["type"] == "available"


def _is_within_cycle(card_name, max_position):
    match = _find_first(card_name)
    return match is not None and isinstance(match["position"], int) and match["position"] <= max_position


def _play_first_available(options):
    for card_name, place_position, delay in options:
        if _is_available(card_name):
            placeCardN(card_name, place_position)
            return delay
    return None


def _refresh_unknown_cycle_card(guess_in_progress, unknown_retry_count, place_position):
    if not _is_available("Unknown"):
        return False, guess_in_progress, unknown_retry_count, 0.0

    if not guess_in_progress:
        placeCardN("Unknown", place_position)
        return True, True, 0, 1.5

    updates = refresh_cycle_from_screen(unknown_only=True, include_next=True)
    if updates > 0:
        return True, False, 0, 0.5

    unknown_retry_count += 1
    if unknown_retry_count >= UNKNOWN_RETRY_LIMIT:
        print("Unknown card could not be resolved while adjusting the cycle.")
        return True, True, unknown_retry_count, -1.0

    return True, True, unknown_retry_count, 1.0


def _is_elixir_golem_cycle_ready():
    support_ready = (
        (_is_available("archers") or _is_available("skeletons") or _is_available("night_witch"))
        and _is_within_cycle("goblin_machine", 5)
    )
    push_ready = (
        _is_available("elixir_golem")
        and (_is_within_cycle("night_witch", 6) or _is_within_cycle("archers", 6))
        and (_is_within_cycle("rage", 7) or _is_within_cycle("skeleton_king", 7))
    )
    return support_ready or push_ready


def _change_cycle_elixir_golem():
    guess_in_progress = False
    unknown_retry_count = 0
    started_at = time.perf_counter()

    while not _is_elixir_golem_cycle_ready():
        delay = _play_first_available(
            [
                ("skeletons", 0, 1.6),
                ("archers", 4, 2.0),
                ("night_witch", 0, 2.8),
                ("arrows", 10, 2.2),
            ]
        )

        if delay is not None:
            guess_in_progress = False
            unknown_retry_count = 0
        else:
            handled_unknown, guess_in_progress, unknown_retry_count, delay = _refresh_unknown_cycle_card(
                guess_in_progress,
                unknown_retry_count,
                0,
            )
            if handled_unknown and delay < 0:
                return False
            if not handled_unknown:
                delay = _play_first_available(
                    [
                        ("goblin_machine", 8, 2.5),
                        ("night_witch", 0, 2.4),
                        ("skeleton_king", 3, 2.2),
                        ("elixir_golem", 0, 2.0),
                        ("rage", 10, 1.6),
                    ]
                )
                if delay is None:
                    delay = 1.0
                guess_in_progress = False
                unknown_retry_count = 0

        if _is_elixir_golem_cycle_ready():
            delay /= 2.0

        sleep_with_runtime_checks(delay)
        if time.perf_counter() - started_at > CYCLE_TIMEOUT_SECONDS:
            return False

    return True


def _is_royal_recruits_cycle_ready():
    support_ready = (
        (_is_available("goblin_cage") or _is_available("zappies") or _is_available("barbarian_barrel"))
        and (_is_within_cycle("royal_recruits", 6) or _is_within_cycle("golden_knight", 6))
        and _is_within_cycle("flying_machine", 7)
    )
    push_ready = (
        _is_available("royal_recruits")
        and (_is_within_cycle("royal_hogs", 6) or _is_within_cycle("golden_knight", 6))
        and (_is_within_cycle("zappies", 7) or _is_within_cycle("goblin_cage", 7))
    )
    return support_ready or push_ready


def _change_cycle_royal_recruits():
    guess_in_progress = False
    unknown_retry_count = 0
    started_at = time.perf_counter()

    while not _is_royal_recruits_cycle_ready():
        delay = _play_first_available(
            [
                ("barbarian_barrel", 10, 1.4),
                ("zappies", 4, 1.8),
                ("goblin_cage", 4, 2.0),
                ("arrows", 10, 1.6),
                ("golden_knight", 3, 2.2),
            ]
        )

        if delay is not None:
            guess_in_progress = False
            unknown_retry_count = 0
        else:
            handled_unknown, guess_in_progress, unknown_retry_count, delay = _refresh_unknown_cycle_card(
                guess_in_progress,
                unknown_retry_count,
                4,
            )
            if handled_unknown and delay < 0:
                return False
            if not handled_unknown:
                delay = _play_first_available(
                    [
                        ("flying_machine", 6, 2.0),
                        ("royal_recruits", 0, 2.4),
                        ("golden_knight", 3, 1.8),
                        ("royal_hogs", 8, 2.2),
                    ]
                )
                if delay is None:
                    delay = 1.0
                guess_in_progress = False
                unknown_retry_count = 0

        if _is_royal_recruits_cycle_ready():
            delay /= 2.0

        sleep_with_runtime_checks(delay)
        if time.perf_counter() - started_at > CYCLE_TIMEOUT_SECONDS:
            return False

    return True


def changeCycle():
    deck = get_deck_definition()
    if deck.id == "elixir_golem":
        return _change_cycle_elixir_golem()
    if deck.id == "royal_recruits":
        return _change_cycle_royal_recruits()

    print(f"changeCycle is not implemented for deck '{deck.id}'.")
    return False


if __name__ == "__main__":
    init5()
    cycle.show_all()
    changeCycle()
    cycle.show_all()
