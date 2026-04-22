from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from cr_bot.config.decks import get_deck_definition
from cr_bot.core.card_config import normalize_card_name
from cr_bot.gameplay.battle_timing import normalize_elixir_stage


ELIXIR_MIN = 0.0
ELIXIR_MAX = 10.0
NORMAL_BATTLE_INITIAL_ELIXIR = 5.6
# Estimate: direct battle takes over an active match with unknown bar state, so bias high.
DIRECT_BATTLE_INITIAL_ELIXIR = 8.0
# Estimate: standard elixir regeneration intervals in seconds.
ELIXIR_REGEN_INTERVALS = {
    "single": 2.8,
    "double": 1.4,
    "triple": 0.93,
}
ELIXIR_STAGE_SOURCE_PRIORITY = {
    "fallback": 0,
    "runtime": 1,
    "manual": 2,
    "time_vision": 3,
}
ABILITY_COSTS = {
    "golden_knight": 1,
    "skeleton_king": 1,
}
# Estimate: when the played card is still Unknown, use a mid-range cost to avoid free spends.
UNKNOWN_CARD_COST_ESTIMATE = 4.0
ELIXIR_GUARD_TOLERANCE = 1.0
STALE_PENDING_SPEND_SECONDS = 20.0
SETTLED_EVENT_RETENTION_SECONDS = 120.0


@dataclass(frozen=True)
class SpendReservation:
    allowed: bool
    event_id: str
    cost: float
    current_elixir: float
    reason: str = ""


@dataclass(frozen=True)
class ResourceSnapshot:
    current_elixir: float
    max_elixir: float
    elixir_stage: str
    direct_battle: bool
    active_battle: bool
    pending_spends: int


