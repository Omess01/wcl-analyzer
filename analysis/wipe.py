"""
Post-wipe cutoff (Contract B of the Phase 1 plan).

WCL's `wipeCalledTime` is set only when the raid leader called the wipe in the Companion app, which in practice
never happens (0 of 201 wipes in the cache). The fallback detects the death cascade that ends a wipe: deaths and
hits strictly after the cascade's first death are not held against a player.

Stdlib only - imported from collect_data, so it must not import anything from dash/ or collect_data.
"""

WIPE_CASCADE_GAP_S = 10.0     # consecutive deaths this close together belong to the same cascade
WIPE_CASCADE_MIN_DEATHS = 3   # a cascade needs at least this many deaths to count as "the wipe"
WIPE_TAIL_S = 20.0            # ... and its last death must be this close to the end of the pull


def wipe_cutoff_s(kill, duration_s, death_times, wipe_called_s) -> float | None:
    """
    Seconds into the pull after which deaths / hits no longer count, or None when everything counts.

    - `wipe_called_s` set -> returned as is (WCL's own wipe call wins).
    - kills -> None.
    - otherwise: sort the death times, take the longest suffix whose consecutive gaps are all <= WIPE_CASCADE_GAP_S;
      if it has >= WIPE_CASCADE_MIN_DEATHS deaths and its last death is within WIPE_TAIL_S of `duration_s`, the
      cutoff is the FIRST death of that suffix (that death still counts: callers compare `seconds <= cutoff`).
    """
    if wipe_called_s is not None:
        return float(wipe_called_s)
    if kill or duration_s is None:
        return None
    times = sorted(float(t) for t in (death_times or []) if t is not None)
    if len(times) < WIPE_CASCADE_MIN_DEATHS:
        return None
    i = len(times) - 1
    while i > 0 and times[i] - times[i - 1] <= WIPE_CASCADE_GAP_S:
        i -= 1
    suffix = times[i:]
    if len(suffix) < WIPE_CASCADE_MIN_DEATHS:
        return None
    if float(duration_s) - suffix[-1] > WIPE_TAIL_S:
        return None
    return suffix[0]
