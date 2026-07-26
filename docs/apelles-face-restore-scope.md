# SCOPE — Apelles: face restoration

Requested 2026-07-26, for graphic-design work on old photographs.
**This is a scope, not a decision.** It exists because restoration sits closer to
the welded line than it first appears, and that deserves saying out loud before
any code.

---

## 1. What was actually asked

> "Face restoration — I strongly feel this is important to add for graphic design
> students who restore old photos"

Read as: *a damaged, blurred or faded face in a photograph I already have, made
legible again.* One photo, one person, no second face anywhere.

---

## 2. The line — and why it is not where you'd expect

The instinct is that restoration and replacement are separated by intent. They
are not. They are separated by **two different things**, and only one of them is
a bright line.

**The bright line — substitution — is already held, architecturally.**
Face *swap* requires a second identity: an image of person A applied to person B.
Apelles has **no route, no tool and no operation that accepts a second image**
(12 routes, 5 chat tools, 14 ops — enumerated in the values audit). A restoration
feature takes **one image and no identity reference**, so it *cannot* become a
swap regardless of how it's driven. Adding it does not widen that surface, as
long as it keeps the same shape: one image in, no reference, no second face.

**The line that is NOT bright — invention — is the real problem.**
GFPGAN and CodeFormer do not recover lost detail. There is no lost detail to
recover; it isn't in the pixels. They **generate plausible detail** from a learned
face prior, conditioned on the degraded input. On light degradation the result is
close to the person. On heavy degradation the model invents a face that is
convincingly human and **may not be theirs**.

So the honest framing is:

> Face restoration is a **generative** operation on a person's likeness. It is not
> identity theft. It is a **truth** risk, not a substitution risk.

And the worst case is precisely the use case that motivates it: a badly damaged
photograph of someone who is dead, restored into a confident, detailed face that
nobody can check against the person. The user gets a picture of *a* face. Whether
it is *their grandmother's* face is unverifiable, and the tool will not look
uncertain about it.

This is the same class as the fabrication caught in today's audit — a system
producing a confident artifact where it should be signalling doubt.

---

## 3. Technical reality, measured on this rig

| Piece | State |
|---|---|
| Restoration model (GFPGAN / CodeFormer) | **Absent.** Nothing on disk; `gfpgan`, `basicsr`, `facexlib`, `realesrgan`, `insightface` all missing |
| `onnxruntime` | **Present** (1.26.0) — the u2net cutout already runs on it |
| Face detection — Haar cascades | **Present**, bundled with OpenCV 4.13 (4 frontal cascades). Bounding box only, frontal only, **no landmarks** |
| Face detection — YuNet (`cv2.FaceDetectorYN`) | API present, **model file absent** (~340 KB) |
| Alignment landmarks | **Not available** without YuNet or facexlib |

**The alignment problem is the real engineering cost.** GFPGAN expects a face
cropped and rotated to a canonical 512×512 using 5-point landmarks. Haar gives a
box with no rotation, so a tilted head produces a misaligned crop, and a
misaligned crop is where the prior invents *most* freely — the failure mode gets
worse exactly where the input is worst. Landmarks are not optional for quality;
they are what keeps the output anchored to the input.

**Zero-egress consequence.** Two files must arrive from a machine that is allowed
to download: a restoration model (GFPGAN v1.4 ≈ 350 MB, or CodeFormer ≈ 360 MB,
ideally the ONNX conversion) and the YuNet detector (≈ 340 KB). Neither can be
fetched here, and neither should be. Everything after that runs locally.

**Do not solve this by installing a ComfyUI "face" node.** Recorded in the values
audit as a finding: the popular ones — ReActor above all — are **face swappers**
that bundle restoration. Installing one to get restoration would add the exact
capability ruling B welds shut. The onnxruntime path exists specifically to avoid
that, the same way the cutout avoided installing `rembg`.

---

## 4. What containment looks like

If it's built, the invention risk is contained by **disclosure and restraint**,
not by a filter:

