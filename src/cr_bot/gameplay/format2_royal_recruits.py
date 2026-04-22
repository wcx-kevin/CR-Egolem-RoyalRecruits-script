from cr_bot.core.comCycle import CRCardCycle
from cr_bot.gameplay.changeCycle import changeCycle
from cr_bot.gameplay.getCycle import init5
from cr_bot.gameplay.sequence_runtime import run_timed_card_sequence


cycle = CRCardCycle()

ROYAL_RECRUITS_1X = (
    (("goblin_cage", "zappies"), lambda o: 4 + o, 1.0),
    (("flying_machine", "golden_knight"), lambda o: 6 + o, 0.8),
    (("royal_recruits", "goblin_cage"), lambda o: o, 1.1),
    (("golden_knight", "barbarian_barrel"), lambda o: 3 - o, 0.8),
    (("royal_hogs", "barbarian_barrel"), lambda o: 8 + o, 1.0),
)
ROYAL_RECRUITS_2X = (
    (("royal_recruits", "goblin_cage"), lambda o: o, 0.9),
    (("flying_machine", "zappies"), lambda o: 6 + o, 0.8),
    (("golden_knight", "barbarian_barrel"), lambda o: 3 - o, 0.7),
    (("royal_hogs", "barbarian_barrel"), lambda o: 9 - o, 0.9),
    (("zappies", "goblin_cage"), lambda o: 4 + o, 0.7),
    (("barbarian_barrel", "arrows"), lambda o: 10 + o, 0.4),
    (("arrows", "barbarian_barrel"), lambda o: 11 - o, 0.6),
)
ROYAL_RECRUITS_3X = (
    (("royal_recruits", "goblin_cage"), lambda o: 4 + o, 0.8),
    (("royal_hogs", "barbarian_barrel"), lambda o: 8 + o, 0.8),
    (("flying_machine", "zappies"), lambda o: 6 + o, 0.7),
    (("golden_knight", "barbarian_barrel"), lambda o: 3 - o, 0.7),
    (("zappies", "goblin_cage"), lambda o: 5 - o, 0.7),
    (("barbarian_barrel", "arrows"), lambda o: 10 + o, 0.4),
    (("arrows", "barbarian_barrel"), lambda o: 11 - o, 0.4),
    (("goblin_cage", "zappies"), lambda o: 4 + o, 0.0),
)


def format2_royal_recruits_1x(delay, random_seed, line):
    run_timed_card_sequence(delay, random_seed, line, ROYAL_RECRUITS_1X)


def format2_royal_recruits_2x(delay, random_seed, line):
    run_timed_card_sequence(delay, random_seed, line, ROYAL_RECRUITS_2X)


def format2_royal_recruits_3x(delay, random_seed, line):
    run_timed_card_sequence(delay, random_seed, line, ROYAL_RECRUITS_3X)


if __name__ == "__main__":
    init5()
    cycle.show_all()
    changeCycle()
    cycle.show_all()

    for line in range(1, 6):
        format2_royal_recruits_1x(4.5, 0, line)

    for line in range(1, 8):
        format2_royal_recruits_2x(3.0, 0, line)

    for line in range(1, 9):
        format2_royal_recruits_3x(2.0, 0, line)
