# Palamedes — Phase 0 findings + Phase 0.5 record (2026-09-22)

Qwen text-rendering lane inside the existing ComfyUI. Findings only at Phase 0;
Phase 0.5 (weights download, no wiring) authorised by ruling on 2026-09-22.
Nothing is wired into Phoebe. Nothing touches the floor surface.

## 1. Licence — the finding that decides the model pick

The brief said *"verify per-variant, not per-family."* That earned its keep: the
Qwen-Image family **splits licences mid-line**.

| Weights | Licence | Sellable output |
|---|---|---|
| Qwen-Image (orig, 20B) | Apache 2.0 | yes |
| Qwen-Image-Edit-2509 | Apache 2.0 | yes |
| **Qwen-Image-2512** (20B, 2025-12-31) | **Apache 2.0** | yes |
| **Qwen-Image-2.1** (7B, native 2K) | **Qwen Research License Agreement** | **NO — research only** |

Qwen-Image-2.1 is the *newest and technically strongest* of the line — 7B instead
of 20B, native 2K, up to 10 reference images — and it is the one that cannot be
used, because Ph3b3 output gets sold and published. That is the trap: instinct
reaches for the newest. There is visible HF community pushback on exactly this
("License renders this model useless"), so it is not a misread of an ambiguous file.

2512's Apache status was verified **against the upstream card itself**, not by the
community-derivative attestation that prompted the check. Primary-source record,
`curl` against the raw file on 2026-09-22:

    $ curl -sL https://huggingface.co/Qwen/Qwen-Image-2512/raw/main/README.md | head -3
    ---
    license: apache-2.0

`card_data.license = apache-2.0`, `license_link = None` (no override pointing at a
custom agreement), repo `last_modified 2025-12-31`. One honest caveat: the repo
carries **no separate LICENSE file** (`/raw/main/LICENSE` -> HTTP 404), so the
declaration rests on the card frontmatter alone. That frontmatter is the canonical
HF mechanism — it drives the license shown on the page and any download gate — but
it is a one-line declaration, not bundled licence text. Both quant repos used
below also carry `license: apache-2.0` in their own metadata.

Apache 2.0 is irrevocable for the version held, so weights already on Nyx cannot
be retroactively converted to research-only. The exposure is only ever the *next*
download.

**Standing rule (ruling, 2026-09-22):** every future Qwen release gets its own
licence check *before* anyone evaluates its capability.

## 2. Premise check — what was already on Nyx

- ComfyUI **v0.27.1**; Qwen support is **in core, not a custom node**:
  `comfy/text_encoders/qwen_image.py`, `QwenImage` at `comfy/supported_models.py:1851`,
  and `comfy_extras/nodes_qwen.py` exposing `TextEncodeQwenImageEdit`,
  `TextEncodeQwenImageEditPlus`, `EmptyQwenImageLayeredLatentImage`.
- `custom_nodes/ComfyUI-GGUF` already installed. `nodes.py:32-33` maps
  `unet_gguf → models/diffusion_models` and `clip_gguf → models/text_encoders`.
- **No new custom nodes are required.**

One correction to an earlier reading: `models/text_encoders/` already held
`qwen_1.7b_ace15` and `qwen_0.6b_ace15`. Those are **ACE-Step music encoders**,
unrelated to this lane. `QwenImage.clip_target()` requires a `qwen25_7b` encoder;
nothing usable was present.

## 3. Why GGUF rather than the official fp8

Comfy-Org officially repackages 2512, but the smallest official build is
`qwen_image_2512_fp8_e4m3fn.safetensors` at **20.43 GB** — it cannot fit the
4060 Ti's 16 GB. GGUF is therefore the lane on merit, not as a compromise.

`Q4_0` was **rejected by ruling**: 1.2 GB saved against 903 GB free buys nothing
and costs quality in letterforms, the one dimension this module exists for.

## 4. Phase 0.5 download manifest (weights only — 64.4 GB)

Ruling order: Edit-2509 first (the edit lane is primary; the main-street sign is
the driving wound), shared encoder and VAE fetched once.

| # | File | Size | Destination |
|---|---|---|---|
| 1 | `Qwen-Image-Edit-2509-Q4_K_M.gguf` | 13.07 GB | `models/diffusion_models/` |
| 2 | `qwen_2.5_vl_7b_fp8_scaled.safetensors` | 9.38 GB | `models/text_encoders/` |
| 3 | `qwen_image_vae.safetensors` | 0.25 GB | `models/vae/` |
| 4 | `Qwen-Image-Edit-2509-Q5_K_S.gguf` | 14.12 GB | `models/diffusion_models/` |
| 5 | `qwen-image-2512-Q4_K_M.gguf` | 13.24 GB | `models/diffusion_models/` |
| 6 | `qwen-image-2512-Q5_K_S.gguf` | 14.30 GB | `models/diffusion_models/` |

Disk: 903 GB free of 1.8 TB before the pull. `rm` remains the exit.


### Download result (2026-09-22, complete)

