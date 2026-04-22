import argparse
import signal
import subprocess
import sys
import threading
import time

import uiautomator2

from cr_bot.config.decks import get_deck_definition
from cr_bot.config.device_config import ADB_EXE, DEVICE_ID
from cr_bot.core.comCycle import CRCardCycle
from cr_bot.gameplay.card_tracker import reset_runtime_tracker
from cr_bot.gameplay.battle_timing import read_direct_battle_selection
from cr_bot.gameplay.deck_runtime import run_selected_deck
from cr_bot.gameplay.placeCard import reset_champion_abilities
from cr_bot.gameplay.resource_state import reset_battle_resources, settle_battle_resources
from cr_bot.recognition.checkType import GameStateDetector


cycle = CRCardCycle()
d = None


def _connect_device():
    try:
        return uiautomator2.connect(DEVICE_ID)
    except Exception:
        if ":" in DEVICE_ID:
            try:
                subprocess.run([ADB_EXE, "connect", DEVICE_ID], capture_output=True, timeout=10, check=False)
            except Exception:
                pass
        return uiautomator2.connect(DEVICE_ID)


def _safe_click(x, y):
    global d
    try:
        if d is None:
            d = _connect_device()
        d.click(x, y)
        return
    except Exception:
        d = _connect_device()
        d.click(x, y)