class BattleResourceState:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if BattleResourceState._initialized:
            return

        self._lock = threading.RLock()
        self._event_serial = 0
        self._session_serial = 0
        self.current_elixir = ELIXIR_MAX
        self.max_elixir = ELIXIR_MAX
        self.elixir_stage = "single"
        self.elixir_stage_source = "fallback"
        self.direct_battle = False
        self.active_battle = False
        self.last_update_at = time.monotonic()
        self.pending_spends = {}
        self.settled_events = {}
        BattleResourceState._initialized = True

    def _log(self, message):
        print(f"[resource] {message}")

    def _next_event_id_locked(self, prefix, label):
        self._event_serial += 1
        return f"{prefix}:{self._session_serial}:{self._event_serial}:{label}"

    def _clamp_elixir_locked(self, value, reason):
        raw_value = float(value)
        clamped_value = min(self.max_elixir, max(ELIXIR_MIN, raw_value))
        if (
            raw_value < (ELIXIR_MIN - 0.05)
            or raw_value > (self.max_elixir + 0.05)
            or abs(raw_value - clamped_value) > 0.05
        ):
            self._log(
                f"corrected abnormal elixir value {raw_value:.2f} -> {clamped_value:.2f} ({reason})"
            )
        return clamped_value

    def _drop_stale_events_locked(self, now):
        for event_id, record in list(self.pending_spends.items()):
            if (now - record["created_at"]) < STALE_PENDING_SPEND_SECONDS:
                continue

            self.current_elixir = self._clamp_elixir_locked(
                self.current_elixir + record["cost"],
                f"stale_pending_refund:{event_id}",
            )
            self.pending_spends.pop(event_id, None)
            self.settled_events[event_id] = now
            self._log(
                f"refunded stale pending spend event={event_id} label={record['label']} cost={record['cost']:.2f}"
            )

        cutoff = now - SETTLED_EVENT_RETENTION_SECONDS
        for event_id, settled_at in list(self.settled_events.items()):
            if settled_at < cutoff:
                self.settled_events.pop(event_id, None)

    def _apply_regen_locked(self, now=None):
        now = time.monotonic() if now is None else float(now)
        self._drop_stale_events_locked(now)

        elapsed = max(0.0, now - self.last_update_at)
        self.last_update_at = now
        if not self.active_battle or elapsed <= 0:
            return

        regen_interval = ELIXIR_REGEN_INTERVALS.get(self.elixir_stage, ELIXIR_REGEN_INTERVALS["single"])
        regenerated = elapsed / regen_interval
        if regenerated <= 0:
            return

        self.current_elixir = self._clamp_elixir_locked(
            self.current_elixir + regenerated,
            f"regen:{self.elixir_stage}",
        )

    def _resolve_cost_locked(self, spend_type, label):
        normalized_label = normalize_card_name(label)
        if spend_type == "ability":
            return float(ABILITY_COSTS.get(normalized_label, 0.0))
        if normalized_label == "Unknown":
            return float(UNKNOWN_CARD_COST_ESTIMATE)
        deck = get_deck_definition()
        return float(deck.card_costs.get(normalized_label, 0.0))

    def _begin_spend_locked(self, spend_type, label, event_id=None):
        label = normalize_card_name(label)
        event_id = event_id or self._next_event_id_locked(spend_type, label)
        self._apply_regen_locked()

        if event_id in self.pending_spends:
            record = self.pending_spends[event_id]
            return SpendReservation(
                allowed=True,
                event_id=event_id,
                cost=record["cost"],
                current_elixir=self.current_elixir,
                reason="duplicate-pending",
            )

        if event_id in self.settled_events:
            return SpendReservation(
                allowed=False,
                event_id=event_id,
                cost=0.0,
                current_elixir=self.current_elixir,
                reason="duplicate-settled",
            )

        cost = self._resolve_cost_locked(spend_type, label)
        if cost <= 0:
            return SpendReservation(
                allowed=True,
                event_id=event_id,
                cost=0.0,
                current_elixir=self.current_elixir,
                reason="zero-cost",
            )

        if (self.current_elixir + ELIXIR_GUARD_TOLERANCE) < cost:
            return SpendReservation(
                allowed=False,
                event_id=event_id,
                cost=cost,
                current_elixir=self.current_elixir,
                reason=f"insufficient-elixir:{self.current_elixir:.2f}<{cost:.2f}",
            )

        self.current_elixir = self._clamp_elixir_locked(
            self.current_elixir - cost,
            f"reserve:{spend_type}:{label}",
        )
        self.pending_spends[event_id] = {
            "type": spend_type,
            "label": label,
            "cost": cost,
            "created_at": time.monotonic(),
        }
        return SpendReservation(
            allowed=True,
            event_id=event_id,
            cost=cost,
            current_elixir=self.current_elixir,
            reason="reserved",
        )

    def _finalize_spend_locked(self, event_id, success, reason):
        self._apply_regen_locked()
        record = self.pending_spends.pop(event_id, None)
        if record is None:
            if event_id in self.settled_events:
                return False
            self.settled_events[event_id] = time.monotonic()
            return False

        if not success:
            self.current_elixir = self._clamp_elixir_locked(
                self.current_elixir + record["cost"],
                f"refund:{event_id}:{reason}",
            )
            self._log(
                f"released spend event={event_id} label={record['label']} cost={record['cost']:.2f} reason={reason}"
            )
        else:
            self._log(
                f"committed spend event={event_id} label={record['label']} cost={record['cost']:.2f} reason={reason}"
            )

        self.settled_events[event_id] = time.monotonic()
        return True

    def reset_for_battle(
        self,
        direct_battle=False,
        elixir_stage=None,
        reason="battle_reset",
        initial_elixir=None,
        source="fallback",
    ):
        normalized_stage = normalize_elixir_stage(elixir_stage) or "single"
        with self._lock:
            self._session_serial += 1
            self.pending_spends.clear()
            self.settled_events.clear()
            self.direct_battle = bool(direct_battle)
            self.active_battle = True
            self.elixir_stage = normalized_stage
            self.elixir_stage_source = source if source in ELIXIR_STAGE_SOURCE_PRIORITY else "fallback"
            self.current_elixir = self._clamp_elixir_locked(
                DIRECT_BATTLE_INITIAL_ELIXIR if initial_elixir is None and direct_battle else (
                    NORMAL_BATTLE_INITIAL_ELIXIR if initial_elixir is None else initial_elixir
                ),
                f"reset_for_battle:{reason}",
            )
            self.last_update_at = time.monotonic()
            self._log(
                "battle reset: "
                f"deck={get_deck_definition().id}, direct_battle={self.direct_battle}, "
                f"stage={self.elixir_stage}, elixir={self.current_elixir:.2f}, reason={reason}"
            )

    def settle_battle(self, reason="battle_end"):
        with self._lock:
            self._apply_regen_locked()
            self.pending_spends.clear()
            self.settled_events.clear()
            self.active_battle = False
            self.direct_battle = False
            self.elixir_stage = "single"
            self.elixir_stage_source = "fallback"
            self.current_elixir = self._clamp_elixir_locked(ELIXIR_MAX, f"settle_battle:{reason}")
            self.last_update_at = time.monotonic()
            self._log(f"battle settled: elixir={self.current_elixir:.2f}, reason={reason}")

    def set_elixir_stage(self, elixir_stage, reason="stage_change", source="runtime"):
        normalized_stage = normalize_elixir_stage(elixir_stage) or "single"
        normalized_source = source if source in ELIXIR_STAGE_SOURCE_PRIORITY else "runtime"
        with self._lock:
            self._apply_regen_locked()
            current_priority = ELIXIR_STAGE_SOURCE_PRIORITY.get(self.elixir_stage_source, 0)
            incoming_priority = ELIXIR_STAGE_SOURCE_PRIORITY.get(normalized_source, 0)
            if self.elixir_stage == normalized_stage:
                self.elixir_stage_source = normalized_source if incoming_priority >= current_priority else self.elixir_stage_source
                return
            if incoming_priority < current_priority:
                self._log(
                    "ignored lower-priority elixir stage update "
                    f"{normalized_stage} from {normalized_source} because current source is {self.elixir_stage_source}"
                )
                return
            old_stage = self.elixir_stage
            self.elixir_stage = normalized_stage
            self.elixir_stage_source = normalized_source
            self._log(f"elixir stage changed: {old_stage} -> {normalized_stage} ({reason})")

    def reserve_card_cost(self, card_name, event_id=None):
        with self._lock:
            return self._begin_spend_locked("card", card_name, event_id=event_id)

    def reserve_ability_cost(self, card_name, event_id=None):
        with self._lock:
            return self._begin_spend_locked("ability", card_name, event_id=event_id)

    def finalize_spend(self, event_id, success, reason):
        with self._lock:
            return self._finalize_spend_locked(event_id, success, reason)

    def create_event_id(self, prefix, label):
        with self._lock:
            return self._next_event_id_locked(prefix, normalize_card_name(label))

    def can_afford_ability(self, card_name):
        with self._lock:
            self._apply_regen_locked()
            cost = self._resolve_cost_locked("ability", card_name)
            return (self.current_elixir + ELIXIR_GUARD_TOLERANCE) >= cost

    def get_snapshot(self):
        with self._lock:
            self._apply_regen_locked()
            return ResourceSnapshot(
                current_elixir=self.current_elixir,
                max_elixir=self.max_elixir,
                elixir_stage=self.elixir_stage,
                direct_battle=self.direct_battle,
                active_battle=self.active_battle,
                pending_spends=len(self.pending_spends),
            )


resources = BattleResourceState()


def reset_battle_resources(
    direct_battle=False,
    elixir_stage=None,
    reason="battle_reset",
    initial_elixir=None,
    source="fallback",
):
    resources.reset_for_battle(
        direct_battle=direct_battle,
        elixir_stage=elixir_stage,
        reason=reason,
        initial_elixir=initial_elixir,
        source=source,
    )


def settle_battle_resources(reason="battle_end"):
    resources.settle_battle(reason=reason)


def set_battle_elixir_stage(elixir_stage, reason="stage_change", source="runtime"):
    resources.set_elixir_stage(elixir_stage, reason=reason, source=source)


def reserve_card_cost(card_name, event_id=None):
    return resources.reserve_card_cost(card_name, event_id=event_id)


def reserve_ability_cost(card_name, event_id=None):
    return resources.reserve_ability_cost(card_name, event_id=event_id)


def finalize_spend(event_id, success, reason):
    return resources.finalize_spend(event_id, success, reason)


def create_resource_event_id(prefix, label):
    return resources.create_event_id(prefix, label)


def can_afford_ability(card_name):
    return resources.can_afford_ability(card_name)


def get_resource_snapshot():
    return resources.get_snapshot()