All six files verified at exact expected size; staging dir removed; the running
ComfyUI picked all four rungs up **without a restart** (`UnetLoaderGGUF` lists
them, `CLIPLoader` offers type `qwen_image`, `VAELoader` sees the VAE).

Sustained 83-87 MB/s; whole 64.4 GB manifest in ~13 min.
Disk went 903 GB free -> 843 GB free; `models/` 111 G -> 171 G.

Every source repo carries `license: apache-2.0` in its own metadata:
`QuantStack/Qwen-Image-Edit-2509-GGUF`, `unsloth/Qwen-Image-2512-GGUF`,
`Comfy-Org/Qwen-Image_ComfyUI`.

## 5. VRAM arithmetic — why the Q5 up-rung test is a real question

The 7B encoder (9.38 GB) and the diffusion model **cannot co-reside** on a 16 GB
card. ComfyUI must encode the prompt, evict the encoder, then load the diffusion
model — so the diffusion model runs alone, which is what makes the up-rung test
worth running at all.

- Q4_K_M 13.07 GB ≈ 12.2 GiB → ~3.8 GiB headroom for activations + VAE decode
- Q5_K_S 14.12 GB ≈ 13.2 GiB → ~2.8 GiB headroom

Card is 16380 MiB = 15.99 GiB. Q5_K_S is genuinely marginal, not obviously fine
and not obviously doomed. **The measurement rules, not the estimate.** If Q5_K_S
fits with activations at 1024², it is the pick; if it OOMs, Q4_K_M stands.

The load/evict cycle per prompt is itself a deliverable — it is the Herakles case
in miniature.

## 6. Logged, no action — v2 candidate

`InstantX/Qwen-Image-ControlNet-Inpainting` — **Apache 2.0**, 4.23 GB single
`diffusion_pytorch_model.safetensors`, 8.3k downloads. Mask-based text
modification against the Qwen-Image base: the surgical sign-repair path, as
opposed to regenerating the whole frame.

Attribution note: the publisher is **InstantX**, not Alibaba. The
`Alibaba-Research-Intelligence-Computing/...` and `alimama-creative/...` paths
both 404.

Filed so this does not get rediscovered from scratch. **Not downloaded, not wired.**

## 7. Open — awaiting measurement

Deliverables owed before Phase 1 is proposed:

- warm-start VRAM footprint, both quant rungs
- seconds-per-1024²
- load/evict cycle time per prompt

**Correction to the eviction plan:** a *restart* of ph3b3 does not work.
`agent/server.py:591` constructs `STTModule()` at import, and its `__init__`
immediately spawns a thread running `whisper.load_model("medium", device="cuda")`.
There is no unload path anywhere in `modules/stt_module.py` (`grep` for
`unload|del _model|empty_cache|_model = None|release` returns nothing). A restart
therefore frees ~4.5 GB for about three seconds before it reloads. The card can
only be cleared by **stop -> measure -> start**, i.e. she is down for the whole
measurement window.

This is also the Herakles case pointing the wrong way: `free_gpu` levels
`("cached", "running")` both target ComfyUI. Nothing in the fleet can evict
*her* models so ComfyUI can work. That is why an `STTModule` lazy-load + evict
lifecycle is a **Phase 1 prerequisite, not an enhancement** (ruling, 2026-09-22) —
without it Palamedes and her hearing cannot share a 16 GB card at all.

ollama released its 6.7 GB unprompted; `/api/ps` reports no models loaded. At Phase 0 read the card already had 12.2 GB held (ollama 6.7 GB
plus two python processes), leaving 3.7 GB free — nothing could have been measured
against that.

## 8. Measured results (2026-09-22) — Phase 0.5 deliverables

Window: Ph3b3 **stopped** (not restarted — see the correction in §7), ComfyUI up,
1024^2, 20 steps, euler/simple, cfg 2.5, GGUF via `UnetLoaderGGUF`,
`qwen_2.5_vl_7b_fp8_scaled` encoder, `qwen_image_vae`.

| rung | warm s/1024^2 | peak MiB | headroom | evict cycle | cold penalty |
|---|---|---|---|---|---|
| **Edit-2509 Q4_K_M** | **136.3** | 14,467 | **1,913** | **+3.4 s** | +10.4 s |
| 2512 Q4_K_M | 137.2 | 14,788 | 1,592 | +11.0 s | +22.6 s |
| Edit-2509 Q5_K_S | 159.3 | 15,505 | 875 | +9.2 s | +9.5 s |
| 2512 Q5_K_S | ~155.4 * | — | — | — | — |

\* Partial. A SIGINT reached the process group at 16:19:17, nine seconds before
ComfyUI finished the render; the harness died mid-wait and the third render was
never submitted. The trap ran `restore` once on the signal and again on normal
exit — the double restart in the log is the signature. The render itself
succeeded: ComfyUI logged `Prompt executed in 155.37 seconds` at 16:19:26. Peak
VRAM and the evict cycle for this rung are **not measured**.

### What the numbers decided

**Q4_K_M wins on both models.** Q5_K_S fits — that was the open question the
ruling asked measurement to settle — but costs 15-17% render time and buys
nothing. Fitting is not winning.

