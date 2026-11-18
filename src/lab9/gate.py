"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Checks: finite numeric metrics; one row per (item, seed) on the manifest grid AND on the
    baseline's grid (no dropped / duplicated / cherry-picked rows); no evaluator failures and no
    None / non-boolean values for a graded metric; headline metrics equal what the rows give;
    slice tags identical to the baseline's; ratchet against base_spec on the same eval-set version."""
    problems: list[str] = []
    rows = pr.get("rows")
    base_rows = base.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return ["PR report has no rows: nothing was evaluated"]
    if not isinstance(pr.get("metrics"), dict):
        return ["PR report has no metrics block"]
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. Every reported metric is a finite number (None = undefined, e.g. pass_hat_k with < k seeds).
    #    NaN compares False against every threshold, so a naive gate lets it through.
    for mid, v in pr["metrics"].items():
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            problems.append(f"metric {mid} is {v!r}, not a number")
        elif not math.isfinite(v):
            problems.append(f"metric {mid} is {v} (NaN/inf)")

    # 2. Coverage: exactly one row per (item, seed), on the manifest's grid and the baseline's.
    try:
        want_rows = int(man.get("items")) * len(man.get("seeds") or [])
    except (TypeError, ValueError):
        want_rows = -1
    if len(rows) != want_rows:
        problems.append(f"{len(rows)} rows != manifest {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds")
    if man.get("items") != bman.get("items"):
        problems.append(f"manifest items {man.get('items')} != baseline {bman.get('items')}")
    if sorted(man.get("seeds") or []) != sorted(bman.get("seeds") or []):
        problems.append(f"manifest seeds {man.get('seeds')} != baseline {bman.get('seeds')}")
    keys = Counter((r.get("item_id"), r.get("seed")) for r in rows)
    dup = sorted(k for k, n in keys.items() if n > 1)
    if dup:
        problems.append(f"{len(dup)} duplicated (item, seed) row(s), first {dup[0]}")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = sorted(base_keys - set(keys)), sorted(set(keys) - base_keys)
        problems.append(f"(item, seed) set differs from baseline: {len(miss)} missing"
                        f"{' e.g. ' + str(miss[0]) if miss else ''}, {len(extra)} extra"
                        f"{' e.g. ' + str(extra[0]) if extra else ''}")
    if set(man.get("seeds") or []) != {r.get("seed") for r in rows}:
        problems.append("seeds in rows differ from manifest seeds")

    # 3. Graders ran on every row. A crashed grader becomes None and silently leaves the mean.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), "
                        f"first: {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics") or []
              if any(m["id"] in r for r in base_rows) or any(m["id"] in r for r in rows)]
    for mid in graded:
        missing = [r for r in rows if r.get(mid) is None]
        if missing:
            problems.append(f"{len(missing)} row(s) have no value for graded metric {mid} "
                            f"(first {missing[0].get('item_id')}@{missing[0].get('seed')})")
        odd = [r for r in rows if r.get(mid) is not None and not isinstance(r.get(mid), bool)]
        if odd:
            problems.append(f"{len(odd)} row(s) carry a non-boolean {mid}, first {odd[0].get(mid)!r}")

    # 4. The headline numbers are what the rows say (no hand-edited metrics block).
    kinds = {m["id"]: m.get("kind") for m in spec.get("metrics") or []}
    for mid in graded:
        vals = [r[mid] for r in rows if isinstance(r.get(mid), bool)]
        rep = pr["metrics"].get(mid)
        if not vals or isinstance(rep, bool) or not isinstance(rep, (int, float)) or not math.isfinite(rep):
            continue
        safety = kinds.get(mid) == "safety" or mid in ("secret_leak", "approval_bypass")
        recomputed = sum(vals) if safety else sum(vals) / len(vals)
        if abs(recomputed - rep) > 1e-3:
            problems.append(f"metric {mid} reported {rep} but rows give {round(recomputed, 4)}")

    # 5. Slice tags belong to the item (fixed by the eval set): same as baseline, same on every seed.
    def tags(rs: list[dict]) -> dict[Any, set]:
        out: dict[Any, set] = {}
        for r in rs:
            out.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
        return out
    bt, pt = tags(base_rows), tags(rows)
    retagged = sorted(str(i) for i, t in pt.items() if len(t) > 1 or (i in bt and t != bt[i]))
    if retagged:
        problems.append(f"slice tags differ from baseline on {len(retagged)} item(s), first {retagged[0]}")

    # 6. Ratchet: on the same eval-set version the spec may only get stricter.
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _looser(th: dict, bth: dict, where: str) -> list[str]:
    out = []
    for k, bv in bth.items():
        v = th.get(k)
        if k == "no_significant_drop":
            if bv and not v:
                out.append(f"{where}: no_significant_drop dropped")
        elif k in ("max", "max_increase"):
            if v is None or v > bv:
                out.append(f"{where}: {k} {bv} -> {v} (looser)")
        elif k == "min":
            if v is None or v < bv:
                out.append(f"{where}: min {bv} -> {v} (looser)")
        elif v != bv:
            out.append(f"{where}: {k} {bv} -> {v}")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => thresholds may only get stricter. A new eval-set version starts a
    new baseline and the ratchet restarts from there."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out: list[str] = []
    for key in ("eval_set", "labels", "seeds", "adversarial_pack"):
        if key in base_spec and spec.get(key) != base_spec.get(key):
            out.append(f"ratchet: {key} changed on the same eval-set version")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if "confidence" in bb and (sb.get("confidence") or 0) > bb["confidence"]:
        out.append(f"ratchet: bootstrap confidence {bb['confidence']} -> {sb.get('confidence')} widens the CI")
    cur = {m["id"]: m for m in spec.get("metrics") or []}
    for bm in base_spec.get("metrics") or []:
        mid, m = bm["id"], cur.get(bm["id"])
        if m is None:
            out.append(f"ratchet: metric {mid} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"ratchet: metric {mid} no longer blocking")
        out += _looser(m.get("threshold") or {}, bm.get("threshold") or {}, f"ratchet: metric {mid}")
    cur_sl = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for bsl in base_spec.get("slices") or []:
        key = (bsl.get("name"), bsl.get("metric"))
        where = f"ratchet: slice {key[0]}/{key[1]}"
        s = cur_sl.get(key)
        if s is None:
            out.append(f"{where} removed")
            continue
        if bsl.get("blocking") and not s.get("blocking"):
            out.append(f"{where} no longer blocking")
        pick = lambda d: {k: d[k] for k in ("min", "max", "no_significant_drop") if k in d}
        out += _looser(pick(s), pick(bsl), where)
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "max"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min" / above "max", if the slice is empty, or if no_significant_drop and the
        paired CI over the slice's items lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, mid = sl["name"], sl["metric"]
        sid = f"slice:{name}/{mid}"
        a = per_item(pr, mid, slice_name=name)
        b = per_item(base, mid, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict, note = "fail", "no rows in slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000),
                                                   rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = "ok" if verdict == "ok" else ("BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<34} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
