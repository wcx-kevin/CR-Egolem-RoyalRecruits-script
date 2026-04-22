from __future__ import annotations

from collections.abc import Callable, Sequence

from cr_bot.gameplay.placeCard import placeCardOptions, sleep_with_runtime_checks


Placement = int | Callable[[int], int]
SequenceStep = tuple[tuple[str, ...], Placement, float | int]


def run_timed_card_sequence(
    delay: float,
    random_seed: int,
    line: int,
    steps: Sequence[SequenceStep],
    final_wait: float = 0.0,
):
    if line < 1 or line > len(steps):
        return

    card_names, place_position, wait_factor = steps[line - 1]
    lane_offset = random_seed % 2
    resolved_place = place_position(lane_offset) if callable(place_position) else place_position
    played_card = placeCardOptions(card_names, resolved_place)
    if wait_factor:
        if played_card is None:
            sleep_with_runtime_checks(min(0.8, max(0.2, delay * 0.25)))
        else:
            sleep_with_runtime_checks(delay * float(wait_factor))
    elif final_wait:
        sleep_with_runtime_checks(final_wait)
    return played_card
