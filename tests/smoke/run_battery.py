#!/usr/bin/env python3
"""Run the live smoke battery and record WHAT DECIDED each turn.

Why a runner rather than pytest: the interesting output is not pass/fail, it is
the stage that decided the turn and how often that stage changes its mind.
Triage's first stage is a model call, so a single verdict proves nothing — every
prompt runs `passes` times and the flake rate is part of the result.

ISOLATION. A fresh session id per prompt per pass, so nothing bleeds between
prompts. The /chat pipeline performs no unconditional Mnemosyne write — writes
come only from the remember tools — so a turn that fires one is FLAGGED rather
than assumed harmless.
"""
from __future__ import annotations
import argparse, json, pathlib, re, subprocess, sys, time, uuid

import requests, urllib3, yaml
urllib3.disable_warnings()

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))


def _auth():
    """Reuse the persona smoke's credentials — never read .env here."""
    import test_persona_smoke as T
    return T.BASE, T.AUTH


# Every deterministic pre-LLM lane. A lane missing from here is reported as
# "model" and fails its route check however well it worked — which is exactly
# what happened to fleet-status-* for nine passes in every baseline until
# 2026-10-05. If you add a lane, add it here and make it log a marker.
LANE_MARKERS = {
    "[head]": "lane:head", "[thoth]": "lane:thoth", "[story]": "lane:story",
    "[kadmos]": "lane:kadmos", "[apelles]": "lane:apelles",
    "[device-cmd]": "lane:device", "[echo-guard]": "lane:echo",
    "[fleet]": "lane:fleet", "[joke]": "lane:joke",
}
TOOL_RE = re.compile(r"\[Ph3b3\] Tool: ([a-z_]+)")
HOLD_RE = re.compile(r"TRIAGE_HOLD — missing=(\[.*?\]) turn=")
HOLD_OLD_RE = re.compile(r"TRIAGE_HOLD — missing=(\[.*?\])")
MEM_TOOLS = {"remember", "remember_fact", "add_note", "file_story", "add_story"}


def journal_since(pid: str, since: str) -> list[str]:
    try:
        out = subprocess.run(["journalctl", f"_PID={pid}", "--since", since,
                              "--no-pager", "-o", "short-iso"],
                             capture_output=True, text=True, timeout=30).stdout
        return out.splitlines()
    except Exception:
        return []


