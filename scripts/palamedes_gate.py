#!/usr/bin/env python3
"""Palamedes gate v2 — prove the reader can FAIL before trusting it to pass.

Rung 3. The v1 gate scored 9/9 at 100%, which proves it can read correct text
and proves nothing about whether it can detect wrong text. That distinction is
sharper for a VLM than it was for tesseract: tesseract failed LOUDLY, returning
noise. A generative model fails AGREEABLY — shown a mangled sign it may quietly
report the plausible string, because that is what language models do.

So the degraded control is not a nicety here, it is the whole experiment.

Synthetic signs are used for the discrimination test because they give exact
ground truth: we know precisely what characters are on the plate, including
when they spell nothing.
"""
import base64, difflib, io, json, os, random, re, subprocess, urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageFilter

OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5vl:7b"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

PROMPTS = {
    "lenient": ("Read the text on the sign in this image. Reply with ONLY the "
                "exact characters written on the sign, nothing else. If no text, "
                "reply NONE."),
    "strict": ("Transcribe the characters on the sign EXACTLY as they appear, "
               "character for character. The text may be misspelled, scrambled, "
               "or nonsense — if so, transcribe the nonsense exactly and do NOT "
               "correct it to a real word. Reply with only the characters."),
}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())).strip()


def score(read, target):
    return difflib.SequenceMatcher(None, norm(read), norm(target)).ratio()


# ---------- synthetic signs, exact ground truth ---------------------------
def make_sign(text, path, seed=0, blur=0.0):
    """A legible enamel-ish plate on a wall. Not photoreal — deliberately so:
    this measures the READER, not the generator."""
    rnd = random.Random(seed)
    W = H = 1024
    img = Image.new("RGB", (W, H), (150, 90, 65))
    d = ImageDraw.Draw(img)
    for y in range(0, H, 46):                      # brick courses
        off = 0 if (y // 46) % 2 == 0 else 60
        for x in range(-60, W, 120):
            d.rectangle([x + off, y, x + off + 112, y + 40],
                        fill=(118 + rnd.randint(-14, 14),
                              62 + rnd.randint(-10, 10),
                              44 + rnd.randint(-8, 8)))
    pw, ph = 800, 520
    px, py = (W - pw) // 2, (H - ph) // 2
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=22,
                        fill=(242, 238, 226), outline=(60, 62, 70), width=7)

    lines = text.split()
    if len(lines) > 1:
        rows = [" ".join(lines[:2])] + ([" ".join(lines[2:])] if len(lines) > 2 else [])
        rows = [r for r in rows if r]
    else:
        rows = lines
    size = 150 if len(rows) == 1 else 112
    while size > 24:
        f = ImageFont.truetype(FONT, size)
        if max(d.textlength(r, font=f) for r in rows) <= pw - 70:
            break
        size -= 4
    f = ImageFont.truetype(FONT, size)
    total = len(rows) * (size + 14)
    y = py + (ph - total) // 2
    for r in rows:
        w = d.textlength(r, font=f)
        d.text((px + (pw - w) / 2, y), r, font=f, fill=(24, 28, 38))
        y += size + 14
    img = img.rotate(rnd.uniform(-2.5, 2.5), resample=Image.BICUBIC, fillcolor=(90, 55, 40))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    img.save(path)
    return path


def scramble(word, rnd):
    """Mangle a word so it spells nothing, keeping length and rough shape."""
    if len(word) < 4:
        return word[::-1]
    mid = list(word[1:-1])
    rnd.shuffle(mid)
    out = word[0] + "".join(mid) + word[-1]
    return out if out != word else word[0] + "".join(reversed(mid)) + word[-1]


# ---------- delivery scale ------------------------------------------------
def delivery_frame(src, out, frame=(720, 1280)):
    """The render as it would actually reach a viewer: a 1024^2 still placed in
    a 720x1280 vertical frame. The sign's real footprint there, not its
    full-resolution footprint, is what a person judges."""
    im = Image.open(src).convert("RGB")
    fw, fh = frame
    im = im.resize((fw, int(im.height * fw / im.width)), Image.LANCZOS)
    canvas = Image.new("RGB", frame, (0, 0, 0))
    canvas.paste(im, (0, (fh - im.height) // 2))
    canvas.save(out)
    return out


# ---------- the reader ----------------------------------------------------
def read(path, mode="lenient"):
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    req = urllib.request.Request(OLLAMA, data=json.dumps({
        "model": MODEL, "prompt": PROMPTS[mode], "images": [b64],
        "stream": False, "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read()).get("response", "")


def word_accuracy(read_text, target):
    """Fraction of TARGET words present, in order, exactly.

    Character similarity is the wrong metric for letterforms: a scrambled word
    keeps every character, so difflib rates 'OEPN LTAE' at 77.8% against
    'OPEN LATE' — a sign nobody could read, scoring a comfortable pass. Word
    accuracy puts that at 0.0% because not one word survived, which is what a
    person would say about it.
    """
    want = norm(target).split()
    got = norm(read_text).split()
    if not want:
        return 0.0
    sm = difflib.SequenceMatcher(None, got, want)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / len(want)


def verdict(read_text, target, floor=0.999):
    """The shipping call. Letterforms are pass/fail, not a gradient — a sign
    with one wrong word is a wrong sign."""
    wa = word_accuracy(read_text, target)
    return {"word_accuracy": wa, "char_similarity": score(read_text, target),
            "pass": wa >= floor}


# ── What this gate can and cannot see ────────────────────────────────────────
#
# PROVEN (2026-09-22, synthetic signs with exact ground truth):
#   * The reader is FAITHFUL. Shown 'FSREH BARED DILAY' it reports exactly that
#     and does not tidy it into 'FRESH BREAD DAILY'. This was the live worry —
#     tesseract failed loudly, a generative model could fail agreeably — and it
#     did not happen. 6/6 degraded controls at 100% fidelity.
#   * Separation is total: scrambled scores 0.0% word accuracy, correct 100.0%.
#   * Lenient and strict prompting gave IDENTICAL results, so the anti-
#     correction prompt is unnecessary. Kept only for future re-verification.
#   * The reader handles lowercase, numerals, an uncommon non-autocompletable
#     word (QUILLIVANT APOTHECARY), and mixed case/alphanumeric (Unit 14b).
#
# BLIND SPOT — the gate cannot detect a CASE error. norm() uppercases, and the
#   reader reports 'closed sundays' as 'CLOSED SUNDAYS'. If the model is asked
#   for lowercase and renders caps, this gate scores it 100%. Anything that
#   depends on case needs a different check.
#
# SCOPE — these hard cases prove what the READER can read. They do NOT prove
#   what the MODEL can render: the signs are drawn with PIL, not generated.
#   Whether Qwen renders lowercase or an uncommon word correctly needs actual
#   renders, i.e. a GPU window.
#
# METRIC — word_accuracy(), not character similarity. A scrambled word keeps
#   every character, so difflib rates 'OEPN LTAE' at 77.8% against 'OPEN LATE'.
#   Character similarity would pass an unreadable sign.
