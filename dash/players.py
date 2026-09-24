"""Players tab: cross-boss first-death / avoidable view (the recruitment tool)."""

from collections import Counter

from .common import esc, table, avoidable_set, player_stats


def players_tab(bosses: dict, avoidable_cfg: dict) -> str:
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

    return f"""
    <h1>Players <span class='diff'>all bosses</span></h1>
    <p class='muted'>Roster-wide view across every pull in the selection. Players with few pulls are hidden by
    default. Pick a player in the toolbar for their per-boss breakdown, or use <code>--player Name</code> to rebuild the whole dashboard for one person's pulls.</p>
    {player_table_lowpart(combined, any_avoidable)}
    """


def player_table_lowpart(stats: dict, show_avoidable: bool) -> str:
    """Players tab table with low-participation rows tagged for hiding."""
    if not stats:
        return "<p class='muted'>No data.</p>"
    max_pulls = max(s["pulls"] for s in stats.values()) or 1
    hidden = sum(1 for s in stats.values() if s["pulls"] < 0.25 * max_pulls)
    rows = ""
    for name, s in sorted(stats.items(), key=lambda kv: -(kv[1]["first_deaths"] / max(kv[1]["pulls"], 1))):
        n = max(s["pulls"], 1)
        rate = s["first_deaths"] / n
        cause = ", ".join(f"{a} ({c})" for a, c in s["causes"].most_common(2)) if s["causes"] else "-"
        low = " class='lowpart'" if s["pulls"] < 0.25 * max_pulls else ""
        avoid_col = f"<td data-sort='{s['avoid_hits'] / n:.2f}'>{s['avoid_hits'] / n:.1f}</td>" if show_avoidable else ""
        rows += (
            f"<tr{low}><td class='{esc(s['class'])}'>{esc(name)}</td><td>{esc(s['class'])}</td><td>{s['pulls']}</td>"
            f"<td>{s['bosses']}</td><td>{s['first_deaths']}</td><td data-sort='{rate:.3f}'>{rate * 100:.0f}%</td>"
            f"{avoid_col}<td>{esc(cause)}</td></tr>"
        )
    headers = [("Player", "str"), ("Class", "str"), ("Pulls", "num"), ("Bosses", "num"),
               ("First death", "num"), ("Started the wipe in % of pulls", "num")]
    if show_avoidable:
        headers.append(("Avoidable hits / pull", "num"))
    headers.append(("What killed them", "str"))
    label = (f"<label class='filter'><input type='checkbox' class='showLow'> Show {hidden} hidden player{'s' if hidden != 1 else ''} "
             f"with under 25% participation</label>") if hidden else ""
    return label + table(headers, rows, caption="Players across all bosses")
