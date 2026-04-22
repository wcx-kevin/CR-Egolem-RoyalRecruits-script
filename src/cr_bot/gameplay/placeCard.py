import os
import subprocess
import threading
import time

import cv2
import numpy as np
import uiautomator2 as u2

from cr_bot.config.device_config import ADB_EXE, DEVICE_ID
from cr_bot.core.comCycle import CRCardCycle
from cr_bot.gameplay.card_tracker import get_recognizer, reconcile_after_play, verify_cycle
from cr_bot.gameplay.resource_state import (
    can_afford_ability,
    create_resource_event_id,
    finalize_spend,
    get_resource_snapshot,
    reserve_ability_cost,
    reserve_card_cost,
)


def _connect_device():
    try:
        return u2.connect(DEVICE_ID)
    except Exception:
        if ":" in DEVICE_ID:
            try:
                subprocess.run([ADB_EXE, "connect", DEVICE_ID], capture_output=True, timeout=10, check=False)
            except Exception:
                pass
        return u2.connect(DEVICE_ID)


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


cycle = CRCardCycle()
d = None

cards_x = [455, 720, 975, 1250]
cards_y = [2273, 2450, 2273, 2273]
places_x = [680, 754, 154, 1304, 680, 754, 680, 754, 346, 1085, 520, 900]
places_y = [1926, 1926, 1890, 1890, 1487, 1487, 1158, 1158, 1164, 1164, 725, 725]
HAND_CARD_MIN_CONFIDENCE = 0.31
NEXT_CARD_MIN_CONFIDENCE = 0.28
CLICK_INTERVAL = 0.08
CHAMPION_ABILITY_POLL_INTERVAL = 0.25
# Heuristic timing windows. Override the button coordinates via env if the HUD differs.
CHAMPION_ABILITY_WINDOWS = {
    "golden_knight": (0.9, 6.0),
    "skeleton_king": (2.2, 10.5),
}
CHAMPION_ABILITY_COSTS = {
    "golden_knight": 1,
    "skeleton_king": 1,
}
PENDING_CHAMPION_ABILITIES = {}
CHAMPION_STATE_LOCK = threading.RLock()


def _read_int_env(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)