def classify(lines: list[str], reply: str) -> tuple[str, list, list]:
    """(stage, triage_missing, tools_fired) for one turn's log slice."""
    tools = TOOL_RE.findall("\n".join(lines))
    missing: list = []
    held = False
    for ln in lines:
        m = HOLD_RE.search(ln) or HOLD_OLD_RE.search(ln)
        if m and "OVERRULED" not in ln and "DECLINED" not in ln:
            held = True
            try:
                missing = json.loads(m.group(1).replace("'", '"'))
            except Exception:
                missing = [m.group(1)]
    if held:
        return "triage_hold", missing, tools
    for ln in lines:
        for marker, stage in LANE_MARKERS.items():
            if marker in ln:
                return stage, missing, tools
    if tools:
        return "tool", missing, tools
    return "model", missing, tools


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battery", default=str(ROOT / "tests/smoke/battery.yaml"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default=None, help="comma-separated categories")
    ap.add_argument("--allow-side-effects", action="store_true",
                    help="permit prompts labelled audio/motion to be sent")
    a = ap.parse_args()

    spec = yaml.safe_load(pathlib.Path(a.battery).read_text())
    prompts = spec["prompts"]
    if a.only:
        want = {c.strip() for c in a.only.split(",")}
        prompts = [p for p in prompts if p["category"] in want]
    passes = int(spec["meta"].get("passes", 3))
    # ── the side-effect gate ────────────────────────────────────────────────
    # Belt and suspenders. The real guarantee is the server-side sandbox
    # (reserved __smoke__ prefix, enforced at the actuators), but a runner that
    # can quietly drive a speaker or a servo should refuse to do it silently.
    # This exists because a battery of mine made her recite Genesis aloud.
    prefix = spec["meta"].get("session_prefix", "")
    sandboxed = prefix.startswith("__smoke__")
    risky = [p for p in prompts if p.get("side_effect", "none") != "none"]
    if risky and not (sandboxed or a.allow_side_effects):
        print("REFUSING TO RUN.", file=sys.stderr)
        print(f"  {len(risky)} prompts can act in the physical world and the session",
              file=sys.stderr)
        print(f"  prefix {prefix!r} is not the sandbox prefix:", file=sys.stderr)
        for p_ in risky:
            print(f"    {p_['id']:<28} {p_['side_effect']}: {p_['text']!r}", file=sys.stderr)
        print("  Use the __smoke__ prefix, or pass --allow-side-effects.", file=sys.stderr)
        return 2
    if risky:
        print("=" * 68)
        print(f"  {len(risky)} prompts CAN act in the real world "
              f"({sum(1 for p_ in risky if p_['side_effect']=='audio')} audio, "
              f"{sum(1 for p_ in risky if p_['side_effect']=='motion')} motion)")
        print(f"  sandbox: {'YES — session prefix ' + prefix if sandboxed else 'NO — --allow-side-effects given'}")
        if not sandboxed:
            print("  SHE WILL SPEAK AND MOVE. Ctrl-C now if that is not intended.")
        print("=" * 68, flush=True)

    base, auth = _auth()
    pid = subprocess.run(["systemctl", "show", "ph3b3", "-p", "MainPID", "--value"],
                         capture_output=True, text=True).stdout.strip()
    print(f"[battery] {len(prompts)} prompts x {passes} passes = "
          f"{len(prompts)*passes} turns | ph3b3 pid={pid}", flush=True)

    results = []
    for p_i in range(1, passes + 1):
        for pr in prompts:
            sid = f"{prefix}{uuid.uuid4().hex[:10]}"
            t_mark = time.strftime("%Y-%m-%d %H:%M:%S")
            t0 = time.time()
            err = None
            reply = ""
            try:
                r = requests.post(f"{base}/chat",
                                  json={"message": pr["text"], "session_id": sid},
                                  auth=auth, verify=False, timeout=180)
                r.raise_for_status()
                d = r.json()
                reply = d.get("reply") or d.get("text") or d.get("response") or ""
            except Exception as e:                                 # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
            dt = time.time() - t0
            time.sleep(0.4)                 # let the journal flush
            lines = [l for l in journal_since(pid, t_mark) if sid in l or "[Ph3b3]" in l]
            mine = [l for l in lines if sid in l]
            window = lines if not mine else lines[lines.index(mine[0]):]
            stage, missing, tools = classify(window, reply)

            low = (reply or "").lower()
            ok_pass = (not pr.get("pass")) or any(s.lower() in low for s in pr["pass"])
            ok_deny = not any(s.lower() in low for s in pr.get("deny", []))
            route_ok = (stage == "triage_hold") == (pr["expect_route"] == "hold")
            if pr["expect_route"] == "lane":
                route_ok = route_ok and (stage.startswith("lane") or stage == "tool")

            results.append({
                "pass": p_i, "id": pr["id"], "category": pr["category"],
                "text": pr["text"], "expect_route": pr["expect_route"],
                "stage": stage, "triage_missing": missing, "tools": tools,
                "mem_write": sorted(set(tools) & MEM_TOOLS),
                "latency_s": round(dt, 2), "error": err,
                "ok": bool(ok_pass and ok_deny and route_ok and not err),
                "ok_pass": ok_pass, "ok_deny": ok_deny, "ok_route": route_ok,
                "reply": (reply or "")[:400], "sid": sid,
            })
            flag = "ok " if results[-1]["ok"] else "FAIL"
            print(f"  [{flag}] p{p_i} {pr['id']:<26} {stage:<14} {dt:5.1f}s"
                  + (f"  missing={missing}" if missing else ""), flush=True)

    out = pathlib.Path(a.out)
    out.write_text(json.dumps({"label": a.label, "battery": a.battery,
                               "results": results}, indent=2))
    print(f"[battery] wrote {out} ({len(results)} turns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
