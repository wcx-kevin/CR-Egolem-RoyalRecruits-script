from pathlib import Path

from cr_bot.config.decks import get_deck_definition


PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = SRC_DIR.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
LEGACY_PROJECT_ROOT = WORKSPACE_ROOT / f"{PROJECT_ROOT.name} (original)" / PROJECT_ROOT.name
ASSETS_DIR = PROJECT_ROOT / "assets"
DECKS_DIR = ASSETS_DIR / "decks"
TMP_ROOT_DIR = PROJECT_ROOT / "tmp"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEBUG_OUTPUT_DIR = PROJECT_ROOT / "debug_output"


def get_active_deck_dir(deck_id=None):
    deck = get_deck_definition(deck_id)
    return DECKS_DIR / deck.id


def get_cards_dir(deck_id=None):
    return get_active_deck_dir(deck_id) / "cards"


def get_cards_full_dir(deck_id=None):
    return get_active_deck_dir(deck_id) / "cards_full"


def get_legacy_cards_dir(deck_id=None):
    deck = get_deck_definition(deck_id)
    if deck.id != "elixir_golem":
        return None
    return LEGACY_PROJECT_ROOT / "cards"


def get_legacy_oldcards_dir(deck_id=None):
    deck = get_deck_definition(deck_id)
    if deck.id != "elixir_golem":
        return None
    return LEGACY_PROJECT_ROOT / "oldcards"