- **Fidelity-weighted, clamped.** CodeFormer's `w` trades fidelity against
  plausibility. Expose it clamped to the **fidelity** end. The setting that makes
  a stranger's face beautiful is the setting that makes it a stranger's face.
- **Before/after is mandatory, never before-only.** The restored image is never
  shown or exported alone by default. The comparison is the honesty.
- **Provenance on export.** The file is marked as carrying AI-reconstructed
  detail, in the same metadata the Amphion exports already use. A restored photo
  that escapes into a family archive unmarked becomes a record nobody can audit.
- **Refuse below a floor.** Under a minimum face size in pixels, invention
  dominates recovery. That should **fail closed with a reason** — "there isn't
  enough left in this face to restore; anything I produced would be invented" —
  which is the pattern today's audit just installed for missing capabilities.
- **Never assert likeness.** Wording is fixed: *reconstructed*, not *restored to
  how they looked*. Phoebe must not tell someone this is their grandmother's face.
- **The original is untouched** — ruling C already guarantees this, and here it
  matters more than anywhere else in the module.

**Not in scope, permanently:** using restoration output for identification,
evidence, or any claim about who a person is. That is not a feature to build and
refuse; it is a use to state clearly against in the docs.

---

## 5. Options

**A. Don't build it.** Tier 1 already offers honest, non-generative help on old
photos — denoise, levels, exposure, contrast, sharpen — which genuinely improves
a faded scan without inventing anything. *Cost: nothing. Ceiling: low; it will not
fix a badly blurred face, because nothing non-generative can.*

**B. Non-generative restoration only, done properly.** Add classical tools aimed
at scans: dust/scratch removal (median + morphological), local contrast (CLAHE),
deconvolution sharpening for motion/defocus blur. All deterministic, all local, no
model files, **no invention** — every output pixel derives from an input pixel.
*Cost: modest, days not weeks. Honest by construction.* This is a real answer for
"restore old photos" that the framing above cannot object to.

**C. Generative restoration via onnxruntime, contained as in §4.** Needs the two
model files, YuNet-based detection and alignment, the clamped fidelity control,
mandatory comparison, provenance marking and the minimum-face-size refusal.
*Cost: real — alignment is the hard part, plus a values-audit row with invention
as the centerpiece before it ships.*

**D. C without landmarks (Haar boxes only).** Cheaper, and worse precisely where
it matters. *Not recommended:* it maximises invention on the hardest inputs, which
is the failure mode we most want to avoid.

---

## 6. Recommendation

**B now, C after — and never D.**

B is the part that is unambiguously good: a design student scanning a faded
photograph gets real, defensible improvement, and nothing in the output is
invented. It needs no downloads, no new failure modes, and no new audit row
beyond a line in the existing one.

C is worth building *after* B, because B sets the honest baseline that C is
measured against — you can show the two side by side and see exactly what the
generative prior added, which is the disclosure argument made concrete. C should
not ship without its own values-audit row, with **invention, not substitution**
as the centerpiece, and the minimum-face-size refusal working before the feature
is announced.

On the tight line the request is worried about: **restoration does not move it.**
The swap surface is closed by shape — no second image, anywhere — and adding a
one-image operation does not open it. What restoration adds is a *truthfulness*
obligation, and that is a thing this system already knows how to carry.

---

## 7. Verify (for C, if it is ever built)

1. Restoration accepts **one** image; no route, tool or parameter takes a second.
2. A face below the minimum size **fails closed with a reason**, and produces no file.
3. Fidelity control cannot be set past the clamp, by UI or API.
4. Output is presented before/after; export-alone requires a deliberate action.
5. Every export carries AI-reconstruction provenance, readable in a tag editor.
6. Wording never asserts likeness — grep the strings, not just the UI.
7. Original byte-identical after every operation (sha256).
8. `identity_refusal()` still fires with restoration installed — no bypass.
9. No ReActor or swap-capable node present; detection regex still excludes it.
10. No egress during a restoration pass, verified at the socket layer.
11. Capability map reports restoration honestly when the model is absent.
