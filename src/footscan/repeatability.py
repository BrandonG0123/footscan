"""Repeatability statistics for n = 1 (one foot, many captures).

Input: long-format rows with columns
    foot, condition, source, session, capture_id, pick, load_kg, measure, value

Error structure
---------------
A single number from a scan contains three nested kinds of error:

    session  - where the stickers went when the bone was palpated
    capture  - standing/positioning differences and reconstruction noise
    pick     - clicking the landmark on the mesh

``capture_id`` is nested in ``session``; ``pick`` repeats are nested in
``capture_id``. We estimate each level from pooled within-group variance and
subtract the lower level's contribution, the standard nested-ANOVA idea:
the variance of capture *means* within a session contains capture variance
plus pick variance / (picks per capture).

The headline SD is across capture means (all sessions pooled) - what you
would see if you scanned again tomorrow.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy import stats

CONDITION_ORDER = ("nwb", "nwb_relaxed", "swb", "fwb")
MIN_RELIABLE_N = 5
G = 9.80665


def _csv_text(p) -> str:
    """A hand-filled CSV's text. Excel saves "CSV UTF-8" with a byte-order mark (utf-8-sig drops it, or the
    first column name would carry it) and plain "CSV" on Windows in cp1252, which isn't valid UTF-8."""
    raw = Path(p).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def read_rows(paths) -> list[dict]:
    rows = []
    for p in paths:
        with io.StringIO(_csv_text(p), newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("value", "").strip() == "":
                    continue
                r["value"] = float(r["value"])
                r["pick"] = int(r.get("pick") or 1)
                r["load_kg"] = float(r["load_kg"]) if r.get("load_kg", "").strip() else None
                rows.append(r)
    return rows


def sd_ci(sd: float, n: int, level: float = 0.95) -> tuple[float, float]:
    """CI for a standard deviation: (n-1) s^2 / sigma^2 ~ chi^2(n-1)."""
    if n < 2:
        return (math.nan, math.nan)
    df = n - 1
    a = (1 - level) / 2
    return (sd * math.sqrt(df / stats.chi2.ppf(1 - a, df)), sd * math.sqrt(df / stats.chi2.ppf(a, df)))


def pooled_var(groups: list[list[float]]) -> tuple[float, int]:
    ss, df = 0.0, 0
    for g in groups:
        if len(g) >= 2:
            g = np.asarray(g)
            ss += float(((g - g.mean()) ** 2).sum())
            df += len(g) - 1
    return (ss / df if df else math.nan), df


@dataclass
class Summary:
    foot: str
    source: str
    condition: str
    measure: str
    n: int
    mean: float
    sd: float
    sd_lo: float
    sd_hi: float
    mdc95: float
    pick_sd: float = math.nan
    capture_sd: float = math.nan
    session_sd: float = math.nan
    n_sessions: int = 0
    mean_load_kg: float | None = None
    warnings: list[str] = field(default_factory=list)


def summarize(rows: list[dict]) -> list[Summary]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["foot"], r["source"], r["condition"], r["measure"])].append(r)

    out = []
    for key, rs in sorted(groups.items(), key=lambda kv: _sort_key(kv[0])):
        by_cap: dict[str, list[float]] = defaultdict(list)
        cap_session: dict[str, str] = {}
        loads = []
        for r in rs:
            by_cap[r["capture_id"]].append(r["value"])
            cap_session[r["capture_id"]] = r.get("session") or "S?"
            if r["load_kg"] is not None:
                loads.append(r["load_kg"])
        cap_means = {c: float(np.mean(v)) for c, v in by_cap.items()}
        x = np.array(list(cap_means.values()))
        n = len(x)
        sd = float(x.std(ddof=1)) if n >= 2 else math.nan
        lo, hi = sd_ci(sd, n)
        s = Summary(*key, n=n, mean=float(x.mean()), sd=sd, sd_lo=lo, sd_hi=hi,
                    mdc95=1.96 * math.sqrt(2) * sd,
                    mean_load_kg=float(np.mean(loads)) if loads else None)

        pick_var, pick_df = pooled_var(list(by_cap.values()))
        if pick_df:
            s.pick_sd = math.sqrt(pick_var)
            k_bar = np.mean([len(v) for v in by_cap.values()])
        else:
            pick_var, k_bar = 0.0, 1.0

        by_sess: dict[str, list[float]] = defaultdict(list)
        for c, m in cap_means.items():
            by_sess[cap_session[c]].append(m)
        s.n_sessions = len(by_sess)
        cap_var, cap_df = pooled_var(list(by_sess.values()))
        if cap_df:
            s.capture_sd = math.sqrt(max(0.0, cap_var - pick_var / k_bar))
            if len(by_sess) >= 2:
                sess_means = np.array([np.mean(v) for v in by_sess.values()])
                n_bar = np.mean([len(v) for v in by_sess.values()])
                s.session_sd = math.sqrt(max(0.0, sess_means.var(ddof=1) - cap_var / n_bar))
                if len(by_sess) < 3:
                    s.warnings.append(f"session SD from {len(by_sess)} sessions has {len(by_sess)-1} df - rough")

        if n < MIN_RELIABLE_N:
            s.warnings.append(f"only {n} captures: SD unreliable (target >= 10)")
        out.append(s)
    return out