CHAMPION_ABILITY_ENABLED = os.getenv("CR_ENABLE_CHAMPION_ABILITY", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
# Heuristic defaults for the current emulator layout.
CHAMPION_ABILITY_X = _read_int_env("CR_CHAMPION_ABILITY_X", 1300)
CHAMPION_ABILITY_Y = _read_int_env("CR_CHAMPION_ABILITY_Y", 1950)
CHAMPION_ABILITY_RADIUS = _read_int_env("CR_CHAMPION_ABILITY_RADIUS", 100)
CHAMPION_ABILITY_READY_SCORE = float(os.getenv("CR_CHAMPION_READY_SCORE", "0.24"))
CHAMPION_ABILITY_READY_WARM_RATIO = float(os.getenv("CR_CHAMPION_READY_WARM_RATIO", "0.14"))
CHAMPION_ABILITY_CHECK_INTERVAL = float(os.getenv("CR_CHAMPION_CHECK_INTERVAL", "0.20"))
CHAMPION_ABILITY_FORCE_CAST_WINDOW = float(os.getenv("CR_CHAMPION_FORCE_CAST_WINDOW", "1.00"))
CHAMPION_ABILITY_CAST_COOLDOWN = float(os.getenv("CR_CHAMPION_CAST_COOLDOWN", "0.45"))
CHAMPION_ABILITY_VERIFY_RETRIES = max(1, _read_int_env("CR_CHAMPION_VERIFY_RETRIES", 4))
CHAMPION_ABILITY_VERIFY_INTERVAL = float(os.getenv("CR_CHAMPION_VERIFY_INTERVAL", "0.12"))
CHAMPION_ABILITY_VERIFY_SCORE_DROP = float(os.getenv("CR_CHAMPION_VERIFY_SCORE_DROP", "0.015"))
ELIXIR_CAP_BREAK_THRESHOLD = float(os.getenv("CR_ELIXIR_CAP_BREAK_THRESHOLD", "9.4"))
ELIXIR_CAP_BREAK_MIN_REMAINING = float(os.getenv("CR_ELIXIR_CAP_BREAK_MIN_REMAINING", "0.9"))
ELIXIR_CAP_BREAK_ENABLED = os.getenv("CR_ELIXIR_CAP_BREAK_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


def _get_recognizer():
    return get_recognizer()


def _resolve_available_card_position(card_name):
    matches = cycle.find_card(card_name, [])
    for match in matches:
        if match["type"] == "available" and 1 <= match["position"] <= 4:
            return match["position"]
    return None


def _capture_runtime_screenshot():
    recognizer = _get_recognizer()
    if recognizer is None:
        return None
    try:
        return recognizer.adb_screenshot()
    except Exception:
        return None


def _sample_ability_button_signal(screenshot=None):
    screenshot = _capture_runtime_screenshot() if screenshot is None else screenshot
    if screenshot is None or screenshot.size == 0:
        return {
            "ready": False,
            "score": 0.0,
            "warm_ratio": 0.0,
            "edge_ratio": 0.0,
            "contrast": 0.0,
            "reason": "screenshot_failed",
        }

    radius = max(20, CHAMPION_ABILITY_RADIUS)
    x1 = max(0, CHAMPION_ABILITY_X - radius)
    x2 = min(screenshot.shape[1], CHAMPION_ABILITY_X + radius)
    y1 = max(0, CHAMPION_ABILITY_Y - radius)
    y2 = min(screenshot.shape[0], CHAMPION_ABILITY_Y + radius)
    if x2 <= x1 or y2 <= y1:
        return {
            "ready": False,
            "score": 0.0,
            "warm_ratio": 0.0,
            "edge_ratio": 0.0,
            "contrast": 0.0,
            "reason": "button_region_out_of_bounds",
        }

    crop = screenshot[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    warm_mask = (
        (hsv[:, :, 0] >= 5)
        & (hsv[:, :, 0] <= 35)
        & (hsv[:, :, 1] >= 90)
        & (hsv[:, :, 2] >= 110)
    )
    warm_ratio = float(np.count_nonzero(warm_mask)) / float(warm_mask.size)

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)

    height, width = gray.shape[:2]
    yy, xx = np.ogrid[:height, :width]
    center_x = width / 2.0
    center_y = height / 2.0
    distance = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
    center_mask = distance <= (min(width, height) * 0.28)
    border_mask = (distance >= (min(width, height) * 0.40)) & (distance <= (min(width, height) * 0.48))
    center_mean = float(gray[center_mask].mean()) if np.any(center_mask) else 0.0
    border_mean = float(gray[border_mask].mean()) if np.any(border_mask) else 0.0
    contrast = max(0.0, (center_mean - border_mean) / 255.0)

    score = (1.25 * warm_ratio) + (0.75 * edge_ratio) + contrast
    ready = warm_ratio >= CHAMPION_ABILITY_READY_WARM_RATIO and score >= CHAMPION_ABILITY_READY_SCORE
    return {
        "ready": ready,
        "score": score,
        "warm_ratio": warm_ratio,
        "edge_ratio": edge_ratio,
        "contrast": contrast,
        "reason": "ready" if ready else "button_not_ready",
    }


def _locate_ability_button(screenshot=None):
    screenshot = _capture_runtime_screenshot() if screenshot is None else screenshot
    if screenshot is None or screenshot.size == 0:
        return None

    height, width = screenshot.shape[:2]
    x1 = max(0, int(width * 0.70))
    x2 = min(width, int(width * 0.98))
    y1 = max(0, int(height * 0.64))
    y2 = min(height, int(height * 0.90))
    region = screenshot[y1:y2, x1:x2]
    if region.size == 0:
        return None

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    warm_mask = (
        (hsv[:, :, 0] >= 5)
        & (hsv[:, :, 0] <= 35)
        & (hsv[:, :, 1] >= 95)
        & (hsv[:, :, 2] >= 110)
    ).astype(np.uint8) * 255
    warm_mask = cv2.morphologyEx(warm_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    warm_mask = cv2.morphologyEx(warm_mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    contours, _ = cv2.findContours(warm_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_center = None
    best_score = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 1200:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = w / float(max(1, h))
        if not 0.55 <= aspect_ratio <= 1.65:
            continue

        center_x = x + (w // 2) + x1
        center_y = y + (h // 2) + y1
        contour_score = area / float(max(1, w * h))
        if contour_score > best_score:
            best_score = contour_score
            best_center = (center_x, center_y)

    return best_center


def _tap_card_and_place(card_position, place_positon):
    if not (1 <= card_position <= 4):
        return False
    if not (0 <= place_positon < len(places_x)):
        return False

    _safe_click(cards_x[card_position - 1], cards_y[card_position - 1])
    time.sleep(CLICK_INTERVAL)
    _safe_click(places_x[place_positon], places_y[place_positon])
    time.sleep(CLICK_INTERVAL)
    return True


def known(position):
    return cycle.get_card(position) != "Unknown"


def _apply_card_observation(position, card_name, confidence, unknown_only=False):
    internal_position = 5 if position == "next" else position
    min_confidence = NEXT_CARD_MIN_CONFIDENCE if position == "next" else HAND_CARD_MIN_CONFIDENCE

    if unknown_only and cycle.get_card(internal_position) != "Unknown":
        return False

    if card_name == "Unknown" or confidence < min_confidence:
        return False

    return cycle.set_card(internal_position, card_name, confidence)


def refresh_cycle_from_screen(unknown_only=False, include_next=True):
    return verify_cycle(force=True, unknown_only=unknown_only, include_next=include_next)


def reset_champion_abilities():
    with CHAMPION_STATE_LOCK:
        PENDING_CHAMPION_ABILITIES.clear()


def _record_champion_play(card_name):
    timing = CHAMPION_ABILITY_WINDOWS.get(card_name)
    if timing is None:
        return

    ready_delay, expire_delay = timing
    now = time.monotonic()
    with CHAMPION_STATE_LOCK:
        PENDING_CHAMPION_ABILITIES[card_name] = {
            "ready_at": now + ready_delay,
            "expires_at": now + expire_delay,
            "last_check_at": 0.0,
            "last_attempt_at": 0.0,
            "last_reason": "hero_detected",
            "ready_logged": False,
            "compensation_used": False,
            "casted": False,
        }
    print(
        f"hero detected: hero={card_name}, "
        f"skill_window={ready_delay:.2f}-{expire_delay:.2f}s, "
        f"ability_cost={CHAMPION_ABILITY_COSTS.get(card_name, 0)}"
    )


def trigger_champion_ability(card_name, reason="ready", pre_signal=None):
    if not CHAMPION_ABILITY_ENABLED:
        print(f"skill cast failed: hero={card_name}, reason=ability_disabled")
        return False

    if not can_afford_ability(card_name):
        snapshot = get_resource_snapshot()
        print(
            f"skill cast failed: hero={card_name}, reason=insufficient_elixir, "
            f"current={snapshot.current_elixir:.2f}"
        )
        return False

    event_id = create_resource_event_id("ability", card_name)
    reservation = reserve_ability_cost(card_name, event_id=event_id)
    if not reservation.allowed:
        print(
            f"skill cast failed: hero={card_name}, reason={reservation.reason}, "
            f"current={reservation.current_elixir:.2f}"
        )
        return False

    print(
        f"skill cast triggered: hero={card_name}, reason={reason}, "
        f"cost={reservation.cost:.2f}, remaining={reservation.current_elixir:.2f}"
    )

    def _ability_consumed(signal):
        if not signal["ready"]:
            return True
        if pre_signal is None:
            return False
        pre_score = float(pre_signal.get("score", 0.0))
        return signal["score"] <= max(0.0, pre_score - CHAMPION_ABILITY_VERIFY_SCORE_DROP)

    def _wait_for_ability_consumed():
        last_signal = _sample_ability_button_signal()
        for attempt in range(CHAMPION_ABILITY_VERIFY_RETRIES):
            if _ability_consumed(last_signal):
                return True, last_signal
            if attempt + 1 < CHAMPION_ABILITY_VERIFY_RETRIES:
                time.sleep(CHAMPION_ABILITY_VERIFY_INTERVAL)
                last_signal = _sample_ability_button_signal()
        return False, last_signal

    try:
        target = _locate_ability_button()
        if target is None:
            target = (CHAMPION_ABILITY_X, CHAMPION_ABILITY_Y)
        _safe_click(target[0], target[1])
        time.sleep(CLICK_INTERVAL)
    except Exception as exc:
        finalize_spend(event_id, False, f"skill_click_error:{exc.__class__.__name__}")
        print(f"skill cast failed: hero={card_name}, reason=click_error:{exc.__class__.__name__}")
        return False

    cast_confirmed, post_signal = _wait_for_ability_consumed()
    if not cast_confirmed:
        retry_target = _locate_ability_button()
        if retry_target is None:
            retry_target = target
        try:
            _safe_click(retry_target[0], retry_target[1])
            time.sleep(CLICK_INTERVAL)
        except Exception as exc:
            finalize_spend(event_id, False, f"skill_retry_click_error:{exc.__class__.__name__}")
            print(f"skill cast failed: hero={card_name}, reason=retry_click_error:{exc.__class__.__name__}")
            return False
        cast_confirmed, post_signal = _wait_for_ability_consumed()

    if not cast_confirmed:
        pre_score = 0.0 if pre_signal is None else float(pre_signal.get("score", 0.0))
        finalize_spend(event_id, False, "skill_button_still_ready")
        print(
            f"skill cast failed: hero={card_name}, reason=button_still_ready, "
            f"pre_score={pre_score:.3f}, post_score={post_signal['score']:.3f}"
        )
        return False

    finalize_spend(event_id, True, f"skill_cast:{reason}")
    if post_signal["ready"]:
        print(
            f"skill cast success: hero={card_name}, verify=unconfirmed, "
            f"score={post_signal['score']:.3f}"
        )
    else:
        print(
            f"skill cast success: hero={card_name}, verify={post_signal['reason']}, "
            f"score={post_signal['score']:.3f}"
        )
    return True


def maybe_trigger_champion_abilities(force_compensation=False):
    with CHAMPION_STATE_LOCK:
        if not PENDING_CHAMPION_ABILITIES:
            return ()

        now = time.monotonic()
        triggered_cards = []
        for card_name, state in list(PENDING_CHAMPION_ABILITIES.items()):
            if state.get("casted"):
                PENDING_CHAMPION_ABILITIES.pop(card_name, None)
                continue

            if now > state["expires_at"]:
                print(f"skill cast failed: hero={card_name}, reason=window_expired")
                PENDING_CHAMPION_ABILITIES.pop(card_name, None)
                continue

            if now < state["ready_at"]:
                continue

            if (now - state["last_check_at"]) < CHAMPION_ABILITY_CHECK_INTERVAL and not force_compensation:
                continue
            state["last_check_at"] = now

            signal = _sample_ability_button_signal()
            expires_soon = (state["expires_at"] - now) <= CHAMPION_ABILITY_FORCE_CAST_WINDOW

            if signal["ready"] and not state["ready_logged"]:
                print(
                    f"skill ready: hero={card_name}, score={signal['score']:.3f}, "
                    f"warm_ratio={signal['warm_ratio']:.3f}"
                )
                state["ready_logged"] = True

            trigger_reason = None
            if signal["ready"]:
                trigger_reason = "button_ready"
            elif force_compensation or (expires_soon and not state["compensation_used"]):
                trigger_reason = "compensation_window"
                state["compensation_used"] = True

            if trigger_reason is None:
                blocked_reason = signal["reason"]
                if blocked_reason != state["last_reason"]:
                    print(
                        f"skill cast failed: hero={card_name}, reason={blocked_reason}, "
                        f"score={signal['score']:.3f}"
                    )
                    state["last_reason"] = blocked_reason
                continue

            if (now - state["last_attempt_at"]) < CHAMPION_ABILITY_CAST_COOLDOWN:
                continue

            state["last_attempt_at"] = now
            if trigger_champion_ability(card_name, reason=trigger_reason, pre_signal=signal):
                state["casted"] = True
                triggered_cards.append(card_name)
                PENDING_CHAMPION_ABILITIES.pop(card_name, None)
                continue

            state["last_reason"] = trigger_reason

        return tuple(triggered_cards)


def sleep_with_runtime_checks(delay, poll_interval=CHAMPION_ABILITY_POLL_INTERVAL):
    remaining = max(0.0, float(delay))
    while remaining > 0:
        should_force_compensation = remaining <= CHAMPION_ABILITY_FORCE_CAST_WINDOW
        maybe_trigger_champion_abilities(force_compensation=should_force_compensation)
        snapshot = get_resource_snapshot()
        if (
            ELIXIR_CAP_BREAK_ENABLED
            and remaining > ELIXIR_CAP_BREAK_MIN_REMAINING
            and snapshot.current_elixir >= ELIXIR_CAP_BREAK_THRESHOLD
        ):
            print(
                f"runtime wait shortened due to elixir cap pressure: "
                f"elixir={snapshot.current_elixir:.2f}, remaining={remaining:.2f}"
            )
            break
        interval = min(poll_interval, remaining)
        time.sleep(interval)
        remaining -= interval
    maybe_trigger_champion_abilities(force_compensation=True)
    get_resource_snapshot()


def placeCardN(card_name, place_positon, remove=False, allow_refresh=True):
    maybe_trigger_champion_abilities()
    card_position = _resolve_available_card_position(card_name)
    if card_position is None and allow_refresh:
        verify_cycle(force=True, unknown_only=False, include_next=True)
        card_position = _resolve_available_card_position(card_name)
        if card_position is None:
            print(f"Unable to find an available hand card: {card_name}")
            return False
    elif card_position is None:
        return False

    spend_event_id = create_resource_event_id("card", card_name)
    reservation = reserve_card_cost(card_name, event_id=spend_event_id)
    if not reservation.allowed:
        print(
            f"Skipping card play due to elixir guard: card={card_name}, "
            f"reason={reservation.reason}, current={reservation.current_elixir:.2f}"
        )
        return False

    if not _tap_card_and_place(card_position, place_positon):
        finalize_spend(spend_event_id, False, "tap_failed")
        print(
            "Failed to tap the hand card or placement point: "
            f"card={card_name}, position={card_position}, place={place_positon}"
        )
        return False

    if not reconcile_after_play(card_position, remove=remove, expected_card_name=card_name):
        finalize_spend(spend_event_id, False, "play_not_confirmed")
        print(f"Card play was not confirmed and has been rolled back: card={card_name}, position={card_position}")
        return False
    finalize_spend(spend_event_id, True, "play_confirmed")

    _record_champion_play(card_name)
    return True


def placeCardP(card_position, place_positon):
    maybe_trigger_champion_abilities()
    card_name = cycle.get_card(card_position)
    if card_name in {None, "Unknown"}:
        print(f"Unable to resolve card slot before placing: card_position={card_position}")
        return False
    spend_event_id = create_resource_event_id("card", card_name)
    reservation = reserve_card_cost(card_name, event_id=spend_event_id)
    if not reservation.allowed:
        print(
            f"Skipping card slot play due to elixir guard: card={card_name}, "
            f"reason={reservation.reason}, current={reservation.current_elixir:.2f}"
        )
        return False

    if not _tap_card_and_place(card_position, place_positon):
        finalize_spend(spend_event_id, False, "tap_failed")
        print(f"Unable to tap the requested card slot: card_position={card_position}, place={place_positon}")
        return False

    if not reconcile_after_play(card_position, remove=False, expected_card_name=card_name):
        finalize_spend(spend_event_id, False, "play_not_confirmed")
        print(f"Card slot play was not confirmed and has been rolled back: card={card_name}, position={card_position}")
        return False
    finalize_spend(spend_event_id, True, "play_confirmed")

    _record_champion_play(card_name)
    return True


def placeCardOptions(card_names, place_positon, remove=False):
    for card_name in card_names:
        if _resolve_available_card_position(card_name) is not None:
            if placeCardN(card_name, place_positon, remove=remove, allow_refresh=False):
                return card_name

    verify_cycle(force=True, unknown_only=True, include_next=True)
    for card_name in card_names:
        if placeCardN(card_name, place_positon, remove=remove, allow_refresh=False):
            return card_name
    return None


if __name__ == "__main__":
    placeCardP(2, 4)
