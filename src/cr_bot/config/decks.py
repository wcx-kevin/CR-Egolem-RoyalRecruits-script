from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_DECK_ID = "elixir_golem"
DECK_ENV_VAR = "CR_DECK"


@dataclass(frozen=True)
class DeckDefinition:
    id: str
    display_name: str
    strategy: str
    card_template_groups: dict[str, tuple[str, ...]]
    card_costs: dict[str, int]
    description: str = ""


def _deck_key(value):
    if value is None:
        return ""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


DECKS = {
    "elixir_golem": DeckDefinition(
        id="elixir_golem",
        display_name="Elixir Golem",
        strategy="elixir_golem_autoplay",
        description="Elixir Golem autoplay deck.",
        card_template_groups={
            "archers": ("archers", "archers_evil", "archer"),
            "arrows": ("arrows",),
            "elixir_golem": ("elixir_golem", "egolem", "e_golem", "e-golem"),
            "goblin_machine": ("goblin_machine", "gmachine", "grobot"),
            "night_witch": ("night_witch", "nwitch"),
            "rage": ("rage",),
            "skeleton_king": ("skeleton_king", "ksk"),
            "skeletons": ("skeletons", "skeletons_evil", "sk"),
        },
        card_costs={
            "archers": 3,
            "arrows": 3,
            "elixir_golem": 3,
            "goblin_machine": 5,
            "night_witch": 4,
            "rage": 2,
            "skeleton_king": 4,
            "skeletons": 1,
        },
    ),
    "royal_recruits": DeckDefinition(
        id="royal_recruits",
        display_name="Royal Recruits",
        strategy="royal_recruits_autoplay",
        description="Royal Recruits autoplay deck with a minimal placement routine.",
        card_template_groups={
            "arrows": ("arrows",),
            "barbarian_barrel": ("barbarian_barrel",),
            "flying_machine": ("flying_machine",),
            "goblin_cage": ("goblin_cage",),
            "golden_knight": ("golden_knight",),
            "royal_hogs": ("royal_hogs", "royal_hogs_evil"),
            "royal_recruits": ("royal_recruits", "royal_recruits_evil"),
            "zappies": ("zappies",),
        },
        card_costs={
            "arrows": 3,
            "barbarian_barrel": 2,
            "flying_machine": 4,
            "goblin_cage": 4,
            "golden_knight": 4,
            "royal_hogs": 5,
            "royal_recruits": 7,
            "zappies": 4,
        },
    ),
}


DECK_ALIASES = {
    _deck_key("elixir_golem"): "elixir_golem",
    _deck_key("e_golem"): "elixir_golem",
    _deck_key("e-golem"): "elixir_golem",
    _deck_key("egolem"): "elixir_golem",
    _deck_key("royal_recruits"): "royal_recruits",
    _deck_key("royalrecruits"): "royal_recruits",
    _deck_key("rr"): "royal_recruits",
}


def normalize_deck_id(value, default=DEFAULT_DECK_ID):
    if value is None:
        return default

    normalized = DECK_ALIASES.get(_deck_key(value))
    if normalized is None:
        raise ValueError(
            f"Unsupported deck '{value}'. Available decks: {', '.join(sorted(DECKS))}"
        )
    return normalized


def get_active_deck_id():
    return normalize_deck_id(os.getenv(DECK_ENV_VAR), default=DEFAULT_DECK_ID)


def set_active_deck(value):
    normalized = normalize_deck_id(value)
    os.environ[DECK_ENV_VAR] = normalized
    return normalized


def get_deck_definition(deck_id=None):
    normalized = normalize_deck_id(deck_id, default=get_active_deck_id())
    return DECKS[normalized]


def list_decks():
    return tuple(DECKS.values())
