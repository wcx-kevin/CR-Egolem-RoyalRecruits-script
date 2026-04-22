import time

from cr_bot.core.comCycle import CRCardCycle
from cr_bot.gameplay.changeCycle import changeCycle
from cr_bot.gameplay.getCycle import init5
from cr_bot.gameplay.sequence_runtime import run_timed_card_sequence


cycle = CRCardCycle()

ELIXIR_GOLEM_1X = (
    (("archers", "skeletons"), lambda o: 4 + o, 0.8),
    (("night_witch", "archers"), lambda o: o, 1.4),
    (("goblin_machine", "archers"), lambda o: 9 - o, 1.0),
    (("elixir_golem", "skeletons"), lambda o: o, 1.0),
    (("rage", "arrows"), lambda o: 10 + o, 0.7),
    (("skeleton_king", "archers"), lambda o: 3 - o, 0.0),
)
ELIXIR_GOLEM_2X = (
    (("night_witch", "archers"), lambda o: o, 1.4),
    (("goblin_machine", "archers"), lambda o: 8 + o, 1.0),
    (("elixir_golem", "skeletons"), lambda o: 4 + o, 0.8),
    (("skeleton_king", "archers"), lambda o: 1 - o, 1.1),
    (("rage", "arrows"), lambda o: 10 + o, 0.7),
    (("skeletons", "archers"), lambda o: 5 - o, 0.6),
    (("archers", "skeletons"), lambda o: 7 - o, 0.8),
)
ELIXIR_GOLEM_3X = (
    (("night_witch", "archers"), lambda o: 4 + o, 1.0),
    (("elixir_golem", "skeletons"), lambda o: 4 + o, 0.8),
    (("goblin_machine", "archers"), lambda o: 8 + o, 1.0),
    (("skeleton_king", "archers"), lambda o: 3 - o, 0.8),
    (("rage", "arrows"), lambda o: 10 + o, 0.6),
    (("elixir_golem", "archers"), lambda o: 9 - o, 0.8),
    (("skeletons", "archers"), lambda o: 5 - o, 0.6),
    (("archers", "skeletons"), lambda o: 7 - o, 0.6),
    (("arrows", "rage"), lambda o: 11 - o, 0.5),
    (("skeletons", "archers"), lambda o: 4 + o, 0.0),
)


def _run_sequence(delay, random_seed, line, steps):
    run_timed_card_sequence(delay, random_seed, line, steps)


def format2_elixir_golem_1x(delay, random_seed, line):
    _run_sequence(delay, random_seed, line, ELIXIR_GOLEM_1X)


def format2_elixir_golem_2x(delay, random_seed, line):
    _run_sequence(delay, random_seed, line, ELIXIR_GOLEM_2X)


def format2_elixir_golem_3x(delay, random_seed, line):
    _run_sequence(delay, random_seed, line, ELIXIR_GOLEM_3X)


if __name__ == "__main__":
    started_at = time.perf_counter()
    init5()
    cycle.show_all()
    changeCycle()
    cycle.show_all()
    format2_elixir_golem_1x(6, 0, 1)
    time.sleep(12)
    if time.perf_counter() - started_at < 90:
        format2_elixir_golem_1x(6, 1, 1)
        time.sleep(9)
    else:
        time.sleep(12)

    for i in range(4):
        time.sleep(2)
        format2_elixir_golem_2x(3, i, 1)

    for i in range(3):
        format2_elixir_golem_3x(2, i, 1)
