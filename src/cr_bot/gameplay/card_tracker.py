import time

from cr_bot.config.device_config import DEVICE_ID
from cr_bot.core.card_config import normalize_card_name
from cr_bot.core.comCycle import CRCardCycle
from cr_bot.recognition.finalGetCards import CRCardRecognizer


HAND_CARD_MIN_CONFIDENCE = 0.31
NEXT_CARD_MIN_CONFIDENCE = 0.28

BOOTSTRAP_RECOGNITION_DELAY = 0.18
BOOTSTRAP_MIN_KNOWN = 4
BOOTSTRAP_ATTEMPTS = 3
BOOTSTRAP_CONFIRM_REQUIRED = 1
BOOTSTRAP_INTERVAL = 0.1

UNKNOWN_VERIFY_INTERVAL = 0.8
PERIODIC_VERIFY_INTERVAL = 4.0
POST_PLAY_VERIFY_DELAY = 0.18
POST_PLAY_VERIFY_RETRIES = 3
POST_PLAY_VERIFY_INTERVAL = 0.14
MISMATCH_CONFIRM_REQUIRED = 1
OVERRIDE_CONFIDENCE_FLOOR = 0.52
OVERRIDE_CONFIDENCE_GAP = 0.04


class CardCycleTracker:
    def __init__(self, device_id=None):
        self.device_id = device_id or DEVICE_ID
        self.cycle = CRCardCycle()
        self.recognizer = CRCardRecognizer(
            self.device_id,
            vote_frames=2,
            vote_interval=0.04,
            unknown_retry_attempts=1,
            unknown_retry_interval=0.12,
        )
        self.bootstrap_ready = False
        self.last_full_verify_at = 0.0
        self.last_unknown_verify_at = 0.0
        self.mismatch_streaks = {}

    def reset_for_battle(self):
        self.cycle.clear_all()
        self.bootstrap_ready = False
        self.last_full_verify_at = 0.0
        self.last_unknown_verify_at = 0.0
        self.mismatch_streaks.clear()

    def _to_internal_position(self, position):
        return 5 if position == "next" else position

    def _position_min_confidence(self, position):
        return NEXT_CARD_MIN_CONFIDENCE if position == "next" else HAND_CARD_MIN_CONFIDENCE

    def _get_internal_confidence(self, internal_position):
        if 1 <= internal_position <= 4:
            return self.cycle.confidences_available[internal_position - 1]
        if 5 <= internal_position <= 8:
            return self.cycle.confidences_unavailable[internal_position - 5]
        return 0.0

    def _count_known_visible_cards(self, include_next=True):
        positions = [1, 2, 3, 4]
        if include_next:
            positions.append(5)
        return sum(1 for position in positions if self.cycle.get_card(position) != "Unknown")

    def _count_unknown_visible_cards(self, include_next=True):
        positions = [1, 2, 3, 4]
        if include_next:
            positions.append(5)
        return sum(1 for position in positions if self.cycle.get_card(position) == "Unknown")

    def _capture_visible_cards(self):
        return self.recognizer.get_all_cards()

    def _get_observation_at_position(self, observations, position):
        for card in observations or ():
            if card.get("position") == position:
                return card
        return None

    def _is_confident_visible_observation(self, position, observation):
        if not observation:
            return False
        confidence = float(observation.get("confidence", 0.0))
        return observation.get("name") != "Unknown" and confidence >= self._position_min_confidence(position)

    def _play_visibly_confirmed(self, card_position, expected_card_name, previous_next_name, observations):
        expected_card_name = normalize_card_name(expected_card_name)
        card_observation = self._get_observation_at_position(observations, card_position)
        next_observation = self._get_observation_at_position(observations, "next")

        slot_changed = self._is_confident_visible_observation(card_position, card_observation) and (
            normalize_card_name(card_observation["name"]) != expected_card_name
        )
        next_changed = (
            previous_next_name != "Unknown"
            and self._is_confident_visible_observation("next", next_observation)
            and normalize_card_name(next_observation["name"]) != normalize_card_name(previous_next_name)
        )

        expected_still_visible = False
        for observation in observations or ():
            position = observation.get("position")
            if position not in {1, 2, 3, 4, "next"}:
                continue
            if not self._is_confident_visible_observation(position, observation):
                continue
            if normalize_card_name(observation["name"]) == expected_card_name:
                expected_still_visible = True
                break

        return slot_changed or next_changed or not expected_still_visible

    def _note_mismatch(self, internal_position, observed_name):
        previous = self.mismatch_streaks.get(internal_position)
        if previous is not None and previous[0] == observed_name:
            count = previous[1] + 1
        else:
            count = 1
        self.mismatch_streaks[internal_position] = (observed_name, count)
        return count

    def _clear_mismatch(self, internal_position):
        self.mismatch_streaks.pop(internal_position, None)

    def _apply_single_observation(self, position, card_name, confidence, unknown_only=False, allow_override=True):
        internal_position = self._to_internal_position(position)
        min_confidence = self._position_min_confidence(position)
        current_name = self.cycle.get_card(internal_position)

        if card_name == "Unknown" or confidence < min_confidence:
            self._clear_mismatch(internal_position)
            return False

        if unknown_only and current_name != "Unknown":
            if current_name == card_name:
                self._clear_mismatch(internal_position)
            return False

        if current_name == card_name:
            self._clear_mismatch(internal_position)
            return self.cycle.set_card(internal_position, card_name, confidence)

        if current_name == "Unknown":
            self._clear_mismatch(internal_position)
            return self.cycle.set_card(internal_position, card_name, confidence)

        if not allow_override:
            self._note_mismatch(internal_position, card_name)
            return False

        mismatch_count = self._note_mismatch(internal_position, card_name)
        current_confidence = self._get_internal_confidence(internal_position)
        strong_override = confidence >= OVERRIDE_CONFIDENCE_FLOOR and confidence >= (current_confidence + OVERRIDE_CONFIDENCE_GAP)
        if mismatch_count >= MISMATCH_CONFIRM_REQUIRED or strong_override:
            self._clear_mismatch(internal_position)
            return self.cycle.set_card(internal_position, card_name, confidence)

        return False

    def _apply_visible_observations(self, observations, unknown_only=False, include_next=True, allow_override=True):
        updates = 0
        for card in observations:
            position = card["position"]
            if position == "next" and not include_next:
                continue
            if self._apply_single_observation(
                position,
                card["name"],
                card["confidence"],
                unknown_only=unknown_only,
                allow_override=allow_override,
            ):
                updates += 1
        return updates

    def bootstrap_visible_cycle(self):
        time.sleep(BOOTSTRAP_RECOGNITION_DELAY)

        best_observation = None
        best_known = 0
        stable_signature = None
        stable_hits = 0

        for attempt in range(BOOTSTRAP_ATTEMPTS):
            observations = self._capture_visible_cards()
            if observations:
                known_count = sum(1 for item in observations if item["name"] != "Unknown")
                if known_count > best_known:
                    best_known = known_count
                    best_observation = observations

                if known_count >= BOOTSTRAP_MIN_KNOWN:
                    signature = tuple((item["position"], item["name"]) for item in observations)
                    if signature == stable_signature:
                        stable_hits += 1
                    else:
                        stable_signature = signature
                        stable_hits = 1

                    if stable_hits >= BOOTSTRAP_CONFIRM_REQUIRED:
                        self._apply_visible_observations(observations, unknown_only=False, include_next=True, allow_override=True)
                        self.bootstrap_ready = self._count_known_visible_cards(include_next=True) >= BOOTSTRAP_MIN_KNOWN
                        self.last_full_verify_at = time.monotonic()
                        return self.bootstrap_ready

            if attempt + 1 < BOOTSTRAP_ATTEMPTS:
                time.sleep(BOOTSTRAP_INTERVAL)

        if best_observation is not None:
            self._apply_visible_observations(best_observation, unknown_only=False, include_next=True, allow_override=True)
            self.bootstrap_ready = self._count_known_visible_cards(include_next=True) >= BOOTSTRAP_MIN_KNOWN
            if self.bootstrap_ready:
                self.last_full_verify_at = time.monotonic()

        return self.bootstrap_ready

    def verify_visible_cycle(self, force=False, unknown_only=False, include_next=True):
        if not self.bootstrap_ready:
            return int(self.bootstrap_visible_cycle())

        if unknown_only and self._count_unknown_visible_cards(include_next=include_next) == 0:
            return 0

        now = time.monotonic()
        if not force:
            last_verify_at = self.last_unknown_verify_at if unknown_only else self.last_full_verify_at
            interval = UNKNOWN_VERIFY_INTERVAL if unknown_only else PERIODIC_VERIFY_INTERVAL
            if (now - last_verify_at) < interval:
                return 0

        observations = self._capture_visible_cards()
        if not observations:
            return 0

        updates = self._apply_visible_observations(
            observations,
            unknown_only=unknown_only,
            include_next=include_next,
            allow_override=True,
        )

        if unknown_only:
            self.last_unknown_verify_at = now
        else:
            self.last_full_verify_at = now

        return updates

    def verify_positions(self, positions, delay=0.0, allow_full_fallback=True):
        positions = list(dict.fromkeys(positions))
        if not positions:
            return 0

        if delay > 0:
            time.sleep(delay)

        updates = 0
        for position in positions:
            result = self.recognizer.get_card_at_position(position, retry_unknown=False)
            if self._apply_single_observation(
                result["position"],
                result["name"],
                result["confidence"],
                unknown_only=True,
                allow_override=False,
            ):
                updates += 1

        if updates == 0 and allow_full_fallback:
            updates += self.verify_visible_cycle(force=True, unknown_only=True, include_next=True)

        return updates

    def reconcile_after_play(self, card_position, remove=False, expected_card_name=None):
        expected_card_name = normalize_card_name(expected_card_name or self.cycle.get_card(card_position))
        previous_next_name = self.cycle.get_card(5)

        confirmed_observations = None
        for attempt in range(POST_PLAY_VERIFY_RETRIES):
            delay = POST_PLAY_VERIFY_DELAY if attempt == 0 else POST_PLAY_VERIFY_INTERVAL
            if delay > 0:
                time.sleep(delay)

            observations = self._capture_visible_cards()
            if not observations:
                continue
            if self._play_visibly_confirmed(card_position, expected_card_name, previous_next_name, observations):
                confirmed_observations = observations
                break

        if confirmed_observations is None:
            self.verify_visible_cycle(force=True, unknown_only=False, include_next=True)
            slot_name = self.cycle.get_card(card_position)
            next_name = self.cycle.get_card(5)
            if slot_name == expected_card_name and (
                previous_next_name == "Unknown" or next_name == previous_next_name
            ):
                print(
                    f"Play was not confirmed from visible cards: "
                    f"slot={card_position}, card={expected_card_name}"
                )
                return False
            confirmed_observations = self._capture_visible_cards()

        if not self.cycle.use_card(card_position, remove):
            return False

        if confirmed_observations:
            self._apply_visible_observations(
                confirmed_observations,
                unknown_only=False,
                include_next=True,
                allow_override=True,
            )

        positions_to_verify = []
        if self.cycle.get_card(card_position) == "Unknown":
            positions_to_verify.append(card_position)
        if self.cycle.get_card(5) == "Unknown":
            positions_to_verify.append("next")

        self.verify_positions(positions_to_verify, delay=POST_PLAY_VERIFY_DELAY, allow_full_fallback=bool(positions_to_verify))
        self.verify_visible_cycle(force=False, unknown_only=False, include_next=True)
        return True


cycle = CRCardCycle()
tracker = None


def _get_tracker():
    global tracker
    if tracker is None:
        tracker = CardCycleTracker(DEVICE_ID)
    return tracker


def get_recognizer():
    return _get_tracker().recognizer


def reset_runtime_tracker():
    global tracker
    if tracker is None:
        cycle.clear_all()
        return
    tracker.reset_for_battle()


def bootstrap_cycle():
    return _get_tracker().bootstrap_visible_cycle()


def verify_cycle(force=False, unknown_only=False, include_next=True):
    return _get_tracker().verify_visible_cycle(force=force, unknown_only=unknown_only, include_next=include_next)


def verify_positions(positions, delay=0.0, allow_full_fallback=True):
    return _get_tracker().verify_positions(positions, delay=delay, allow_full_fallback=allow_full_fallback)


def reconcile_after_play(card_position, remove=False, expected_card_name=None):
    return _get_tracker().reconcile_after_play(
        card_position,
        remove=remove,
        expected_card_name=expected_card_name,
    )
