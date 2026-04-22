import time

from cr_bot.core.comCycle import CRCardCycle
from cr_bot.gameplay.card_tracker import bootstrap_cycle, get_recognizer, reset_runtime_tracker
from cr_bot.gameplay.placeCard import placeCardP

cycle = CRCardCycle()

INIT_RECOGNITION_RETRIES = 2
INIT_RECOGNITION_INTERVAL = 0.12


def _get_recognizer():
    return get_recognizer()


def _count_known_cards(include_next=True):
    positions = [1, 2, 3, 4]
    if include_next:
        positions.append(5)
    return sum(1 for position in positions if cycle.get_card(position) != "Unknown")


def init5():
    reset_runtime_tracker()
    for attempt in range(INIT_RECOGNITION_RETRIES + 1):
        if bootstrap_cycle():
            return
        if attempt + 1 <= INIT_RECOGNITION_RETRIES:
            time.sleep(INIT_RECOGNITION_INTERVAL)


def test(x, px):
    placeCardP(x, px)
    time.sleep(2)
    result = _get_recognizer().get_card_at_position(x)
    cycle.set_card(x, result["name"], result["confidence"])


if __name__ == "__main__":
    init5()
    cycle.show_all()
    test(1, 0)
    test(3, 8)
    test(2, 4)
    test(4, 6)
    cycle.show_all()
