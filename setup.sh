#!/usr/bin/env bash
set -e
PH3B3_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PH3B3_DIR/.venv"
echo "Ph3b3 Setup Starting..."
sudo apt update -qq
sudo apt install -y ffmpeg portaudio19-dev python3-pyaudio libsndfile1 v4l-utils
if [ ! -d "$VENV" ]; then python3 -m venv "$VENV"; fi
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$PH3B3_DIR/requirements.txt"
if [ ! -f "$PH3B3_DIR/soul/soul.md" ]; then
    cp "$PH3B3_DIR/soul/soul_public.md" "$PH3B3_DIR/soul/soul.md"
    echo "Soul seeded from soul_public.md — customise soul/soul.md to give Ph3b3 her full identity."
fi

# ── Piper TTS voices (one-time download; ZERO runtime network fetches) ─────────
# Alba (en) is Phoebe's voice; the others power the Language & Voice selector.
# ~60 MB each. Every model is HASH-PINNED: the sha256 below was recorded at
# selection time and verified on install — a mismatch aborts (no silent swap).
# Skips any already present (still hash-verified). Must match config/voices.yaml.
VOICE_DIR="${PH3B3_DATA:-$HOME/ph3b3_data}/voices"
REVIEW_JSON="${PH3B3_DATA:-$HOME/ph3b3_data}/voice_review.json"
mkdir -p "$VOICE_DIR"
HF="https://huggingface.co/rhasspy/piper-voices/resolve/main"
declare -A VOICES=(
  [en_GB-alba-medium]="en/en_GB/alba/medium"
  [es_ES-davefx-medium]="es/es_ES/davefx/medium"
  [fr_FR-siwis-medium]="fr/fr_FR/siwis/medium"
  [de_DE-thorsten-medium]="de/de_DE/thorsten/medium"
  [zh_CN-huayan-medium]="zh/zh_CN/huayan/medium"
  [es_MX-ald-medium]="es/es_MX/ald/medium"          # unreviewed candidate (Español México)
  [es_ES-sharvard-medium]="es/es_ES/sharvard/medium"  # unreviewed candidate (Español España alt)
  [es_MX-claude-high]="es/es_MX/claude/high"          # unreviewed candidate (Español México HQ)
  [de_DE-thorsten-high]="de/de_DE/thorsten/high"      # unreviewed candidate (Deutsch HQ)
)
# Registry code → sha256 (onnx, then .onnx.json). Pinned at selection time.
declare -A SHA_ONNX=(
  [en_GB-alba-medium]=401369c4a81d09fdd86c32c5c864440811dbdcc66466cde2d64f7133a66ad03b
  [es_ES-davefx-medium]=6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917
  [fr_FR-siwis-medium]=641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99
  [de_DE-thorsten-medium]=7e64762d8e5118bb578f2eea6207e1a35a8e0c30595010b666f983fc87bb7819
  [zh_CN-huayan-medium]=9929917bf8cabb26fd528ea44d3a6699c11e87317a14765312420be230be0f3d
  [es_MX-ald-medium]=019b3803293c93e34a206dd2e53a3889209a514e786fd7144f7b70196c579b63
  [es_ES-sharvard-medium]=40febfb1679c69a4505ff311dc136e121e3419a13a290ef264fdf43ddedd0fb1
  [es_MX-claude-high]=3ef40a71ea63852cd8ab7e6fa7d2ecdcfa67a0b47c9c48e3f10e02ee02083ea0
  [de_DE-thorsten-high]=9df1c43c61149ef9b39e618e2b861fbe41e1fcea9390b2dac62e8761573ea4f1
)
declare -A SHA_JSON=(
  [en_GB-alba-medium]=aa965a2f02ecced632c2694e1fc72bbff6d65f265fab567ca945918c73dd89f4
  [es_ES-davefx-medium]=0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842
  [fr_FR-siwis-medium]=39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959
  [de_DE-thorsten-medium]=974adee790533adb273a1ac88f49027d2a1b8f0f2cf4905954a4791e79264e85
  [zh_CN-huayan-medium]=d521dc45504a8ccc99e325822b35946dd701840bfb07e3dbb31a40929ed6a82b
  [es_MX-ald-medium]=5a71498158e04afc8099bfd019c7e87c68eb9d042505a2b1a87e5c1ac2b1a61d
  [es_ES-sharvard-medium]=7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c
  [es_MX-claude-high]=1afc81f703c0e4cb3b4d7c0dca096b8b54a98806807f0170cf5eb5557723c12d
  [de_DE-thorsten-high]=6de734444e4c3f9e33b7ebe2746dbc19b71e85f613e79c65acf623200b99a76a
)
verify() {  # verify <file> <expected-sha256>
  local got; got="$(sha256sum "$1" | cut -d' ' -f1)"
  if [ "$got" != "$2" ]; then
    echo "  ✗ HASH MISMATCH for $1"; echo "     expected $2"; echo "     got      $got"
    rm -f "$1"; return 1
  fi
}
# Model files the Captain rejected in the review flow (voice_review.json keys are
# registry codes; map them to model filenames via voices.yaml) — never re-fetched.
REJECTED_MODELS=""
if [ -f "$REVIEW_JSON" ]; then
  REJECTED_MODELS="$(python3 - "$REVIEW_JSON" "$PH3B3_DIR/config/voices.yaml" <<'PY' 2>/dev/null || true
import json, sys, yaml
review = json.load(open(sys.argv[1]))
reg = (yaml.safe_load(open(sys.argv[2])) or {}).get("voices", {})
for code, verdict in review.items():
    if verdict == "rejected":
        m = (reg.get(code) or {}).get("model", "")
        if m.endswith(".onnx"):
            print(m[:-5])   # model basename, no extension
PY
)"
fi

echo "Fetching Piper voices (~600 MB total, one-time, hash-verified) → $VOICE_DIR"
for name in "${!VOICES[@]}"; do
  if printf '%s\n' $REJECTED_MODELS | grep -qx "$name"; then
    echo "  $name rejected by review — skipping"; continue
  fi
  if [ -f "$VOICE_DIR/$name.onnx" ] && [ -f "$VOICE_DIR/$name.onnx.json" ]; then
    verify "$VOICE_DIR/$name.onnx" "${SHA_ONNX[$name]}" && \
    verify "$VOICE_DIR/$name.onnx.json" "${SHA_JSON[$name]}" && \
    { echo "  $name already present (hash ok)"; continue; }
    echo "  $name present but failed hash — re-downloading"
  fi
  echo "  downloading $name (~60 MB)..."
  curl -fsSL "$HF/${VOICES[$name]}/$name.onnx"      -o "$VOICE_DIR/$name.onnx"
  curl -fsSL "$HF/${VOICES[$name]}/$name.onnx.json" -o "$VOICE_DIR/$name.onnx.json"
  verify "$VOICE_DIR/$name.onnx"      "${SHA_ONNX[$name]}" || { echo "ABORT: $name.onnx"; exit 1; }
  verify "$VOICE_DIR/$name.onnx.json" "${SHA_JSON[$name]}" || { echo "ABORT: $name.onnx.json"; exit 1; }
done

echo "Ph3b3 Setup Complete"
echo "Nyx IP: $(hostname -I | awk '{print $1}')"
