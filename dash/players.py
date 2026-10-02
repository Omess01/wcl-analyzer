"""Players tab: team strip (no names), roster table, and in named builds the Raid-lead rollups."""

from collections import Counter

from .common import esc, empty_state, table, kpis, section_note, avoidable_set, player_stats, player_cell
from .home import _delta
from .rollups import night_series, rollups_named


def _pct(x) -> str:
    return f"{x * 100:.0f}"


def team_strip(bosses: dict, pm_by_key: dict | None) -> str:
    """
    KPI tiles for the latest night vs the previous one, without names: flask + food compliance over player-pulls
    (rune separately), non-tank avoidable hits per minute alive, share of first deaths with no defensive, raid
    interrupts per pull. Empty string when there are no pulls.
    """
    series = night_series(bosses, pm_by_key)
    if not series:
        return ""
    cur = series[-1]
    prev = series[-2] if len(series) > 1 else None

    def before(field, sub=None):
        if prev is None:
            return None
        v = prev[field]
        if sub is not None:
            v = v[sub] if v else None
        return v

    tiles = [("Night", esc(cur["night"]), "text")]
    prep = cur["prep"]
    if prep:
        pb = before("prep", "ff")
        rune = f"<span class='vs'>rune on {_pct(prep['rune'])}%</span>" if prep.get("rune") is not None else ""
        tiles.append(("Flask + food at pull start", f"{_pct(prep['ff'])}%"
                      + _delta(prep["ff"] * 100, pb * 100 if pb is not None else None, lambda v: f"{v:.0f}", unit="%") + rune))
    if cur["avm"] is not None:
        pa = before("avm")
        tiles.append(("Avoidable hits / min alive (non-tanks)", f"{cur['avm']:.2f}"
                      + _delta(cur["avm"], pa, lambda v: f"{v:.2f}", lower_is_better=True)))
    if cur["nodef"] is not None:
        pn = before("nodef")
        tiles.append(("First deaths with no defensive", f"{_pct(cur['nodef'])}%"
                      + _delta(cur["nodef"] * 100, pn * 100 if pn is not None else None, lambda v: f"{v:.0f}",
                               lower_is_better=True, unit="%")))
    if cur["irpp"] is not None:
        pi = before("irpp")
        tiles.append(("Raid interrupts per pull", f"{cur['irpp']:.1f}" + _delta(cur["irpp"], pi, lambda v: f"{v:.1f}")))
    return ("<h2>Team</h2>"
            + section_note("The whole raid on the latest night, compared with the night before. No one is named here: "
                           "pick your name in the toolbar to see your card.")
            + kpis(tiles, "team-strip", raw=True))


def players_tab(bosses: dict, avoidable_cfg: dict, mode: str = "anonymous", players_block: dict | None = None,
                pm_by_key: dict | None = None, ordered: list | None = None) -> str:
    """
    Static Players tab. Public builds (mode != 'named'): team strip without names + roster sorted by name.
    Named builds: roster sorted by first-death rate + the 'Raid lead' rollups (dash/rollups.py).
    """
    named = mode == "named"
    if pm_by_key is None:
        from .payload import all_metrics
        pm_by_key = all_metrics(bosses, avoidable_cfg)
    combined: dict[str, dict] = {}
    any_avoidable = False
    for (name, diff), pulls in bosses.items():
        avoidable = avoidable_set(avoidable_cfg, name)
        any_avoidable = any_avoidable or bool(avoidable)
        for player, s in player_stats(pulls, avoidable).items():
            c = combined.setdefault(player, {"class": s["class"], "pulls": 0, "first_deaths": 0, "avoid_hits": 0,
                                             "causes": Counter(), "boss_set": set()})
            c["pulls"] += s["pulls"]
            c["first_deaths"] += s["first_deaths"]
            c["avoid_hits"] += s["avoid_hits"]
            c["causes"].update(s["causes"])
            if s["pulls"]:
                c["boss_set"].add((name, diff))
    for c in combined.values():
        c["bosses"] = len(c.pop("boss_set"))

    raid_lead = ""
    if named:
        if players_block is None:
            from .payload import players_data
            players_block = players_data(bosses, ordered or list(bosses.items()), avoidable_cfg, pm_by_key, True)
        raid_lead = rollups_named(bosses, ordered or list(bosses.items()), players_block, pm_by_key, avoidable_cfg)
    order_note = ("sorted by how often they started the wipe" if named else "sorted by name")
    return f"""
    <h1>Players <span class='diff'>all bosses</span></h1>
    {team_strip(bosses, pm_by_key)}
    <h2>Roster</h2>
    <p class='muted'>Roster-wide view across every pull in the selection, {order_note}. Players with few pulls are hidden by
    default. Click a name below (or pick a player in the toolbar) for their card and per-boss breakdown, or use <code>--player Name</code> to rebuild the whole dashboard for one person's pulls.</p>
    {player_table_lowpart(combined, any_avoidable, named)}
    {raid_lead}
    """


def player_table_lowpart(stats: dict, show_avoidable: bool, by_first_death: bool = True) -> str:
    """Players tab table with low-participation rows tagged for hiding. Rows by first-death rate (named builds) or by
    name, then most pulls (public builds)."""
    if not stats:
        return empty_state("players", "no boss pulls in this selection")
    max_pulls = max(s["pulls"] for s in stats.values()) or 1
    hidden = sum(1 for s in stats.values() if s["pulls"] < 0.25 * max_pulls)
    rows = ""
    if by_first_death:
        order = sorted(stats.items(), key=lambda kv: -(kv[1]["first_deaths"] / max(kv[1]["pulls"], 1)))
    else:
        order = sorted(stats.items(), key=lambda kv: (kv[0].lower(), -kv[1]["pulls"]))
    for name, s in order:
        n = max(s["pulls"], 1)
        rate = s["first_deaths"] / n
        cause = ", ".join(f"{a} ({c})" for a, c in s["causes"].most_common(2)) if s["causes"] else "-"
        low = " class='lowpart'" if s["pulls"] < 0.25 * max_pulls else ""
        avoid_col = f"<td data-sort='{s['avoid_hits'] / n:.2f}'>{s['avoid_hits'] / n:.1f}</td>" if show_avoidable else ""
        # data-player: dash.js's click-your-name handler (tr[data-player] .player) sets the toolbar Player filter
        rows += (
            f"<tr{low} data-player='{esc(name)}'><td>{player_cell(name, s['class'])}</td><td>{s['pulls']}</td>"
            f"<td>{s['bosses']}</td><td>{s['first_deaths']}</td><td data-sort='{rate:.3f}'>{rate * 100:.0f}%</td>"
            f"{avoid_col}<td>{esc(cause)}</td></tr>"
        )
    headers = [("Player", "str"), ("Pulls", "num"), ("Bosses", "num"),
               ("First death", "num"), ("Started the wipe in % of pulls", "num")]
    if show_avoidable:
        headers.append(("Avoidable hits / pull", "num"))
    headers.append(("What killed them", "str"))
    label = (f"<label class='filter'><input type='checkbox' class='showLow'> Show {hidden} hidden player{'s' if hidden != 1 else ''} "
             f"with under 25% participation</label>") if hidden else ""
    return label + table(headers, rows, caption="Players across all bosses")
