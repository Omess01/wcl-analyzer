"""
Live WCL probe (design doc P0.7): settles the [unverified] items of
docs/research/2026-09-25-player-analysis/04-wcl-api.md with one real call each
and measures the point cost (rateLimitData deltas) per request kind.

    python tools/wcl_probe.py [--report CODE --fight N] [--out FILE]

Without --report/--fight it picks the longest raid pull found in the cached
FIGHTS entries of data/cache/report_meta.json. It never uses cached_query and
never writes to data/cache (read-only use of cached entries). Player names are
redacted (P1, P2, ...) in everything it prints or writes.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cache                      # noqa: E402
import collect_data               # noqa: E402
import wcl_client                 # noqa: E402
from wcl_client import WCLError   # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "docs", "research", "2026-09-25-player-analysis", "06-live-probe.md")
FIXTURE_CODE = "3w1jJ8BZ2m9kMrYG"
RAID_DIFFS = {1, 3, 4, 5}
RL = " rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }"
CAST_FILTER = "source.type = 'player' AND type IN ('cast','begincast')"
KNOWN_SPECS = {250, 251, 252, 577, 581, 102, 103, 104, 105, 1467, 1468, 1473, 253, 254, 255, 62, 63, 64,
               268, 269, 270, 65, 66, 70, 256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266, 267, 71, 72, 73}


class StopProbe(RuntimeError):
    pass


# --------------------------------------------------------------------------
# HTTP recorder: wraps the client's session.post (no production code change)
# --------------------------------------------------------------------------

HTTP_LOG: list[dict] = []
_n429 = 0
_orig_post = wcl_client._session.post


def _recording_post(url, *a, **kw):
    global _n429
    t0 = time.time()
    resp = _orig_post(url, *a, **kw)
    hdr = {k: v for k, v in resp.headers.items()
           if k.lower() == "retry-after" or "ratelimit" in k.lower() or "rate-limit" in k.lower()}
    rl = None
    if url == wcl_client.GRAPHQL_URL and resp.status_code == 200:
        try:   # read rateLimitData from the raw body: the client may strip it from the returned data
            rl = ((resp.json() or {}).get("data") or {}).get("rateLimitData")
        except ValueError:
            pass
    HTTP_LOG.append({"url": url, "status": resp.status_code, "bytes": len(resp.content),
                     "seconds": round(time.time() - t0, 2), "rate_headers": hdr, "rl": rl})
    if resp.status_code == 429:
        _n429 += 1
        if _n429 >= 2:
            raise StopProbe(f"second HTTP 429 - stopping (headers: {hdr})")
    return resp


wcl_client._session.post = _recording_post


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

class Redactor:
    def __init__(self):
        self.map: dict[str, str] = {}

    def add(self, name):
        if isinstance(name, str) and len(name) >= 2 and name not in self.map:
            self.map[name] = f"P{len(self.map) + 1}"

    def _pattern(self):
        names = sorted(self.map, key=len, reverse=True)
        return re.compile("|".join(re.escape(n) for n in names)) if names else None

    def text(self, s: str) -> str:
        pat = self._pattern()
        return pat.sub(lambda m: self.map[m.group(0)], s) if pat else s

    def obj(self, o):
        if isinstance(o, dict):
            return {k: self.obj(v) for k, v in o.items()}
        if isinstance(o, list):
            return [self.obj(v) for v in o]
        if isinstance(o, str):
            return self.text(o)
        return o

    def leaks(self, s: str) -> list[str]:
        return [n for n in self.map if re.search(r"\b" + re.escape(n) + r"\b", s)]


RED = Redactor()


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------

def with_rl(query: str) -> str:
    q = query.rstrip()
    assert q.endswith("}"), "query must end with its closing brace"
    return q[:-1] + RL + " }"


class Probe:
    def __init__(self):
        self.calls: list[dict] = []
        self.last_spent = None

    def run(self, kind: str, query: str, variables: dict | None = None, note: str = ""):
        """Runs one query (+ rateLimitData). Returns data or None on WCLError."""
        n_http = len(HTTP_LOG)
        rec = {"kind": kind, "note": note, "error": None}
        t0 = time.time()
        try:
            data = wcl_client.run_query(with_rl(query), variables or {})
        except WCLError as exc:
            data = None
            rec["error"] = str(exc)[:300]
        rec["seconds"] = round(time.time() - t0, 2)
        http = HTTP_LOG[n_http:]
        rec["http_attempts"] = len(http)
        rec["bytes"] = http[-1]["bytes"] if http else 0
        rec["statuses"] = [h["status"] for h in http]
        rl = (data or {}).get("rateLimitData") or next((h["rl"] for h in reversed(http) if h.get("rl")), None)
        rec["rl"] = rl
        if rl:
            spent = rl["pointsSpentThisHour"]
            rec["delta"] = None if self.last_spent is None else round(spent - self.last_spent, 3)
            self.last_spent = spent
        else:
            rec["delta"] = None
        self.calls.append(rec)
        d = "?" if rec["delta"] is None else rec["delta"]
        print(f"  [{len(self.calls):2}] {kind:<28} {rec['bytes']:>9} B {rec['seconds']:>6.1f} s  "
              f"dpts={d}  {'ERR ' + rec['error'][:120] if rec['error'] else ''}")
        return data


def report_part(data):
    return ((data or {}).get("reportData") or {}).get("report") or {}


def shape(o, depth=0, max_depth=3):
    """Compact type sketch of a JSON value."""
    if isinstance(o, dict):
        if depth >= max_depth:
            return "{...}"
        return {k: shape(v, depth + 1, max_depth) for k, v in o.items()}
    if isinstance(o, list):
        if not o:
            return "[]"
        return [shape(o[0], depth + 1, max_depth), f"... x{len(o)}"]
    return type(o).__name__


def snippet(o, limit=2500) -> str:
    s = json.dumps(RED.obj(o), indent=1, ensure_ascii=False)
    if len(s) > limit:
        s = s[:limit] + "\n ... (truncated)"
    return s


def first_entries(o, n=1):
    """Shrinks lists to their first n entries, recursively."""
    if isinstance(o, dict):
        return {k: first_entries(v, n) for k, v in o.items()}
    if isinstance(o, list):
        return [first_entries(v, n) for v in o[:n]] + ([f"... {len(o) - n} more"] if len(o) > n else [])
    return o


def key_union(events) -> dict:
    out: dict[str, int] = {}
    for e in events:
        for k in e:
            out[k] = out.get(k, 0) + 1
    return out


# --------------------------------------------------------------------------
# Target selection from the cache (read-only)
# --------------------------------------------------------------------------

def cached_fights(code):
    p = cache._cache_path(collect_data.FIGHTS_QUERY, {"code": code})
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return report_part(json.load(f))


def pick_target(meta):
    best = None
    for code in meta:
        rep = cached_fights(code)
        if not rep:
            continue
        for f in rep.get("fights") or []:
            if f.get("encounterID") and f.get("difficulty") in RAID_DIFFS:
                length = f["endTime"] - f["startTime"]
                if best is None or length > best[0]:
                    best = (length, code, f["id"])
    if not best:
        raise SystemExit("no cached raid pull found; pass --report and --fight")
    return best[1], best[2]


def normal_candidates(meta, limit=3):
    """Newest small Normal-only nights in the cache (fixture replacement candidates)."""
    out = []
    for code, end in sorted(meta.items(), key=lambda kv: -kv[1]):
        rep = cached_fights(code)
        if not rep:
            continue
        boss = [f for f in rep.get("fights") or [] if f.get("encounterID") and f.get("difficulty") in RAID_DIFFS]
        if boss and all(f["difficulty"] == 3 for f in boss) and len(boss) <= 8:
            out.append({"code": code, "end": end, "pulls": len(boss), "kills": sum(1 for f in boss if f["kill"])})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def events_part(alias, fid, start, end, args, limit):
    return (f"{alias}: events(fightIDs: [{fid}], startTime: {int(start)}, endTime: {int(end)}, "
            f"{args}, limit: {limit}) {{ data nextPageTimestamp }}")


def follow(probe, kind, code, fid, start, end, args, limit, var_decl="", variables=None, max_pages=8):
    """Follows nextPageTimestamp; returns (events, pages, bytes, page_sizes)."""
    events, pages, total_bytes, sizes = [], 0, 0, []
    s = start
    while s is not None and pages < max_pages:
        q = (f"query P($code: String!{var_decl}) {{ reportData {{ report(code: $code) {{ "
             + events_part("ev", fid, s, end, args, limit) + " } } }")
        data = probe.run(kind if pages == 0 else f"{kind} p{pages + 1}", q, {"code": code, **(variables or {})})
        pages += 1
        total_bytes += probe.calls[-1]["bytes"]
        page = report_part(data).get("ev") or {}
        batch = page.get("data") or []
        sizes.append(len(batch))
        events.extend(batch)
        s = page.get("nextPageTimestamp")
        if data is None:
            break
    return events, pages, total_bytes, sizes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report")
    ap.add_argument("--fight", type=int)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    meta = collect_data.load_meta()
    if args.report and args.fight:
        code, fid = args.report, args.fight
    else:
        code, fid = pick_target(meta)
    oldest = min(meta, key=meta.get) if meta else None
    cands = [c for c in normal_candidates(meta) if c["code"] != FIXTURE_CODE]

    P = Probe()
    R: dict = {"code": code, "fid": fid, "oldest": oldest, "candidates": cands}
    print(f"WCL probe: report {code} fight {fid}; oldest cached report {oldest}")
    stopped = None
    try:
        # 0. baseline: is a bare rateLimitData query free?
        bare = "query RL { reportData { report(code: \"%s\") { code } } }" % code
        P.run("baseline (report code only)", bare)
        P.run("baseline repeat", bare)

        # FIGHTS (fresh) + attribution check
        d = P.run("FIGHTS_QUERY", collect_data.FIGHTS_QUERY, {"code": code})
        rep = report_part(d) or cached_fights(code) or {}
        for a in (rep.get("masterData") or {}).get("actors") or []:
            RED.add(a.get("name"))
        P.run("bare after FIGHTS (attribution)", bare)
        fights = rep.get("fights") or []
        fight = next((f for f in fights if f["id"] == fid), None)
        if not fight:
            raise SystemExit(f"fight {fid} not in report {code}")
        R["fight"] = {k: fight.get(k) for k in ("id", "name", "difficulty", "kill", "startTime", "endTime", "friendlyPlayers")}
        R["fight"]["friendlyPlayers"] = len(fight.get("friendlyPlayers") or [])
        st, en = fight["startTime"], fight["endTime"]
        R["duration_s"] = round((en - st) / 1000, 1)

        P.run("PHASES_QUERY", collect_data.PHASES_QUERY, {"code": code})

        # 1. tables
        R["tables"] = {}
        for dt_ in ("Casts", "Buffs", "Summary"):
            q = ("query T($code: String!) { reportData { report(code: $code) { "
                 f"t: table(dataType: {dt_}, fightIDs: [{fid}]) }} }} }}")
            R["tables"][dt_] = report_part(P.run(f"table {dt_}", q, {"code": code})).get("t")

        # 3. playerDetails
        q = ("query PD($code: String!) { reportData { report(code: $code) { "
             f"pd: playerDetails(fightIDs: [{fid}], includeCombatantInfo: true) }} }} }}")
        pd = report_part(P.run("playerDetails +cinfo", q, {"code": code})).get("pd")
        R["playerDetails"] = pd
        pdd = ((pd or {}).get("data") or {}).get("playerDetails") or {}
        healers = pdd.get("healers") or []
        if not healers:
            summ = (R["tables"].get("Summary") or {}).get("data") or {}
            healers = (summ.get("playerDetails") or {}).get("healers") or []
        for grp in pdd.values():
            for p in grp or []:
                RED.add(p.get("name"))

        # 2. healer casts with resources
        if healers:
            hid = healers[0]["id"]
            R["healer"] = {"id": hid, "spec": (healers[0].get("specs") or [{}])[0], "type": healers[0].get("type")}
            q = ("query H($code: String!) { reportData { report(code: $code) { "
                 + events_part("h", fid, st, en, f"dataType: Casts, sourceID: {hid}, includeResources: true", 20)
                 + " } } }")
            R["healer_events"] = (report_part(P.run("healer casts includeResources", q, {"code": code})).get("h") or {})
        else:
            R["healer_events"] = None

        # 4. filtered casts, limit 100
        q = ("query F($code: String!, $filter: String) { reportData { report(code: $code) { "
             + events_part("f", fid, st, en, "dataType: Casts, filterExpression: $filter", 100) + " } } }")
        f100 = report_part(P.run("filtered casts limit 100", q,
                                 {"code": code, "filter": "source.type = 'player' AND type = 'begincast'"})).get("f") or {}
        R["f100"] = {"returned": len(f100.get("data") or []), "nextPageTimestamp": f100.get("nextPageTimestamp"),
                     "example": (f100.get("data") or [None])[0]}

        # 5. whole-fight player casts (the P2.1 alias form)
        ev, pages, nbytes, sizes = follow(P, "casts alias (whole fight)", code, fid, st, en,
                                          "dataType: Casts, hostilityType: Friendlies, filterExpression: $filter",
                                          10000, ", $filter: String", {"filter": CAST_FILTER})
        R["casts"] = {"events": len(ev), "pages": pages, "bytes": nbytes, "page_sizes": sizes,
                      "types": key_union([{e.get("type"): 1} for e in ev]),
                      "fake": sum(1 for e in ev if e.get("fake")),
                      "players": len({e.get("sourceID") for e in ev}),
                      "example": ev[0] if ev else None}

        # 6. archiveStatus (aliased)
        codes = [FIXTURE_CODE] + ([oldest] if oldest else []) + [c["code"] for c in cands[:1]]
        parts = " ".join(f'a{i}: report(code: "{c}") {{ code startTime archiveStatus {{ isArchived isAccessible archiveDate }} }}'
                         for i, c in enumerate(codes))
        d = P.run("archiveStatus x%d" % len(codes), "query A { reportData { " + parts + " } }")
        R["archive"] = [((d or {}).get("reportData") or {}).get(f"a{i}") for i in range(len(codes))]
        R["archive_codes"] = codes
        R["archive_error"] = P.calls[-1]["error"]

        # 7. enemy casts vs the cached Interrupts table
        ev, pages, nbytes, sizes = follow(P, "enemy casts", code, fid, st, en,
                                          "dataType: Casts, hostilityType: Enemies, filterExpression: $filter",
                                          10000, ", $filter: String", {"filter": "type IN ('begincast','cast')"})
        per: dict = {}
        for e in ev:
            a = per.setdefault(e.get("abilityGameID"), {"begincast": 0, "cast": 0})
            if e.get("type") in a:
                a[e["type"]] += 1
        R["enemy"] = {"events": len(ev), "pages": pages, "bytes": nbytes, "per_ability": per}
        b = cache.get_entry(collect_data._bundle_key(code, fid, True))
        R["interrupts_source"] = "cache"
        intr = (b or {}).get("interrupts")
        if intr is None:
            q = ("query I($code: String!) { reportData { report(code: $code) { "
                 f"t: table(dataType: Interrupts, fightIDs: [{fid}]) }} }} }}")
            intr = report_part(P.run("table Interrupts (not cached)", q, {"code": code})).get("t")
            R["interrupts_source"] = "live"
        R["interrupts"] = intr

        # 8. costs: 5-fight bundle, DamageTaken page, rankings
        boss = [f for f in fights if f.get("encounterID")]
        i = next((k for k, f in enumerate(boss) if f["id"] == fid), 0)
        five = boss[max(0, min(i, len(boss) - 5)):][:5]
        d = P.run(f"bundle v3 x{len(five)} fights", collect_data._bundle_query(five, True), {"code": code})
        brep = report_part(d)
        P.run("bare after bundle (attribution)", bare)
        R["bundle_fights"] = [f["id"] for f in five]
        cinfo_specs = []
        for f in five:
            for e in ((brep.get(f"cinfo_{f['id']}") or {}).get("data") or []):
                cinfo_specs.append(e.get("specID"))
        R["cinfo_specs"] = cinfo_specs
        R["cinfo_example_keys"] = sorted(((brep.get(f"cinfo_{five[0]['id']}") or {}).get("data") or [{}])[0].keys()) if five else []

        d = P.run("DamageTaken 10k page", collect_data.DAMAGE_TAKEN_QUERY,
                  {"code": code, "fightID": fid, "start": st, "end": en})
        dtp = (report_part(d).get("events") or {})
        R["dt_page"] = {"events": len(dtp.get("data") or []), "next": dtp.get("nextPageTimestamp")}

        kill = next((f for f in boss if f.get("kill")), fight)
        R["rank_fight"] = kill["id"]
        d = P.run(f"RANKINGS (fight {kill['id']})", collect_data.RANKINGS_QUERY, {"code": code, "fightID": kill["id"]})
        P.run("final bare (closes the lag)", bare)
    except StopProbe as exc:
        stopped = str(exc)
        print("  STOPPED:", stopped)
    R["stopped"] = stopped

    md = render(P, R)
    leaks = RED.leaks(md)
    if leaks:
        raise SystemExit(f"redaction failed for {len(leaks)} name(s); nothing written")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\nwrote {args.out}")
    for line in R.get("_summary", []):
        print(line)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def _attribute(P) -> bool:
    """Sets c['cost'] on every call; returns True if the counter lags one request."""
    bb = _delta(P, "bundle v3 x5 fights", raw=True)
    ab = _delta(P, "bare after bundle (attribution)", raw=True)
    lag = bool(bb is not None and ab is not None and ab > bb)
    for i, c in enumerate(P.calls):
        if lag:
            nxt = P.calls[i + 1] if i + 1 < len(P.calls) else None
            c["cost"] = nxt["delta"] if nxt else None
        else:
            c["cost"] = c["delta"]
    return lag


def _delta(P, kind, raw=False):
    for c in P.calls:
        if c["kind"] == kind:
            return c["delta"] if raw else c.get("cost")
    return None


def render(P, R) -> str:
    L = []
    w = L.append
    today = dt.date.today().isoformat()
    w(f"# 06 - Live WCL probe ({today})\n")
    w(f"Generated by `tools/wcl_probe.py` (design doc P0.7). Player names are redacted as `P1, P2, ...`.\n")
    f = R.get("fight") or {}
    w(f"Target: report `{R['code']}`, fight {R['fid']} ({f.get('name')}, difficulty {f.get('difficulty')}, "
      f"kill={f.get('kill')}, {R.get('duration_s')} s, {f.get('friendlyPlayers')} players). "
      f"Oldest cached report: `{R['oldest']}`.\n")
    if R.get("stopped"):
        w(f"**Probe stopped early:** {R['stopped']}\n")

    # calls table
    lag = _attribute(P)
    w("## Calls and point cost\n")
    w("`dpts` = `pointsSpentThisHour` in this call's response minus the previous call's value. `cost` = the points the "
      "call itself was charged after the attribution below (`dpts` of the NEXT call if the counter lags).\n")
    w("| # | kind | bytes | s | HTTP | dpts | cost | spent/limit | reset in s | error |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(P.calls, 1):
        rl = c.get("rl") or {}
        cost = c.get("cost")
        w(f"| {i} | {c['kind']} | {c['bytes']} | {c['seconds']} | {','.join(map(str, c['statuses']))} | "
          f"{'' if c['delta'] is None else c['delta']} | {'' if cost is None else cost} | "
          f"{rl.get('pointsSpentThisHour', '')}/{rl.get('limitPerHour', '')} | "
          f"{rl.get('pointsResetIn', '')} | {(c['error'] or '').replace('|', '/')[:120]} |")
    total = sum(c["delta"] for c in P.calls if c["delta"] and c["delta"] > 0)
    w(f"\nTotal: {len(P.calls)} queries, {len(HTTP_LOG)} HTTP requests, {round(total, 2)} points between the first and "
      "the last response (the first call's own cost is not included).\n")
    R["_total"] = total
    w("### Attribution\n")
    bb, ab = _delta(P, "bundle v3 x5 fights", raw=True), _delta(P, "bare after bundle (attribution)", raw=True)
    w(f"Bare query (`report {{ code }}`) dpts on repeat: {_delta(P, 'baseline repeat', raw=True)}. "
      f"5-fight bundle (30 aliases) dpts = {bb}; the bare call right after it dpts = {ab} -> "
      + ("**the counter lags one request**: a request's charge shows in the NEXT response. Costs below are lag-corrected."
         if lag else "**the counter includes the request's own charge**.")
      + " A negative delta would mean the hourly window reset during the probe.\n")
    rh = [h for h in HTTP_LOG if h["rate_headers"]]
    w("### Rate-limit headers\n")
    w(f"429 responses: {sum(1 for h in HTTP_LOG if h['status'] == 429)}. "
      f"Responses carrying `Retry-After`/`X-RateLimit-*`: {len(rh)}"
      + (f"; first: `{json.dumps(rh[0]['rate_headers'])}`, last: `{json.dumps(rh[-1]['rate_headers'])}`"
         if rh else " (none seen, also not on 200 responses)") + ".\n")

    # shapes
    w("## 1. Table shapes (`table(dataType: Casts | Buffs | Summary)`)\n")
    for k, t in (R.get("tables") or {}).items():
        w(f"### {k}\n")
        if t is None:
            w("No data (error or null).\n")
            continue
        w("Shape:\n\n```json\n" + snippet(shape(t, max_depth=4), 3000) + "\n```\n")
        w("First entries:\n\n```json\n" + snippet(first_entries(t), 3000) + "\n```\n")
    summ = ((R.get("tables") or {}).get("Summary") or {}).get("data") or {}
    w(f"Summary embeds `playerDetails`: **{'yes' if 'playerDetails' in summ else 'no'}** "
      f"(Summary `data` keys: {sorted(summ.keys())}).\n")

    w("## 2. Healer casts with `includeResources: true`\n")
    he = R.get("healer_events")
    if he:
        evs = he.get("data") or []
        w(f"Healer actor {R['healer']['id']} ({json.dumps(R['healer'].get('spec'))}); {len(evs)} events; "
          f"key counts: `{json.dumps(key_union(evs))}`.\n")
        cast = next((e for e in evs if e.get("type") == "cast"), evs[0] if evs else None)
        w("Example cast:\n\n```json\n" + snippet(cast) + "\n```\n")
    else:
        w("No healer found or call failed.\n")

    w("## 3. `playerDetails(fightIDs, includeCombatantInfo: true)`\n")
    pd = R.get("playerDetails")
    if pd:
        w("Shape:\n\n```json\n" + snippet(shape(pd, max_depth=6), 3500) + "\n```\n")
        w("First entry per role:\n\n```json\n" + snippet(first_entries(pd), 4000) + "\n```\n")
    else:
        w("No data.\n")

    w("## 4. Filtered Casts, `limit: 100`\n")
    f1 = R.get("f100") or {}
    w(f"Filter `source.type = 'player' AND type = 'begincast'`: returned {f1.get('returned')} events, "
      f"`nextPageTimestamp` = `{f1.get('nextPageTimestamp')}`.\n")
    w("```json\n" + snippet(f1.get("example")) + "\n```\n")

    w("## 5. Whole-fight player casts (P2.1 alias)\n")
    c = R.get("casts") or {}
    w(f"Filter `{CAST_FILTER}`, limit 10000: **{c.get('events')} events, {c.get('pages')} page(s)** "
      f"(page sizes {c.get('page_sizes')}), {c.get('bytes')} bytes total, {c.get('players')} distinct sources, "
      f"types {json.dumps(c.get('types'))}, `fake` events {c.get('fake')}. "
      f"Rate: {round((c.get('events') or 0) / max(1, R.get('duration_s') or 1) / max(1, f.get('friendlyPlayers') or 1), 2)} "
      "events/s/player.\n")
    w("```json\n" + snippet(c.get("example")) + "\n```\n")

    w("## 6. `archiveStatus`\n")
    if R.get("archive_error"):
        w(f"Error: `{R['archive_error']}`\n")
    for code, a in zip(R.get("archive_codes") or [], R.get("archive") or []):
        w(f"- `{code}`: `{json.dumps(a)}`")
    w("")

    w("## 7. Enemy casts vs the Interrupts table\n")
    e = R.get("enemy") or {}
    w(f"Enemy `begincast`/`cast` events: {e.get('events')} in {e.get('pages')} page(s), {e.get('bytes')} bytes. "
      f"Interrupts table source: {R.get('interrupts_source')}.\n")
    intr = R.get("interrupts") or {}
    w("Interrupts table (first entries):\n\n```json\n" + snippet(first_entries(intr, 2), 3000) + "\n```\n")
    rows = _interrupt_rows(intr)
    per = e.get("per_ability") or {}
    w("| ability | table spellsBegun | spellsCompleted | spellsInterrupted | events begincast | events cast |")
    w("|---|---|---|---|---|---|")
    for gid, r in rows.items():
        p = per.get(gid) or {}
        w(f"| {r.get('name')} ({gid}) | {r.get('spellsBegun')} | {r.get('spellsCompleted')} | {r.get('spellsInterrupted')} | "
          f"{p.get('begincast', 0)} | {p.get('cast', 0)} |")
    begun_not_listed = {k: v for k, v in per.items() if v["begincast"] and k not in rows}
    w(f"\nEnemy spells with `begincast` events that the Interrupts table does NOT list: {len(begun_not_listed)} "
      f"(`{json.dumps(dict(list(begun_not_listed.items())[:15]))}`).\n")
    R["_never_listed"] = len(begun_not_listed)

    w("## 8. Other cost probes\n")
    w(f"Bundle fights {R.get('bundle_fights')}; DamageTaken page: {json.dumps(R.get('dt_page'))}; "
      f"rankings fight {R.get('rank_fight')}. CombatantInfo event keys: `{R.get('cinfo_example_keys')}`.\n")

    # specs
    pd_specs = []
    for grp in (((pd or {}).get("data") or {}).get("playerDetails") or {}).values():
        for p in grp or []:
            ci = p.get("combatantInfo") or {}
            if isinstance(ci, dict) and ci.get("specIDs"):
                pd_specs.extend(ci["specIDs"])
            if isinstance(ci, dict) and ci.get("specID"):
                pd_specs.append(ci["specID"])
    ids = [s for s in R.get("cinfo_specs", []) + pd_specs if s is not None]
    unknown = sorted({s for s in ids if s not in KNOWN_SPECS})
    w("## 10. specIDs\n")
    w(f"specIDs seen (cinfo of the bundle fights + playerDetails): {sorted(set(ids))}. Unknown: {unknown or 'none'}.\n")

    # decisions
    fpts, ppts = _delta(P, "FIGHTS_QUERY"), _delta(P, "PHASES_QUERY")
    w("## Decisions\n")
    if fpts and ppts is not None:
        ratio = ppts / fpts
        d1 = (f"PHASES costs {ppts} vs FIGHTS {fpts} points ({round(ratio * 100)} %) -> "
              + ("**merge recommended** (>= 50 %)." if ratio >= 0.5 else "**no merge needed** (< 50 %).")
              + f" Absolute saving at most {ppts} point(s) per report against a {(P.calls[-1].get('rl') or {}).get('limitPerHour')}"
              " points/hour limit.")
    else:
        d1 = f"undetermined (FIGHTS dpts={fpts}, PHASES dpts={ppts}); see the attribution note."
    pages = c.get("pages")
    ev_s = (c.get("events") or 0) / max(1.0, R.get("duration_s") or 1.0)
    one_page_s = round(10000 / ev_s) if ev_s else None
    d2 = (f"{pages} page(s) ({c.get('page_sizes')} events, {c.get('bytes')} bytes) for the longest pull "
          f"({R.get('duration_s')} s, {f.get('friendlyPlayers')} players, {round(ev_s, 1)} events/s); at that rate a pull "
          f"longer than about {one_page_s} s needs a second page. A 3-fight request of long pulls returns ~3 MB "
          "and truncates each alias at 10,000 events, so the P2.1 follow-up loop is required; "
          + ("3 fights per request stays reasonable." if (c.get("bytes") or 0) < 1_500_000 else "use 1-2 fights per request."))
    arch = dict(zip(R.get("archive_codes") or [], R.get("archive") or []))
    fx = (arch.get(FIXTURE_CODE) or {}).get("archiveStatus")
    if fx is None:
        d3 = f"undetermined ({R.get('archive_error')})."
    elif fx.get("isArchived"):
        cand = R.get("candidates") or []
        d3 = ("fixture **is archived**; replace with " +
              (", ".join(f"`{x['code']}` ({x['pulls']} pulls, {x['kills']} kills)" for x in cand) or "a newer Normal night") + ".")
    else:
        d3 = f"fixture `{FIXTURE_CODE}` is **not archived** (`{json.dumps(fx)}`); keep it."
    d4 = f"unknown specIDs: **{unknown}**." if unknown else "**no unknown specID** appeared."
    for i, d in enumerate((d1, d2, d3, d4), 1):
        w(f"{i}. **{('FIGHTS+PHASES merge', 'Casts pages per whole-fight pull', 'archiveStatus', 'Unknown specID')[i - 1]}:** {d}")
    w("")
    R["_summary"] = ["Decisions:"] + [f"  {i}. {d}" for i, d in enumerate((d1, d2, d3, d4), 1)] + [
        f"Calls: {len(P.calls)} queries / {len(HTTP_LOG)} HTTP; points about {round(R['_total'], 2)}"]
    return RED.text("\n".join(L) + "\n")


def _interrupt_rows(intr) -> dict:
    """Flattens the Interrupts table into {abilityGameID: entry}. Shape-tolerant."""
    out = {}

    def walk(o):
        if isinstance(o, dict):
            if "spellsBegun" in o or "spellsInterrupted" in o:
                gid = o.get("guid") or o.get("id")
                out[gid] = o
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(intr)
    return out


if __name__ == "__main__":
    main()
