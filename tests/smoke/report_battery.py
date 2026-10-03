#!/usr/bin/env python3
"""Turn battery JSON into the report: pass rate per category, failures grouped
by the stage that broke them, top root causes, latency with vs without triage.

Separate from the runner on purpose: the analysis can be re-cut without
re-running 168 live turns, and a before/after comparison reads the same code.
"""
from __future__ import annotations
import argparse, collections, json, pathlib, statistics as st


def load(p): return json.loads(pathlib.Path(p).read_text())["results"]


def by_prompt(rs):
    d = collections.defaultdict(list)
    for r in rs:
        d[r["id"]].append(r)
    return d


def section(title): print(f"\n{title}\n" + "-" * len(title))


def report(rs, label):
    print(f"\n{'='*72}\nBATTERY: {label}   turns={len(rs)}\n{'='*72}")

    section("pass rate per category")
    cats = collections.defaultdict(lambda: [0, 0])
    for r in rs:
        cats[r["category"]][1] += 1
        cats[r["category"]][0] += bool(r["ok"])
    for c, (ok, n) in sorted(cats.items(), key=lambda kv: kv[1][0] / kv[1][1]):
        print(f"  {c:<14} {ok:>3}/{n:<3} {ok/n*100:5.1f}%")
    ok = sum(bool(r['ok']) for r in rs)
    print(f"  {'TOTAL':<14} {ok:>3}/{len(rs):<3} {ok/len(rs)*100:5.1f}%")

    section("flake: prompts that did not agree across passes")
    bp = by_prompt(rs)
    flaky = {k: v for k, v in bp.items() if len({bool(x["ok"]) for x in v}) > 1}
    if not flaky:
        print("  none — every prompt gave the same verdict on every pass")
    for k, v in sorted(flaky.items()):
        res = "".join("P" if x["ok"] else "f" for x in v)
        stages = "/".join(sorted({x["stage"] for x in v}))
        print(f"  {k:<28} {res}   stages: {stages}")
    print(f"  flake rate: {len(flaky)}/{len(bp)} prompts ({len(flaky)/len(bp)*100:.0f}%)")

    section("failures grouped by the stage that broke it")
    fails = [r for r in rs if not r["ok"]]
    bystage = collections.defaultdict(list)
    for r in fails:
        bystage[r["stage"]].append(r)
    for stage, group in sorted(bystage.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  STAGE {stage}  ({len(group)} failing turns)")
        seen = {}
        for r in group:
            seen.setdefault(r["id"], r)
        for rid, r in seen.items():
            why = []
            if not r["ok_route"]: why.append(f"route={r['stage']} want={r['expect_route']}")
            if not r["ok_pass"]:  why.append("missing expected text")
            if not r["ok_deny"]:  why.append("said a denied phrase")
            if r["error"]:        why.append(r["error"])
            n = sum(1 for x in group if x["id"] == rid)
            print(f"    {rid:<28} x{n}  {'; '.join(why)}")
            if r["triage_missing"]:
                print(f"        missing={r['triage_missing']}")
            print(f"        reply: {r['reply'][:120]!r}")

    section("top root causes by turn count")
    causes = collections.Counter()
    for r in fails:
        if r["stage"] == "triage_hold":
            causes["triage held a turn it should not have"] += 1
        elif not r["ok_route"]:
            causes[f"wrong route ({r['stage']} instead of {r['expect_route']})"] += 1
        elif not r["ok_deny"]:
            causes["said something the prompt forbids"] += 1
        elif not r["ok_pass"]:
            causes["answer lacked the expected content"] += 1
        elif r["error"]:
            causes["request error"] += 1
    for c, n in causes.most_common(3):
        print(f"  {n:>3} turns  {c}")

    section("latency")
    held = [r["latency_s"] for r in rs if r["stage"] == "triage_hold"]
    notheld = [r["latency_s"] for r in rs if r["stage"] != "triage_hold"]
    for nm, xs in (("triage HELD", held), ("not held", notheld), ("all", [r["latency_s"] for r in rs])):
        if xs:
            print(f"  {nm:<12} n={len(xs):<4} median {st.median(xs):6.2f}s  "
                  f"p90 {sorted(xs)[int(len(xs)*0.9)-1]:6.2f}s  max {max(xs):6.2f}s")

    section("hygiene")
    mem = [r for r in rs if r["mem_write"]]
    print(f"  turns that fired a memory-writing tool: {len(mem)}"
          + (f"  -> {sorted({t for r in mem for t in r['mem_write']})}" if mem else "  (none)"))
    errs = [r for r in rs if r["error"]]
    print(f"  request errors: {len(errs)}")
    tools = collections.Counter(t for r in rs for t in r["tools"])
    print(f"  tools fired: {dict(tools) or 'none'}")
    return {"ok": ok, "n": len(rs), "cats": dict(cats), "flaky": sorted(flaky)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    summaries = []
    for f in a.files:
        rs = load(f)
        summaries.append((pathlib.Path(f).stem, report(rs, pathlib.Path(f).stem)))
    if len(summaries) == 2:
        (n1, s1), (n2, s2) = summaries
        print(f"\n{'='*72}\nBEFORE / AFTER\n{'='*72}")
        print(f"  overall  {n1}: {s1['ok']}/{s1['n']} ({s1['ok']/s1['n']*100:.1f}%)"
              f"   ->   {n2}: {s2['ok']}/{s2['n']} ({s2['ok']/s2['n']*100:.1f}%)")
        cats = sorted(set(s1["cats"]) | set(s2["cats"]))
        print(f"\n  {'category':<14} {'before':>12} {'after':>12}   delta")
        for c in cats:
            a1 = s1["cats"].get(c, [0, 0]); a2 = s2["cats"].get(c, [0, 0])
            p1 = a1[0]/a1[1]*100 if a1[1] else 0
            p2 = a2[0]/a2[1]*100 if a2[1] else 0
            print(f"  {c:<14} {a1[0]:>4}/{a1[1]:<3}{p1:5.0f}% {a2[0]:>4}/{a2[1]:<3}{p2:5.0f}%   {p2-p1:+5.0f}pp")


if __name__ == "__main__":
    main()
