from cr_bot.config.decks import get_deck_definition


def card_key(name):
    if name is None:
        return ""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def get_card_template_groups(deck_id=None):
    return get_deck_definition(deck_id).card_template_groups.copy()


def get_card_pool(deck_id=None):
    return list(get_card_template_groups(deck_id).keys())


def get_card_aliases(deck_id=None):
    aliases = {}
    for canonical_name, template_aliases in get_card_template_groups(deck_id).items():
        aliases[card_key(canonical_name)] = canonical_name
        for alias in template_aliases:
            aliases[card_key(alias)] = canonical_name
    return aliases


def normalize_card_name(name, deck_id=None):
    if name is None:
        return name

    if name == "Unknown":
        return "Unknown"

    normalized = get_card_aliases(deck_id).get(card_key(name))
    return normalized if normalized is not None else name