**The evict cycle was the wrong thing to worry about.** The brief and the Phase 0
analysis both expected encoder/diffusion swapping to be the architectural problem.
At Edit-2509 Q4_K_M it costs **3.4 s**. ComfyUI keeps the 9.38 GB encoder in host
RAM and the PCIe round trip is cheap.

**Headroom, not model size, drives the evict cost.** 2512 Q4_K_M carries only
0.17 GB more weight than Edit-2509 Q4_K_M and renders within noise of it
(137.2 vs 136.3 s), but 321 MiB less staging room **triples** its evict cycle
(3.4 -> 11.0 s) and doubles its cold penalty (10.4 -> 22.6 s).

**The real problem is render time: 136 s per 1024^2.** Not plumbing. That is what
decides whether this lane is usable, and it is why the Lightning LoRA stopped
being an optimisation and became the thing under test.

### Lightning LoRA — asymmetry that bears on the model pick

`lightx2v/Qwen-Image-Lightning` (Apache 2.0) declares `base_model: Qwen/Qwen-Image`
— the original August weights. The only version-matched folder in the repo is
`Qwen-Image-Edit-2509/`. **There is no 2512-matched acceleration LoRA.**

So Edit-2509 has a matched fast path and 2512 has none. Applying the V2.0 files to
2512 would be an unmatched pairing whose failure could not be distinguished from
2512 being bad at letterforms — a result that looks like data and is not.

Edit-2509 Q4_K_M is also the **only** rung with room for the 0.85 GB LoRA without
eating the margin that keeps its evict cycle cheap.

### Letterform gate

Gate is OCR character accuracy, not impression: render a sign whose text we chose,
read it back with `tesseract 5.3.4`, score against the intended string (best match
over the whole read, each line, and adjacent line pairs, since signs wrap). Signs:
`OPEN LATE`, `FRESH BREAD DAILY`, `MAIN STREET`. Harness:
`scratchpad/measure_gate.py`.

Caveat carried into the comparison: 4/8-step Lightning runs at cfg 1.0 by design,
so the baseline at cfg 2.5 differs in more than step count. That is how each would
actually be run, but the speed gap is not purely steps.

### Reader: tesseract was measured UNFIT and replaced

The first gate scored a **visibly perfect** render of `OPEN LATE` at **0.0%** —
tesseract returned an empty string. A sweep of 30 preprocessing variants
(grayscale / autocontrast / invert / threshold / 2x upscale x psm 3,6,7,11,12)
peaked at 61.5% on a read of `'RE BIL EN E NE L A'` — difflib overlap on noise,
a number that looks like a score and means nothing.

Cause is not contrast polarity (the dark-on-light `FRESH BREAD DAILY` render also
read as `''`). It is that tesseract is a **document** OCR engine and these are
**scene text** images: perspective, weathered texture, display face. No
preprocessing fixes that.

Replaced with `qwen2.5vl:7b` via ollama (already pulled, no install). The scorer
now **validates itself first** against a render confirmed correct by eye and
prints `READER UNFIT` rather than emitting scores, because the original failure
was exactly a gate reporting confident garbage.

    reader returned: 'OPEN LATE'   -> READER OK

### Letterform gate — results

Nine renders, `qwen2.5vl:7b` reading each sign back, scored against the intended
string. Edit-2509 Q4_K_M throughout, so the LoRA is the only variable.

| case | steps | cfg | mean s/image | speedup | letterform |
|---|---|---|---|---|---|
| baseline | 20 | 2.5 | 145.4 | 1.0x | **100.0%** (3/3) |
| **lightning 4-step** | 4 | 1.0 | **24.7** | **5.9x** | **100.0%** (3/3) |
| lightning 8-step | 8 | 1.0 | 43.8 | 3.3x | **100.0%** (3/3) |

Per-sign 4-step: 26.2 / 24.1 / 23.7 s. Per-sign 8-step: 45.2 / 43.6 / 42.7 s.

**The 4-step LoRA passes the gate at zero letterform cost.** The 8-step rung has
no reason to exist in this lane: it costs 19 s more per image and cannot beat a
perfect score.

### The gate has no proven teeth

9/9 at 100% means **the gate never failed anything**, so it is validated as able
to READ correct text but not as able to DETECT degraded text. `OPEN LATE`,
`FRESH BREAD DAILY` and `MAIN STREET` are short, common, all-caps strings that
Qwen renders trivially.

Before this gate guards anything in Phase 1 it needs a case it can fail on:
longer strings, mixed case, numerals, hyphenation, and an uncommon word the model
cannot infer from context. A deliberately degraded render (1-step, or a wrong-step
LoRA pairing) should be scored too, to prove the gate reports a low number when
one is deserved.

### Discarded: the window's own SUMMARY line

`measure_lora.log` ends with `4-step: letterform +0.0 pts, 8-step: +13.3 pts`.
That is **tesseract output and is void** — the 8-step's apparent advantage is
`'POE IB'` scoring 40% against `OPEN LATE` by coincidence.
