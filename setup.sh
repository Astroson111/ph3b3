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
  [en_US-ryan-high]="en/en_US/ryan/high" # unreviewed candidate (English alt to Alba)
  [en_US-lessac-high]="en/en_US/lessac/high" # unreviewed candidate (English alt to Alba)
  [en_GB-jenny_dioco-medium]="en/en_GB/jenny_dioco/medium" # unreviewed candidate (English alt to Alba)
  [de_DE-thorsten-high]="de/de_DE/thorsten/high"      # unreviewed candidate (Deutsch HQ)
  [it_IT-paola-medium]="it/it_IT/paola/medium"        # unreviewed candidate (Italiano)
  [pl_PL-gosia-medium]="pl/pl_PL/gosia/medium"        # unreviewed candidate (Polski)
  [ru_RU-irina-medium]="ru/ru_RU/irina/medium"        # unreviewed candidate (Русский)
  [vi_VN-vais1000-medium]="vi/vi_VN/vais1000/medium"  # unreviewed candidate (Tiếng Việt)
  [ar_JO-kareem-medium]="ar/ar_JO/kareem/medium"      # unreviewed candidate (العربية, RTL)
  [tr_TR-dfki-medium]="tr/tr_TR/dfki/medium"          # unreviewed candidate (Türkçe)
  [nl_NL-pim-medium]="nl/nl_NL/pim/medium"            # unreviewed candidate (Nederlands; pim, not mls)
  [uk_UA-ukrainian_tts-medium]="uk/uk_UA/ukrainian_tts/medium"  # unreviewed candidate (Українська)
  [cs_CZ-jirka-medium]="cs/cs_CZ/jirka/medium"        # unreviewed candidate (Čeština)
  [sv_SE-nst-medium]="sv/sv_SE/nst/medium"            # unreviewed candidate (Svenska)
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
  [en_GB-jenny_dioco-medium]=469c630d209e139dd392a66bf4abde4ab86390a0269c1e47b4e5d7ce81526b01
  [en_US-lessac-high]=4cabf7c3a638017137f34a1516522032d4fe3f38228a843cc9b764ddcbcd9e09
  [en_US-ryan-high]=b3990d7606e183ec8dbfba70a4607074f162de1a0c412e0180d1ff60bb154eca
  [de_DE-thorsten-high]=9df1c43c61149ef9b39e618e2b861fbe41e1fcea9390b2dac62e8761573ea4f1
  [it_IT-paola-medium]=6fc918b5a0ea6137382833dddfa567bffbe6a5060c02043c87192ee59c04210c
  [pl_PL-gosia-medium]=38f66464240ed74f186e6b7dc13c6e3b22e023426299f25c2b3cc9dfa9373fbc
  [ru_RU-irina-medium]=8ff38212d23da300bbe3705c645e6e5b9475f0bfde01558eb17813e22acaaaaa
  [vi_VN-vais1000-medium]=ec7c89e2c85f4d1edc24b6120c18aaf1bda614f06b511567eb9c7c0de15e2dab
  [ar_JO-kareem-medium]=9e95cab07b679da603bba17c4dec7ab3111320571964ee95c0379603c086491e
  [tr_TR-dfki-medium]=2844717f524ab965d3fe86e60562cbb601d3e456836efcc2196cc3a14112a8fb
  [nl_NL-pim-medium]=403e58c3675c394f505c2428117bf34cc56e9542dcf6eadbdd3a84706c12e048
  [uk_UA-ukrainian_tts-medium]=7920419ac5f6fd8b6450520f24b52ed5a319cb53dd018fbcd71c9e079cbac84f
  [cs_CZ-jirka-medium]=cbd5c900acacc8e8cbecd64347abb8de39c00a9d3104bed06fee92e4f319efc8
  [sv_SE-nst-medium]=df011f56825a59dd1efc080c38a65a1ef70407e60f63050e9246f43a3d7e471e
)
declare -A SHA_JSON=(
  [en_US-ryan-high]=c6d3b98f08315cb4bebf0d49d50fc4ff491b503c64b940cd3d5ca28543b48011
  [en_US-lessac-high]=db42b97d9859f257bc1561b8ed980e7fb2398402050a74ddd6cbec931a92412f
  [en_GB-jenny_dioco-medium]=a9a7a93a317c9a3cb6563e37eb057df9ef09c06188a8a4341b0fcb58cba54dd4
  [en_GB-alba-medium]=aa965a2f02ecced632c2694e1fc72bbff6d65f265fab567ca945918c73dd89f4
  [es_ES-davefx-medium]=0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842
  [fr_FR-siwis-medium]=39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959
  [de_DE-thorsten-medium]=974adee790533adb273a1ac88f49027d2a1b8f0f2cf4905954a4791e79264e85
  [zh_CN-huayan-medium]=d521dc45504a8ccc99e325822b35946dd701840bfb07e3dbb31a40929ed6a82b
  [es_MX-ald-medium]=5a71498158e04afc8099bfd019c7e87c68eb9d042505a2b1a87e5c1ac2b1a61d
  [es_ES-sharvard-medium]=7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c
  [es_MX-claude-high]=1afc81f703c0e4cb3b4d7c0dca096b8b54a98806807f0170cf5eb5557723c12d
  [de_DE-thorsten-high]=6de734444e4c3f9e33b7ebe2746dbc19b71e85f613e79c65acf623200b99a76a
  [it_IT-paola-medium]=aea19c0a7fce29fbc359b93f10e7902854401e4c95ae2ea328ae516b15d296cf
  [pl_PL-gosia-medium]=1aefb31a9d53ffe44a8163ff73ec833acb7a6253848f6bb0403d8a66f9c7510d
  [ru_RU-irina-medium]=c2ec28bb38e2b59e93b959b3e40348c1afebbd272f30fed5d41205d08e98a9d7
  [vi_VN-vais1000-medium]=fafb9da1354ed4b77c31af228ed41fb41cd825c14cffa105454b25e6ae751ee0
  [ar_JO-kareem-medium]=ea6d9b9d9076dbdb6bf5c98c6a141ef154959d2359709b37855727964e7d6c4d
  [tr_TR-dfki-medium]=13ebd7810f1b61b5027583cf3131a0a233b6ea81c38f2200ebc4ff41c3cca039
  [nl_NL-pim-medium]=08b58456ca00cf77123826b1712758f99d5fd19ddfb7ec7da8e1a715b047f642
  [uk_UA-ukrainian_tts-medium]=4e96e72917ca9b94edc77d6ccfee03a73f450ba2fc1ca93c2e562bc014e5aa55
  [cs_CZ-jirka-medium]=fb38b1799b7354808227c065efa97b1ffa2b0cde59505babb56a36d35af9c637
  [sv_SE-nst-medium]=d45dd74cbb4eca58694bf04a97e243044092476f28a55ae26424f0653086980a
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

echo "Fetching Piper voices (~1.2 GB total, one-time, hash-verified) → $VOICE_DIR"
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
