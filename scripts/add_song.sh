#!/usr/bin/env bash
# add_song.sh — intake one song into a Dio karaoke library, with contract validation.
# Works identically for the main card, the DIO-BACKUP card, or a staging dir on Nyx —
# only the <dest> changes. See firmware/Ph3b3-Chan/docs/dio_sd_contract.md.
#
# Usage:
#   add_song.sh <dest> <song.wav> [<song.lrc>]
#     <dest>      mount point or directory (a "karaoke/" subdir is created under it)
#                 e.g. /media/astroson/6566-3235   (main 239 GB card)
#                      /media/astroson/DIO-BACKUP   (16 GB backup)
#                      ~/ph3b3_data                 (staging)
#     <song.wav>  source audio; converted to the canonical spec if it isn't already
#     <song.lrc>  optional synced-lyrics file (validated if given)
#
# Add a song to BOTH cards = two invocations, same procedure:
#   add_song.sh /media/astroson/6566-3235 mytune.wav mytune.lrc
#   add_song.sh /media/astroson/DIO-BACKUP mytune.wav mytune.lrc
#
# NOTE (not implemented tonight): a --sync mode could mirror main→backup with e.g.
#   rsync -a --delete /media/astroson/6566-3235/karaoke/ /media/astroson/DIO-BACKUP/karaoke/
# Deliberately left as a note so a one-off swap can't accidentally wipe a card.

set -euo pipefail

# Canonical WAV spec (contract: PCM 16-bit; canonical rate/channels for consistency)
SPEC_CODEC=pcm_s16le; SPEC_RATE=44100; SPEC_CH=2; SPEC_BITS=16

die(){ echo "add_song: ERROR: $*" >&2; exit 1; }

[ $# -ge 2 ] || die "usage: add_song.sh <dest> <song.wav> [<song.lrc>]"
DEST=$1; WAV=$2; LRC=${3:-}
command -v ffprobe >/dev/null || die "ffprobe not found (install ffmpeg)"

[ -d "$DEST" ] || die "dest '$DEST' is not a directory / not mounted"
[ -f "$WAV" ]  || die "wav '$WAV' not found"
case "${WAV,,}" in *.wav) ;; *) die "source must be a .wav" ;; esac

stem=$(basename "$WAV"); stem=${stem%.*}
KDIR="$DEST/karaoke"; mkdir -p "$KDIR"
OUT="$KDIR/$stem.wav"

# --- validate / normalize the WAV to the canonical spec ---
spec=$(ffprobe -v error -select_streams a:0 \
        -show_entries stream=codec_name,sample_rate,channels,bits_per_sample \
        -of csv=p=0 "$WAV" 2>/dev/null || true)
want="$SPEC_CODEC,$SPEC_RATE,$SPEC_CH,$SPEC_BITS"
if [ "$spec" = "$want" ]; then
    echo "[spec] $stem.wav already $want — copying verbatim"
    cp -f "$WAV" "$OUT"
else
    command -v ffmpeg >/dev/null || die "spec is '$spec' (need '$want') but ffmpeg not found to convert"
    echo "[spec] $stem.wav is '$spec' → converting to '$want'"
    ffmpeg -v error -y -i "$WAV" -acodec "$SPEC_CODEC" -ar "$SPEC_RATE" -ac "$SPEC_CH" "$OUT"
fi

# --- verify what actually landed matches the contract's hard checks (PCM/16-bit) ---
got=$(ffprobe -v error -select_streams a:0 \
       -show_entries stream=codec_name,sample_rate,channels,bits_per_sample \
       -of csv=p=0 "$OUT" 2>/dev/null)
[ "$got" = "$want" ] || die "post-write spec mismatch: got '$got' want '$want'"
echo "[ok]  $OUT  ($got)"

# --- optional LRC: validate it parses, then place as <stem>.lrc ---
if [ -n "$LRC" ]; then
    [ -f "$LRC" ] || die "lrc '$LRC' not found"
    n=$(grep -cE '^\[[0-9]+:[0-9]+(\.[0-9]+)?\]' "$LRC" || true)
    [ "$n" -ge 1 ] || die "lrc '$LRC' has 0 parseable [mm:ss.xx] lines"
    cp -f "$LRC" "$KDIR/$stem.lrc"
    echo "[ok]  $KDIR/$stem.lrc  ($n timed lines)"
else
    echo "[note] no .lrc given — '$stem' will play without synced lyrics (contract-legal)"
fi

sync
echo "[done] '$stem' added to $DEST/karaoke  ($(ls -1 "$KDIR"/*.wav 2>/dev/null | wc -l) songs on this dest)"
