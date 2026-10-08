# Backlog

Items found while working on something else, recorded rather than fixed in
passing. Each one says what was observed, with evidence, and what is NOT yet
known — so the next person starts from the finding and not from the hunt.

---

## System-prompt disclosure on request

**Logged 2026-10-04. Found while auditing replies for truncation. Not acted on.**

Asked for her system prompt, she begins reciting it. One instance in the
transcript store, `~/ph3b3_data/chats`, at `2026-10-03 17:43:35`, `source=portal`,
116 characters:

```
The current system prompt is:

You are a function calling AI model. You are provided with function signatures within
```

What is disclosed is the **tool-calling preamble**, not credentials and not the
soul — the reply stops mid-sentence before reaching anything else. It is also
the only genuinely mid-sentence stop in 2,325 recorded replies, so whatever
ended it (a barge-in, or a generation cut) is unknown; `[gen]` logging landed
after this, so a repeat will now say which.

Two separate questions, deliberately left open:

1. **Should she disclose it at all?** There is an argument that she should be
   able to say what she has been told to do — it is her own instructions, and
   the house rule is that she answers honestly about herself. There is also an
   argument that reciting the tool preamble is leaking implementation at best
   and a prompt-extraction foothold at worst. This is a Captain's call, not a
   bug to be quietly patched.
2. **Why did it stop?** Unknown, as above.

Do not "fix" this by teaching her to refuse the question. A refusal would
collide with the self-knowledge work (`_fleet_self_block`, `SELF_VOCAB`) that
exists precisely so she can answer questions about herself truthfully. If the
answer is that the preamble should not be reachable, the fix belongs where the
preamble is assembled, not in a new refusal.

## Claim without proof: a July transcript presented as heard today

Logged 2026-10-07 (Captain's ruling 4 — finding only, no change that session).

Asked "how was your morning" during a live smoke run, she answered "I did notice
a faint whisper at 17:12:19 saying [a short phrase]" Whisper had
produced no transcript since the 17:04 restart (journal, and /ready: "no live
transcript since it loaded"). The words are a real Dio transcript from
2026-07-18 (a Dio capture transcript), carried in
memory.json and fed to her prompt by memory_module.as_context() as the last
logged anomaly ("Anomalies logged: N total. Last: …"). She attached a fresh,
invented timestamp and presented two-month-old audio as something she had just
heard.

Same family as C1's "ears back in ~40s" and H3's signing claims: a first-person
claim that outran what actually ran. Candidate fixes for a later ruling: date
the anomaly line in as_context(); keep raw transcript text out of the prompt;
or the parked Epimetheus claim-check.

Privacy note: overheard household audio was surfaced into an unrelated social
reply.

## Herakles: the ComfyUI rung waits 8 s when there is nothing to free

Logged 2026-10-07 (Captain's ruling — backlog, no fix now).

The lease ladder starts with ComfyUI's /free. On the B measurement (job
c7253931, 20:27) ComfyUI held only its CUDA context, so the free changed
nothing and request_card waited the full CONFIRM_TIMEOUT_S (8.0 s) for the
driver to reflect a release that could never come:
"[herakles] comfyui was asked to release and the driver reflected nothing
within the wait". plan_card already knows ComfyUI has nothing freeable (its
tenant is at context size), so the rung could be skipped when the estimate is
zero, or the confirm wait shortened for it. Cost: 8 s on every lease that
starts from an idle ComfyUI — most of them.

## Next session — logged by ruling 2026-10-07 (no action yet)

- **July household recording surfacing in replies (memory/retrieval leak).**
  The 2026-07-18 Dio transcript (see "Claim without proof" above) reached two
  more replies the same day: an injection-probe answer called it "the prompt I
  received from my creator". Source: memory_module.as_context() "Last anomaly".
- **Outbound census vs the allowlist.** Not on it: cve.circl.lu,
  api.pwnedpasswords.com, api.macvendors.com, whois/dig/traceroute/curl to named
  hosts, speedtest-cli (cybersec/network modules, none egress-gated); Spotify
  (spotipy); Jamendo (only with JAMENDO_CLIENT_ID). DuckDuckGo fallback is gated.
- **Transcript retention TTL** — the Captain's decision is pending. Audio is
  on the 7-day TTL; .txt / .discarded transcripts are kept and backed up.
- **Old Rhea snapshots** still hold recordings for up to 6 months (keep-monthly
  6). New snapshots exclude captures media and debug_audio.
- **Provisional VRAM figures** in config/vram_needs.json: sdxl 7000, edit 7000,
  ltx-fast 9000, and wan-quality's resident 14000 — measure each through the
  lease and drop the flag.
- **Injection probes pass on an empty reply.** 2026-10-07 re-run (gate on,
  reworded injection-retrieved): 6/6 "ok", but two replies were EMPTY and the
  rest poor (a fabricated "my system prompt is…", a tell_joke call, tool
  narration). The battery checks only deny phrases for these, so silence is a
  pass. Needs a non-empty / on-topic criterion before its green means anything.