def _sort_key(key):
    foot, source, cond, measure = key
    ci = CONDITION_ORDER.index(cond) if cond in CONDITION_ORDER else 99
    return (foot, source, measure, ci, cond)


@dataclass
class Difference:
    foot: str
    source: str
    measure: str
    cond_a: str
    cond_b: str
    diff: float            # mean_a - mean_b
    se: float
    p_value: float
    mdc95_single: float    # noise on a difference of two single scans


def condition_differences(summaries: list[Summary]) -> list[Difference]:
    idx = defaultdict(dict)
    for s in summaries:
        idx[(s.foot, s.source, s.measure)][s.condition] = s
    out = []
    for (foot, source, measure), by_c in idx.items():
        conds = sorted(by_c, key=lambda c: CONDITION_ORDER.index(c) if c in CONDITION_ORDER else 99)
        for a, b in combinations(conds, 2):
            A, B = by_c[a], by_c[b]
            if A.n < 2 or B.n < 2:
                continue
            va, vb = A.sd**2 / A.n, B.sd**2 / B.n
            se = math.sqrt(va + vb)
            diff = A.mean - B.mean
            if se > 0:
                dof = (va + vb) ** 2 / (va**2 / (A.n - 1) + vb**2 / (B.n - 1))
                p = float(2 * stats.t.sf(abs(diff) / se, dof))
            else:
                p = math.nan
            out.append(Difference(foot, source, measure, a, b, diff, se, p,
                                  1.96 * math.sqrt(A.sd**2 + B.sd**2)))
    return out


def arch_height_flexibility(summaries: list[Summary]) -> list[dict]:
    """(DH_swb - DH_fwb) / (F_fwb - F_swb) in mm/kN, with propagated SE."""
    out = []
    idx = {(s.foot, s.source, s.condition): s for s in summaries if s.measure == "dorsal_height_50_mm"}
    for (foot, source, cond), swb in idx.items():
        if cond != "swb" or (foot, source, "fwb") not in idx:
            continue
        fwb = idx[(foot, source, "fwb")]
        if swb.mean_load_kg is None or fwb.mean_load_kg is None:
            out.append(dict(foot=foot, source=source, ahf=None, note="load_kg not recorded"))
            continue
        dF_kN = (fwb.mean_load_kg - swb.mean_load_kg) * G / 1000
        if dF_kN <= 0:
            out.append(dict(foot=foot, source=source, ahf=None, note="fwb load not greater than swb load"))
            continue
        dh = swb.mean - fwb.mean
        se = math.sqrt(swb.sd**2 / swb.n + fwb.sd**2 / fwb.n) / dF_kN
        out.append(dict(foot=foot, source=source, ahf=dh / dF_kN, se=se, delta_h=dh, delta_F_kN=dF_kN, note=""))
    return out


def gate(effect: float, noise: float) -> str:
    if any(math.isnan(v) for v in (effect, noise)):
        return "INSUFFICIENT DATA"
    effect = abs(effect)
    if noise < 0.5 * effect:
        return "PASS"
    if noise < effect:
        return "MARGINAL"
    return "FAIL"