class MainLoop:
    """Main loop for match flow."""

    def __init__(self, device_id=None):
        self.device_id = device_id or DEVICE_ID
        self.running = False
        self.game_detector = None
        self.op2_thread = None
        self.stop_op2_event = threading.Event()
        self.op2_finished = False
        self.direct_battle_mode = False

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        print(f"Received signal {signum}; stopping.")
        self.running = False
        self.stop_op2_event.set()
        if self.game_detector:
            self.game_detector.stop_detection()
        if self.op2_thread and self.op2_thread.is_alive():
            self.op2_thread.join(timeout=2.0)
        settle_battle_resources(reason=f"signal:{signum}")
        sys.exit(0)

    def _click_with_delay(self, x, y, repeats=1, interval=0.4):
        for _ in range(max(1, int(repeats))):
            _safe_click(x, y)
            time.sleep(interval)

    def operation_1(self):
        print("Operation 1: leave result screens and queue the next match.")
        time.sleep(2)

        self._click_with_delay(750, 2300, repeats=2, interval=1.0)
        time.sleep(2)
        self._click_with_delay(1100, 1500, repeats=2, interval=0.7)

        cycle.clear_all()
        reset_runtime_tracker()
        print("Cycle state has been reset.")

        self._click_with_delay(720, 2190, repeats=2, interval=0.9)

    def operation_2(self, stop_event):
        print("Operation 2: run in-battle routine.")
        try:
            run_selected_deck(stop_event, direct_battle=self.direct_battle_mode)
        finally:
            self.op2_finished = True
            print("Operation 2 thread ended.")

    def _reset_runtime_for_battle(self):
        cycle.clear_all()
        reset_runtime_tracker()
        reset_champion_abilities()
        direct_selection = read_direct_battle_selection() if self.direct_battle_mode else None
        reset_battle_resources(
            direct_battle=self.direct_battle_mode,
            elixir_stage=(direct_selection.start_elixir_stage if direct_selection is not None else "single"),
            reason="main_loop_battle_reset",
            source="manual" if self.direct_battle_mode else "runtime",
        )
        self.stop_op2_event.clear()
        self.op2_finished = False
        print("Battle runtime state has been reset.")

    def _run_battle_session(self, session_label, triggered_at=None):
        print(f"Starting battle session: {session_label}")
        self.game_detector.mark_battle_active(started_at=time.time())
        self.game_detector.start_detection()

        self.op2_thread = threading.Thread(target=self.operation_2, args=(self.stop_op2_event,))
        self.op2_thread.daemon = True
        self.op2_thread.start()
        if triggered_at is not None:
            print(f"battle entered: session={session_label}, elapsed={time.perf_counter() - triggered_at:.2f}s")

        print("Waiting for battle end...")
        wait_started_at = time.perf_counter()
        op2_finish_logged = False

        while self.running and not self.game_detector.game_ended:
            if self.op2_finished and not op2_finish_logged:
                print("Placement routine finished; still waiting for battle end.")
                op2_finish_logged = True

            if not self.direct_battle_mode and time.perf_counter() - wait_started_at > 240:
                print("Battle wait timed out; ending the current round.")
                break

            time.sleep(1)

        print("Round finished; stopping the in-battle thread.")
        self.stop_op2_event.set()
        self.game_detector.stop_detection()

        if self.op2_thread and self.op2_thread.is_alive():
            self.op2_thread.join(timeout=30.0)
            if self.op2_thread.is_alive():
                print("Operation 2 thread did not stop in time; aborting main loop.")
                self.running = False

        self.game_detector.reset_battle_flags()
        settle_battle_resources(reason=f"session_finished:{session_label}")

    def _enter_battle(self, session_label, detection_started_at):
        print(
            f"enter battle triggered: session={session_label}, "
            f"elapsed={time.perf_counter() - detection_started_at:.2f}s"
        )
        self._reset_runtime_for_battle()
        self._run_battle_session(session_label, triggered_at=detection_started_at)

    def run_direct_battle(self):
        self.running = True
        self.direct_battle_mode = True
        deck = get_deck_definition()
        print(f"Selected deck: {deck.display_name} ({deck.id})")
        print("Direct battle mode enabled.")
        print(f"Direct battle stage selection: {read_direct_battle_selection().describe()}")

        self.game_detector = GameStateDetector(
            device_id=self.device_id,
            debug=False,
        )
        self.game_detector.set_direct_battle_mode(True)

        print("Direct battle waiting mode active.")
        while self.running:
            detect_started_at = time.perf_counter()
            active_battle = self.game_detector.wait_for_active_battle(
                timeout=1.0,
                label="direct battle wait",
            )
            if not active_battle:
                continue

            self._enter_battle("direct battle", detect_started_at)
            if not self.running:
                break

        self.direct_battle_mode = False
        print("Direct battle mode ended.")

    def run(self):
        self.running = True
        self.direct_battle_mode = False
        deck = get_deck_definition()
        print(f"Selected deck: {deck.display_name} ({deck.id})")

        self.game_detector = GameStateDetector(
            device_id=self.device_id,
            debug=False,
        )
        self.game_detector.set_direct_battle_mode(False)

        while self.running:
            print("\n=== Start new loop ===")
            self.stop_op2_event.clear()
            self.op2_finished = False

            current_screenshot = self.game_detector.take_screenshot()
            if self.game_detector.detect_game_start(current_screenshot):
                print("A battle is already in progress; taking over the current battle.")
                self._enter_battle("take over current battle", time.perf_counter())
                time.sleep(2)
                continue

            self.operation_1()

            print("Waiting for battle start...")
            wait_started_at = time.perf_counter()
            if not self.game_detector.wait_for_game_start(timeout=18):
                print("Battle start timed out; retrying.")
                time.sleep(2)
                continue

            print(f"Battle started after {time.perf_counter() - wait_started_at:.2f}s.")
            self._enter_battle("newly started battle", wait_started_at)
            if not self.running:
                break
            time.sleep(3)

        print("Main loop ended.")


def build_parser():
    parser = argparse.ArgumentParser(description="Clash Royale battle loop")
    parser.add_argument("--device-id", default=DEVICE_ID, help="ADB/uiautomator2 device id")
    parser.add_argument(
        "--direct-battle",
        action="store_true",
        help="Directly take over the current battle and start placing cards without matchmaking waits.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    main_loop = MainLoop(device_id=args.device_id)
    try:
        if args.direct_battle:
            main_loop.run_direct_battle()
        else:
            main_loop.run()
    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        main_loop.running = False
        main_loop.stop_op2_event.set()
        settle_battle_resources(reason="main_finally")


if __name__ == "__main__":
    main()
