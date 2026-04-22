from cr_bot.core.card_config import get_card_pool, normalize_card_name


class CRCardCycle:
    """Singleton tracker for the visible and queued card cycle."""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, initial_available=None, initial_unavailable=None):
        if CRCardCycle._initialized:
            self.refresh_card_pool()
            return

        self.default_cards = ["Unknown"] * 8
        self.available = self.default_cards[:4]
        self.unavailable = self.default_cards[4:]
        self.confidences_available = [0.0] * 4
        self.confidences_unavailable = [0.0] * 4
        self.removed_card = None
        self.removed_confidence = 0.0
        self.card_pool = get_card_pool()
        self.clear_all(initial_available=initial_available, initial_unavailable=initial_unavailable)
        CRCardCycle._initialized = True

    def refresh_card_pool(self):
        self.card_pool = get_card_pool()

    def find_card(self, card_name, not_found_value=None):
        card_name = normalize_card_name(card_name)
        positions = []

        for index, card in enumerate(self.available, start=1):
            if card == card_name:
                positions.append({"type": "available", "position": index})

        for index, card in enumerate(self.unavailable, start=5):
            if card == card_name:
                positions.append({"type": "unavailable", "position": index})

        if self.removed_card == card_name:
            positions.append({"type": "removed", "position": "removed"})

        return positions if positions else not_found_value

    def use_card(self, position, remove_from_cycle=False):
        if not 1 <= position <= 4:
            print(f"Invalid hand position: {position}")
            return False

        used_card = self.available[position - 1]
        used_confidence = self.confidences_available[position - 1]
        print(f"Using card from slot {position}: {used_card} ({used_confidence:.2f})")

        if remove_from_cycle:
            if self.removed_card is not None:
                print("A card is already marked as removed from the cycle.")
                return False
            self.removed_card = used_card
            self.removed_confidence = used_confidence
        else:
            self.unavailable.append(used_card)
            self.confidences_unavailable.append(used_confidence)

        if self.unavailable:
            new_card = self.unavailable.pop(0)
            new_confidence = self.confidences_unavailable.pop(0)
            self.available[position - 1] = new_card
            self.confidences_available[position - 1] = new_confidence
        else:
            self.available[position - 1] = "Unknown"
            self.confidences_available[position - 1] = 0.0

        return True

    def return_removed_card(self):
        if self.removed_card is None:
            print("No removed card is waiting to be returned.")
            return False

        self.unavailable.append(self.removed_card)
        self.confidences_unavailable.append(self.removed_confidence)
        self.removed_card = None
        self.removed_confidence = 0.0
        return True

    def set_card(self, position, card_name, confidence=1.0, guess=False):
        card_name = normalize_card_name(card_name)
        if not 1 <= position <= 8:
            print(f"Invalid cycle position: {position}")
            return False

        old_unknown_count = self._count_unknown_cards()
        infer_after_update = bool(guess)

        if card_name != "Unknown":
            for existing in self.find_card(card_name, []) or []:
                existing_position = self._convert_position_to_internal(existing["type"], existing["position"])
                if existing_position == position:
                    continue
                infer_after_update = True
                existing_confidence = self.get_confidence(existing["type"], existing["position"])
                if confidence < existing_confidence:
                    result = self._set_card_internal(position, "Unknown", 0.0)
                    self._infer_unknown_card(old_unknown_count)
                    return result

                self._set_position_unknown(existing["type"], existing["position"])

        updated = self._set_card_internal(position, card_name, confidence)
        if updated and infer_after_update:
            self._infer_unknown_card(old_unknown_count)
        return updated

    def _set_position_unknown(self, pos_type, position):
        if pos_type == "available":
            self._set_card_internal(position, "Unknown", 0.0)
        elif pos_type == "unavailable":
            self._set_card_internal(position, "Unknown", 0.0)
        elif pos_type == "removed":
            self.removed_card = "Unknown"
            self.removed_confidence = 0.0

    def _set_card_internal(self, position, card_name, confidence):
        if 1 <= position <= 4:
            old_card = self.available[position - 1]
            old_confidence = self.confidences_available[position - 1]
            if old_card == card_name and abs(old_confidence - confidence) < 1e-6:
                return False
            self.available[position - 1] = card_name
            self.confidences_available[position - 1] = confidence
            return True

        index = position - 5
        if index >= len(self.unavailable):
            print(f"Invalid unavailable position: {position}")
            return False

        old_card = self.unavailable[index]
        old_confidence = self.confidences_unavailable[index]
        if old_card == card_name and abs(old_confidence - confidence) < 1e-6:
            return False
        self.unavailable[index] = card_name
        self.confidences_unavailable[index] = confidence
        return True

    def _count_unknown_cards(self):
        count = sum(1 for card in self.available if card == "Unknown")
        count += sum(1 for card in self.unavailable if card == "Unknown")
        if self.removed_card == "Unknown":
            count += 1
        return count

    def _infer_unknown_card(self, old_unknown_count):
        current_unknown_count = self._count_unknown_cards()
        if current_unknown_count != 1 and not (old_unknown_count > 1 and current_unknown_count == 1):
            return

        known_cards = {card for card in self.available if card != "Unknown"}
        known_cards.update(card for card in self.unavailable if card != "Unknown")
        if self.removed_card not in {None, "Unknown"}:
            known_cards.add(self.removed_card)

        missing_cards = [card for card in self.card_pool if card not in known_cards]
        if len(missing_cards) != 1:
            return

        inferred_card = missing_cards[0]
        for index, card in enumerate(self.available, start=1):
            if card == "Unknown":
                self._set_card_internal(index, inferred_card, 1.0)
                return

        for index, card in enumerate(self.unavailable, start=5):
            if card == "Unknown":
                self._set_card_internal(index, inferred_card, 1.0)
                return

        if self.removed_card == "Unknown":
            self.removed_card = inferred_card
            self.removed_confidence = 1.0

    def get_confidence(self, pos_type, position):
        if pos_type == "available" and 1 <= position <= 4:
            return self.confidences_available[position - 1]
        if pos_type == "unavailable" and 5 <= position <= 8:
            return self.confidences_unavailable[position - 5]
        if pos_type == "removed":
            return self.removed_confidence
        return 0.0

    def _convert_position_to_internal(self, pos_type, position):
        if pos_type == "available":
            return position
        if pos_type == "unavailable":
            return position
        return -1

    def get_card(self, position):
        if not 1 <= position <= 8:
            return None
        if position <= 4:
            return self.available[position - 1]
        return self.unavailable[position - 5]

    def show_all(self):
        print("\n=== Current Card Cycle ===")
        print("Available:")
        for index, (card, confidence) in enumerate(zip(self.available, self.confidences_available), start=1):
            print(f"  slot {index}: {card} ({confidence:.2f})")
        print("Unavailable:")
        for index, (card, confidence) in enumerate(zip(self.unavailable, self.confidences_unavailable), start=5):
            print(f"  slot {index}: {card} ({confidence:.2f})")
        if self.removed_card is not None:
            print(f"Removed: {self.removed_card} ({self.removed_confidence:.2f})")
        print("==========================\n")

    def get_cycle_state(self):
        return {
            "available": self.available.copy(),
            "unavailable": self.unavailable.copy(),
            "confidences_available": self.confidences_available.copy(),
            "confidences_unavailable": self.confidences_unavailable.copy(),
            "removed_card": self.removed_card,
            "removed_confidence": self.removed_confidence,
        }

    def set_cycle_state(self, state):
        if "available" not in state or "unavailable" not in state:
            print("Invalid cycle state payload.")
            return False

        self.refresh_card_pool()
        self.available = state["available"].copy()
        self.unavailable = state["unavailable"].copy()
        self.confidences_available = state.get("confidences_available", [0.0] * 4).copy()
        self.confidences_unavailable = state.get("confidences_unavailable", [0.0] * 4).copy()
        self.removed_card = state.get("removed_card")
        self.removed_confidence = state.get("removed_confidence", 0.0)
        return True

    def clear_all(self, initial_available=None, initial_unavailable=None):
        self.refresh_card_pool()
        self.available = initial_available.copy() if initial_available is not None else self.default_cards[:4]
        self.unavailable = initial_unavailable.copy() if initial_unavailable is not None else self.default_cards[4:]
        self.confidences_available = [0.0] * 4
        self.confidences_unavailable = [0.0] * 4
        self.removed_card = None
        self.removed_confidence = 0.0
