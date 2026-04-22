import os
import subprocess
import threading
import time
from queue import Queue

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2
import numpy as np

from cr_bot.config.device_config import DEVICE_ID, adb_command
from cr_bot.gameplay.battle_timing import BattleTimeVision
from cr_bot.gameplay.resource_state import set_battle_elixir_stage
from cr_bot.paths import TEMPLATES_DIR

try:
    import uiautomator2 as u2
except ImportError:
    u2 = None


START_REGION = (2460, 2530, 280, 1400)
START_TARGET_COLOR_BGR = np.array([0xC9, 0x1E, 0xC3], dtype=np.int16)
START_COLOR_TOLERANCE = np.array([24, 24, 24], dtype=np.int16)


class GameStateDetector:
    """Detect match start and end states."""

    def __init__(self, device_id=None, debug=False, end_template_path=None, device=None, start_sample_step=4):
        self.device_id = device_id or DEVICE_ID
        self.debug = debug
        self.debug_dir = "debug_game_state"
        self.end_template_path = end_template_path or os.fspath(TEMPLATES_DIR / "game_end_template.png")
        self.device = device
        self.start_sample_step = max(1, int(start_sample_step))

        self.start_match_threshold = 0.26
        self.start_sustain_threshold = 0.10
        self.start_fast_match_threshold = 0.32
        self.start_poll_interval = 0.08
        self.end_poll_interval = 1.8
        self.start_confirm_required = 2
        self.end_confirm_required = 3
        self.end_missing_start_limit = 8
        self.end_fallback_min_elapsed = 90.0
        self.direct_battle_confirm_attempts = 5
        self.direct_battle_confirm_required = 2
        self.direct_battle_confirm_interval = 0.08

        self.game_started = False
        self.game_ended = False
        self.game_started_at = None
        self.running = False
        self.direct_battle_mode = False
        self.state_lock = threading.RLock()
        self.start_detection_thread = None
        self.end_detection_thread = None
        self.screenshot_queue = Queue(maxsize=1)
        self.start_confirm_count = 0
        self.end_confirm_count = 0
        self.end_missing_start_count = 0
        self.end_confirmation_active = False
        self.last_time_stage = None
        self.time_vision = BattleTimeVision(debug=debug)

        self.end_match_threshold = 0.42
        self.end_search_regions = [
            (500, 2050, 1040, 2400),
            (560, 2140, 940, 2360),
        ]

        if debug:
            os.makedirs(self.debug_dir, exist_ok=True)

        self.end_template_original = None
        self.end_template = None
        if self.end_template_path and os.path.exists(self.end_template_path):
            self.end_template_original = cv2.imread(self.end_template_path)
            if self.end_template_original is not None:
                self.end_template = cv2.cvtColor(self.end_template_original, cv2.COLOR_BGR2GRAY)

        if self.device is None and u2 is not None:
            try:
                self.device = u2.connect(self.device_id)
            except Exception as exc:
                if self.debug:
                    print(f"uiautomator2 screenshot unavailable, fallback to adb: {exc}")

    def take_screenshot(self):
        if self.device is not None:
            try:
                screenshot = self.device.screenshot(format="opencv")
                if screenshot is not None:
                    return screenshot
            except Exception as exc:
                if self.debug:
                    print(f"uiautomator2 screenshot failed, fallback to adb: {exc}")

        try:
            adb_cmd = adb_command("exec-out", "screencap", "-p", device_id=self.device_id)
            process = subprocess.run(
                adb_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                check=False,
            )
            if process.stderr:
                if self.debug:
                    print(f"adb screenshot stderr: {process.stderr.decode(errors='ignore')}")
                return None

            nparr = np.frombuffer(process.stdout, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as exc:
            if self.debug:
                print(f"adb screenshot exception: {exc}")
            return None

    def get_start_match_ratio(self, screenshot):
        if screenshot is None:
            return 0.0

        y1, y2, x1, x2 = START_REGION
        region = screenshot[y1:y2, x1:x2]
        if region.size == 0:
            return 0.0

        sampled_region = region[::self.start_sample_step, ::self.start_sample_step].astype(np.int16)
        color_diff = np.abs(sampled_region - START_TARGET_COLOR_BGR)
        match_mask = np.all(color_diff <= START_COLOR_TOLERANCE, axis=2)
        match_ratio = float(np.count_nonzero(match_mask)) / match_mask.size

        if self.debug:
            print(f"start match ratio={match_ratio:.4f}")

        return match_ratio

    def detect_game_start(self, screenshot, threshold=None):
        threshold = self.start_match_threshold if threshold is None else float(threshold)
        return self.get_start_match_ratio(screenshot) > threshold

    def detect_active_battle(self, screenshot):
        return self.detect_game_start(screenshot, threshold=self.start_sustain_threshold)

    def set_direct_battle_mode(self, enabled=True):
        self.direct_battle_mode = bool(enabled)

    def _battle_signal_state(self, ratio):
        if ratio >= self.start_match_threshold:
            return "battle"
        if ratio >= self.start_sustain_threshold:
            return "candidate"
        return "idle"

    def _set_battle_started(self, started_at=None):
        with self.state_lock:
            self.game_started = True
            self.game_ended = False
            self.game_started_at = time.time() if started_at is None else float(started_at)

    def _set_battle_ended(self):
        with self.state_lock:
            self.game_ended = True

    def mark_battle_active(self, started_at=None):
        self._set_battle_started(started_at=started_at)

    def reset_battle_flags(self):
        with self.state_lock:
            self.game_started = False
            self.game_ended = False
            self.game_started_at = None
            self.end_confirmation_active = False
            self.end_confirm_count = 0
            self.end_missing_start_count = 0
            self.last_time_stage = None
            self.time_vision = BattleTimeVision(debug=self.debug)

    def _sync_battle_timing(self, screenshot, battle_active=False, source="runtime"):
        reading = self.time_vision.observe(screenshot, battle_active=battle_active)
        if reading is None:
            return None

        if reading.confirmed and reading.stage is not None and reading.stage != self.last_time_stage:
            self.last_time_stage = reading.stage
            set_battle_elixir_stage(reading.stage, reason=f"{source}:{reading.reason}", source="time_vision")
            print(
                f"battle time vision confirmed: stage={reading.stage}, "
                f"text={reading.raw_text!r}, confidence={reading.confidence:.3f}, "
                f"anchor={reading.battle_anchor_score:.3f}, overtime={reading.overtime_score:.3f}"
            )
        return reading

    def wait_for_active_battle(self, timeout=2.5, label="active_battle"):
        started_at = time.perf_counter()
        confirm_count = 0
        last_state = None
        print(f"Waiting for active battle: label={label}, timeout={timeout:.1f}s")

        while (time.perf_counter() - started_at) < timeout:
            screenshot = self.take_screenshot()
            self._sync_battle_timing(screenshot, battle_active=False, source="direct_wait")
            ratio = self.get_start_match_ratio(screenshot)
            signal_state = self._battle_signal_state(ratio)
            elapsed = time.perf_counter() - started_at

            if signal_state != last_state:
                print(
                    f"battle wait state changed: label={label}, state={signal_state}, "
                    f"ratio={ratio:.4f}, elapsed={elapsed:.2f}s"
                )
                last_state = signal_state

            if ratio >= self.start_match_threshold:
                confirm_count += 1
                if confirm_count >= self.direct_battle_confirm_required:
                    print(
                        f"battle detected: label={label}, ratio={ratio:.4f}, "
                        f"stable_frames={confirm_count}, elapsed={elapsed:.2f}s"
                    )
                    return True
            elif ratio >= self.start_sustain_threshold:
                confirm_count += 1
                if confirm_count >= self.direct_battle_confirm_required:
                    print(
                        f"battle detected: label={label}, ratio={ratio:.4f}, "
                        f"mode=sustain, elapsed={elapsed:.2f}s"
                    )
                    return True
            else:
                confirm_count = 0

            remaining = timeout - (time.perf_counter() - started_at)
            if remaining <= 0:
                break
            time.sleep(min(self.direct_battle_confirm_interval, remaining))

        print(f"battle detection timeout: label={label}, elapsed={time.perf_counter() - started_at:.2f}s")
        return False

    def confirm_active_battle(self, attempts=None, interval=None):
        attempts = self.direct_battle_confirm_attempts if attempts is None else max(1, int(attempts))
        interval = self.direct_battle_confirm_interval if interval is None else max(0.0, float(interval))

        sustained_hits = 0
        best_ratio = 0.0
        for index in range(attempts):
            screenshot = self.take_screenshot()
            ratio = self.get_start_match_ratio(screenshot)
            best_ratio = max(best_ratio, ratio)

            if ratio >= self.start_match_threshold:
                return True
            if ratio >= self.start_sustain_threshold:
                sustained_hits += 1
                if sustained_hits >= self.direct_battle_confirm_required:
                    return True

            if index + 1 < attempts and interval > 0:
                time.sleep(interval)

        if self.debug:
            print(f"confirm_active_battle failed, best_ratio={best_ratio:.4f}, hits={sustained_hits}")
        return False

    def detect_game_end(self, screenshot):
        if screenshot is None:
            return False
        if self.end_template is None:
            return False

        gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        best_score = 0.0

        for x1, y1, x2, y2 in self.end_search_regions:
            region = gray_screenshot[y1:y2, x1:x2]
            if region.size == 0:
                continue

            for scale in (0.85, 0.95, 1.0, 1.05, 1.15, 1.25):
                resized_template = cv2.resize(
                    self.end_template,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_LINEAR,
                )
                template_h, template_w = resized_template.shape[:2]
                region_h, region_w = region.shape[:2]
                if template_h > region_h or template_w > region_w:
                    continue

                result = cv2.matchTemplate(region, resized_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                best_score = max(best_score, float(max_val))

        if self.debug:
            print(f"end template score={best_score:.4f}")

        return best_score > self.end_match_threshold

    def _push_latest_screenshot(self, screenshot):
        if self.screenshot_queue.full():
            try:
                self.screenshot_queue.get_nowait()
            except Exception:
                pass
        if screenshot is not None:
            self.screenshot_queue.put(screenshot)

    def start_detection_loop(self):
        print("开始检测线程启动")
        while self.running:
            if self.game_started:
                time.sleep(0.5)
                continue

            screenshot = self.take_screenshot()
            battle_active = self.game_started and not self.game_ended
            self._sync_battle_timing(screenshot, battle_active=battle_active, source="start_loop")
            self._push_latest_screenshot(screenshot)

            if self.detect_game_start(screenshot):
                self.start_confirm_count += 1
                if self.start_confirm_count >= self.start_confirm_required:
                    self.mark_battle_active(started_at=time.time())
                    self.start_confirm_count = 0
                    print(f"检测到游戏开始 ({time.strftime('%Y-%m-%d %H:%M:%S')})")
            else:
                self.start_confirm_count = 0

            time.sleep(self.start_poll_interval)

        print("开始检测线程启动")

    def end_detection_loop(self):
        print("结束检测线程启动")
        while self.running:
            screenshot = None
            if not self.screenshot_queue.empty():
                screenshot = self.screenshot_queue.get()
            if screenshot is None:
                screenshot = self.take_screenshot()

            if self.game_started and not self.game_ended:
                self._sync_battle_timing(screenshot, battle_active=True, source="end_loop")
                battle_visible = self.detect_active_battle(screenshot)
                if self.detect_game_end(screenshot):
                    if battle_visible:
                        if self.end_confirmation_active:
                            print("结束确认撤销，回到 battle 状态")
                        self.end_confirmation_active = False
                        self.end_confirm_count = 0
                        self.end_missing_start_count = 0
                        time.sleep(self.end_poll_interval)
                        continue
                    if not self.end_confirmation_active:
                        self.end_confirmation_active = True
                        self.end_confirm_count = 0
                        print("结束确认中")
                    self.end_confirm_count += 1
                    self.end_missing_start_count = 0
                    if self.end_confirm_count >= self.end_confirm_required:
                        self._set_battle_ended()
                        self.end_confirmation_active = False
                        self.end_confirm_count = 0
                        print(f"检测到游戏结束 ({time.strftime('%Y-%m-%d %H:%M:%S')})")
                elif self.end_confirmation_active:
                    if battle_visible:
                        print("结束确认撤销，回到 battle 状态")
                    self.end_confirmation_active = False
                    self.end_confirm_count = 0
                    self.end_missing_start_count = 0
                elif not self.direct_battle_mode and not battle_visible:
                    self.end_confirm_count = 0
                    if self.game_started_at is not None and (time.time() - self.game_started_at) >= self.end_fallback_min_elapsed:
                        self.end_missing_start_count += 1
                    else:
                        self.end_missing_start_count = 0
                    if self.end_missing_start_count >= self.end_missing_start_limit:
                        self._set_battle_ended()
                        print(f"检测到游戏结束(兜底判定) ({time.strftime('%Y-%m-%d %H:%M:%S')})")
                else:
                    self.end_confirm_count = 0
                    self.end_missing_start_count = 0

            time.sleep(self.end_poll_interval)

        print("结束检测线程停止")

    def start_detection(self):
        if self.running:
            print("检测已经在运行中")
            return

        self.running = True
        self.game_ended = False
        self.start_confirm_count = 0
        self.end_confirm_count = 0
        self.end_missing_start_count = 0

        self.start_detection_thread = threading.Thread(target=self.start_detection_loop, daemon=True)
        self.end_detection_thread = threading.Thread(target=self.end_detection_loop, daemon=True)
        self.start_detection_thread.start()
        self.end_detection_thread.start()
        print("游戏状态检测已启动")

    def stop_detection(self):
        if not self.running:
            return

        self.running = False

        if self.start_detection_thread:
            self.start_detection_thread.join(timeout=1.0)
        if self.end_detection_thread:
            self.end_detection_thread.join(timeout=1.0)

        print("游戏状态检测已停止")

    def wait_for_game_start(self, timeout=30):
        start_time = time.perf_counter()
        self.start_confirm_count = 0
        last_state = None
        print(f"wait for battle start: timeout={timeout:.1f}s")

        while time.perf_counter() - start_time < timeout:
            screenshot = self.take_screenshot()
            self._sync_battle_timing(screenshot, battle_active=False, source="wait_start")
            ratio = self.get_start_match_ratio(screenshot)
            signal_state = self._battle_signal_state(ratio)
            elapsed = time.perf_counter() - start_time

            if signal_state != last_state:
                print(
                    f"battle wait state changed: state={signal_state}, "
                    f"ratio={ratio:.4f}, elapsed={elapsed:.2f}s"
                )
                last_state = signal_state

            if ratio >= self.start_fast_match_threshold:
                self.mark_battle_active(started_at=time.time())
                self.start_confirm_count = 0
                print(f"battle detected: label=matchmaking, ratio={ratio:.4f}, elapsed={elapsed:.2f}s")
                return True

            if ratio >= self.start_match_threshold:
                self.start_confirm_count += 1
                if self.start_confirm_count >= self.start_confirm_required:
                    self.mark_battle_active(started_at=time.time())
                    self.start_confirm_count = 0
                    print(f"battle detected: label=matchmaking, ratio={ratio:.4f}, elapsed={elapsed:.2f}s")
                    return True
            elif ratio >= self.start_sustain_threshold:
                self.start_confirm_count = min(self.start_confirm_required - 1, self.start_confirm_count + 1)
            else:
                self.start_confirm_count = 0

            remaining = timeout - (time.perf_counter() - start_time)
            if remaining <= 0:
                break
            time.sleep(min(self.start_poll_interval, remaining))

        print(f"battle wait timeout: elapsed={time.perf_counter() - start_time:.2f}s")
        return False

    def wait_for_game_end(self, timeout=300):
        start_time = time.time()
        self.end_confirm_count = 0
        self.end_missing_start_count = 0

        while time.time() - start_time < timeout:
            screenshot = self.take_screenshot()
            self._sync_battle_timing(screenshot, battle_active=self.game_started and not self.game_ended, source="wait_end")
            battle_visible = self.detect_active_battle(screenshot)
            if self.detect_game_end(screenshot):
                if battle_visible:
                    if self.end_confirmation_active:
                        print("结束确认撤销，回到 battle 状态")
                    self.end_confirmation_active = False
                    self.end_confirm_count = 0
                    self.end_missing_start_count = 0
                    time.sleep(self.end_poll_interval)
                    continue
                if not self.end_confirmation_active:
                    self.end_confirmation_active = True
                    self.end_confirm_count = 0
                    print("结束确认中")
                self.end_confirm_count += 1
                if self.end_confirm_count >= self.end_confirm_required:
                    self._set_battle_ended()
                    self.end_confirmation_active = False
                    self.end_confirm_count = 0
                    return True
            elif self.end_confirmation_active:
                if battle_visible:
                    print("结束确认撤销，回到 battle 状态")
                self.end_confirmation_active = False
                self.end_confirm_count = 0
            elif not self.direct_battle_mode and not battle_visible:
                self.end_confirm_count = 0
                if self.game_started_at is not None and (time.time() - self.game_started_at) >= self.end_fallback_min_elapsed:
                    self.end_missing_start_count += 1
                else:
                    self.end_missing_start_count = 0
                if self.end_missing_start_count >= self.end_missing_start_limit:
                    self._set_battle_ended()
                    return True
            else:
                self.end_confirm_count = 0
                self.end_missing_start_count = 0

            time.sleep(self.end_poll_interval)

        return False


if __name__ == "__main__":
    template_path = os.fspath(TEMPLATES_DIR / "game_end_template.png")
    detector = GameStateDetector(
        device_id=DEVICE_ID,
        debug=True,
        end_template_path=template_path,
    )
    detector.start_detection()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("程序被用户中断")
    finally:
        detector.stop_detection()
