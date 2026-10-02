"""The one authoritative WoW spec table, keyed by WCL / Blizzard `specID` (game data, not configuration).

`spec_token` is the token WCL uses in table icons ("DemonHunter-Havoc" -> "Havoc", "Hunter-BeastMastery" ->
"BeastMastery"), so spec strings derived from a specID are byte-identical to the ones parsed from icons.
`class` is WCL's CamelCase class id ("DeathKnight", "DemonHunter").
Role sets for Python (dash/common.py) and the browser (dash/static/dash.js via the `cfg` JSON script) both come
from `role_sets()`, so they cannot drift. Tokens shared by two classes ("Holy", "Protection", "Restoration",
"Frost") always share a role, so token-based role lookup is unambiguous.
"""

# specID: (class, spec_token, role, simc_token, support)
SPECS: dict[int, tuple[str, str, str, str, bool]] = {
    250: ("DeathKnight", "Blood", "tank", "blood", False),
    251: ("DeathKnight", "Frost", "dps", "frost", False),
    252: ("DeathKnight", "Unholy", "dps", "unholy", False),
    577: ("DemonHunter", "Havoc", "dps", "havoc", False),
    581: ("DemonHunter", "Vengeance", "tank", "vengeance", False),
    # 1480 verified from real cache data: CombatantInfo specID 1480 always pairs with the table icon "DemonHunter-Devourer"
    1480: ("DemonHunter", "Devourer", "dps", "devourer", False),
    102: ("Druid", "Balance", "dps", "balance", False),
    103: ("Druid", "Feral", "dps", "feral", False),
    104: ("Druid", "Guardian", "tank", "guardian", False),
    105: ("Druid", "Restoration", "healer", "restoration", False),
    1467: ("Evoker", "Devastation", "dps", "devastation", False),
    1468: ("Evoker", "Preservation", "healer", "preservation", False),
    1473: ("Evoker", "Augmentation", "dps", "augmentation", True),
    253: ("Hunter", "BeastMastery", "dps", "beast_mastery", False),
    254: ("Hunter", "Marksmanship", "dps", "marksmanship", False),
    255: ("Hunter", "Survival", "dps", "survival", False),
    62: ("Mage", "Arcane", "dps", "arcane", False),
    63: ("Mage", "Fire", "dps", "fire", False),
    64: ("Mage", "Frost", "dps", "frost", False),
    268: ("Monk", "Brewmaster", "tank", "brewmaster", False),
    269: ("Monk", "Windwalker", "dps", "windwalker", False),
    270: ("Monk", "Mistweaver", "healer", "mistweaver", False),
    65: ("Paladin", "Holy", "healer", "holy", False),
    66: ("Paladin", "Protection", "tank", "protection", False),
    70: ("Paladin", "Retribution", "dps", "retribution", False),
    256: ("Priest", "Discipline", "healer", "discipline", False),
    257: ("Priest", "Holy", "healer", "holy", False),
    258: ("Priest", "Shadow", "dps", "shadow", False),
    259: ("Rogue", "Assassination", "dps", "assassination", False),
    260: ("Rogue", "Outlaw", "dps", "outlaw", False),
    261: ("Rogue", "Subtlety", "dps", "subtlety", False),
    262: ("Shaman", "Elemental", "dps", "elemental", False),
    263: ("Shaman", "Enhancement", "dps", "enhancement", False),
    264: ("Shaman", "Restoration", "healer", "restoration", False),
    265: ("Warlock", "Affliction", "dps", "affliction", False),
    266: ("Warlock", "Demonology", "dps", "demonology", False),
    267: ("Warlock", "Destruction", "dps", "destruction", False),
    71: ("Warrior", "Arms", "dps", "arms", False),
    72: ("Warrior", "Fury", "dps", "fury", False),
    73: ("Warrior", "Protection", "tank", "protection", False),
}


def spec_of(spec_id) -> tuple[str, str, str, bool] | None:
    """(class, spec_token, role, support) for a specID, or None when unknown / missing."""
    try:
        row = SPECS.get(int(spec_id))
    except (TypeError, ValueError):
        return None
    if row is None:
        return None
    cls, token, role, _simc, support = row
    return cls, token, role, support


def role_sets() -> dict[str, list[str]]:
    """{"tanks": [...], "healers": [...], "support": [...]} as sorted, de-duplicated spec tokens."""
    def tokens(pred):
        return sorted({tok for _c, tok, role, _s, sup in SPECS.values() if pred(role, sup)})
    return {
        "tanks": tokens(lambda role, sup: role == "tank"),
        "healers": tokens(lambda role, sup: role == "healer"),
        "support": tokens(lambda role, sup: sup),
    }


_ROLE_BY_TOKEN = {tok: role for _c, tok, role, _s, _sup in SPECS.values()}


def role_of_token(token: str) -> str:
    """'tank' | 'healer' | 'dps' for a spec token; unknown / empty tokens are 'dps'."""
    return _ROLE_BY_TOKEN.get(token, "dps")
