#!/usr/bin/env bash
# Prometheus corpus fetch — the ONLY network call this module ever makes.
#
# Run by the owner, by hand, once. Never by Phoebe, never on a timer, never from
# a route. If this script is running, a human started it.
#
#   ./fetch.sh              fetch what is missing, verify every checksum
#   ./fetch.sh --record     fetch and WRITE observed checksums into manifest.yaml
#   ./fetch.sh --dry-run    say what would happen, touch nothing
#   ./fetch.sh --zims       include the Kiwix ZIMs (large — tens of GB)
#   ./fetch.sh --only ID    one source
#
# TRUST ON FIRST USE, STATED PLAINLY: --record protects you against a file
# changing later. It does NOT protect you against the first download being
# wrong. Review every URL before the first --record, and review the hashes it
# writes before committing them. A checksum recorded from a bad download welds
# the bad download in.
#
# Idempotent: a source whose file is present and whose checksum matches is
# skipped. Nothing is ever partially installed — downloads land in a temp file
# and are moved into place only after verification.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$HERE/manifest.yaml"
PY="${PH3B3_PY:-$HERE/../.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"

RECORD=0; DRY=0; WANT_ZIMS=0; ONLY=""; ACCEPT_UNVERIFIED=0
while [ $# -gt 0 ]; do
  case "$1" in
    --record) RECORD=1 ;;
    --dry-run) DRY=1 ;;
    --zims) WANT_ZIMS=1 ;;
    --only) ONLY="${2:-}"; shift ;;
    --accept-unverified) ACCEPT_UNVERIFIED=1 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -f "$MANIFEST" ] || { echo "FATAL: no manifest at $MANIFEST" >&2; exit 1; }
command -v curl >/dev/null || { echo "FATAL: curl not found" >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "FATAL: sha256sum not found" >&2; exit 1; }

echo "── Prometheus fetch ─────────────────────────────────────────────"
echo "This is a NETWORK operation, and the only one Prometheus performs."
echo "manifest: $MANIFEST"
[ "$DRY" = 1 ] && echo "DRY RUN — nothing will be written."
[ "$RECORD" = 1 ] && echo "RECORD MODE — observed checksums will be written into the manifest."
echo

# The manifest is YAML; parse it with the interpreter that already has PyYAML
# rather than reimplementing YAML in bash. Emits TSV: id, url, path, sha, verified.
read_manifest() {
  "$PY" - "$MANIFEST" "$WANT_ZIMS" "$ONLY" <<'PYEOF'
import sys, yaml
mf, want_zims, only = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
m = yaml.safe_load(open(mf, encoding="utf-8")) or {}
rows = list(m.get("sources") or [])
if want_zims:
    rows += list(m.get("zims") or [])
for s in rows:
    if only and s.get("id") != only:
        continue
    print("\t".join([
        str(s.get("id") or ""), str(s.get("url") or ""), str(s.get("path") or ""),
        str(s.get("sha256") or ""), "1" if s.get("verified_url") else "0",
        str(s.get("sha256_url") or ""),
    ]))
PYEOF
}

CORPUS="$HERE/$("$PY" -c "import yaml,sys;print((yaml.safe_load(open(sys.argv[1],encoding='utf-8')) or {}).get('corpus_dir','corpus'))" "$MANIFEST")"

fail=0; done_n=0; skipped=0; recorded=0
# Initialised empty on purpose; guarded by $recorded below rather than by
# ${#array[@]}, which trips `set -u` on an empty array.
RECORDED_IDS=(); RECORDED_SHAS=()

while IFS=$'\t' read -r id url relpath sha verified shaurl; do
  [ -n "$id" ] || continue
  dest="$CORPUS/$relpath"

  if [ -z "$url" ]; then
    echo "  $id: NO URL in manifest — Astro must supply it. Skipping."
    skipped=$((skipped+1)); continue
  fi

  if [ "$verified" != "1" ] && [ "$ACCEPT_UNVERIFIED" != "1" ]; then
    echo "  $id: url is not marked verified_url — refusing."
    echo "      Review the URL, set verified_url: true, or pass --accept-unverified."
    skipped=$((skipped+1)); continue
  fi

  # A publisher-supplied checksum beats trust-on-first-use outright: it is an
  # independent assertion about what the file should be, made before we fetched
  # it. Kiwix and most distro-style mirrors publish one next to the artifact.
  # Where the manifest gives a sha256_url, fetch it and use it as the expected
  # value — this is NOT recorded from our own download, so it detects a bad
  # first fetch, which --record cannot.
  if [ -z "$sha" ] && [ -n "$shaurl" ]; then
    if pub="$(curl -fsSL --connect-timeout 20 --max-time 120 "$shaurl" 2>/dev/null)"; then
      # Files are usually "<hash>  <filename>"; take the first 64-hex token.
      pub="$(printf '%s' "$pub" | grep -oE '[0-9a-fA-F]{64}' | head -1 | tr 'A-F' 'a-f')"
      if [ -n "$pub" ]; then
        sha="$pub"
        echo "  $id: using publisher checksum from $shaurl"
      else
        echo "  $id: sha256_url returned nothing hash-shaped — falling back."
      fi
    else
      echo "  $id: could not fetch sha256_url — falling back."
    fi
  fi

  # Already present and matching? Nothing to do — this is what makes re-running safe.
  if [ -f "$dest" ] && [ -n "$sha" ]; then
    have="$(sha256sum "$dest" | cut -d' ' -f1)"
    if [ "$have" = "$sha" ]; then
      echo "  $id: present, checksum OK"
      continue
    fi
    echo "  $id: CHECKSUM MISMATCH on the file already on disk."
    echo "      expected $sha"
    echo "      found    $have"
    echo "      Refusing to overwrite. Investigate before deleting anything."
    fail=$((fail+1)); continue
  fi

  if [ "$DRY" = 1 ]; then
    echo "  $id: would fetch $url -> $dest"
    continue
  fi

  mkdir -p "$(dirname "$dest")"
  tmp="$(mktemp "${dest}.part.XXXXXX")"
  echo "  $id: fetching…"
  if ! curl -fsSL --retry 2 --connect-timeout 20 --max-time 7200 -o "$tmp" "$url"; then
    echo "      DOWNLOAD FAILED — leaving no partial file."
    rm -f "$tmp"; fail=$((fail+1)); continue
  fi

  got="$(sha256sum "$tmp" | cut -d' ' -f1)"
  if [ -n "$sha" ]; then
    if [ "$got" != "$sha" ]; then
      echo "      CHECKSUM MISMATCH — refusing to install."
      echo "      expected $sha"
      echo "      got      $got"
      rm -f "$tmp"; fail=$((fail+1)); continue
    fi
    mv "$tmp" "$dest"; echo "      ok, verified"
    done_n=$((done_n+1))
  elif [ "$RECORD" = 1 ]; then
    mv "$tmp" "$dest"
    RECORDED_IDS+=("$id"); RECORDED_SHAS+=("$got")
    echo "      installed, recording sha256 $got"
    recorded=$((recorded+1)); done_n=$((done_n+1))
  else
    rm -f "$tmp"
    echo "      no checksum in manifest and not in --record mode — refusing to install."
    echo "      Re-run with --record once you have reviewed the URL."
    skipped=$((skipped+1))
  fi
done < <(read_manifest)

# Write recorded hashes back in one pass, preserving comments and layout by
# editing the matching sha256 line under each id rather than re-dumping the YAML.
if [ "$recorded" -gt 0 ]; then
  "$PY" - "$MANIFEST" "${RECORDED_IDS[@]}" --shas "${RECORDED_SHAS[@]}" <<'PYEOF'
import re, sys
mf = sys.argv[1]
rest = sys.argv[2:]
cut = rest.index("--shas")
ids, shas = rest[:cut], rest[cut + 1:]
text = open(mf, encoding="utf-8").read()
for i, s in zip(ids, shas):
    # Find "- id: <i>" then the first "sha256:" line after it, and fill it in.
    m = re.search(rf"(- id:\s*{re.escape(i)}\b.*?\n)((?:\s+\w[^\n]*\n)*?)(\s+sha256:\s*)(null|\"\"|)\s*\n",
                  text, re.S)
    if not m:
        print(f"  WARNING: could not place sha256 for {i} — record it by hand", file=sys.stderr)
        continue
    text = text[:m.start(4)] + s + text[m.end(4):]
open(mf, "w", encoding="utf-8").write(text)
print(f"  wrote {len(ids)} checksum(s) into the manifest")
PYEOF
  echo
  echo "  REVIEW THOSE HASHES before committing. They assert only that the bytes"
  echo "  you just downloaded are the bytes you will keep — not that they are the"
  echo "  right document."
fi

echo
echo "── done: $done_n fetched, $skipped skipped, $fail failed ──"
[ "$fail" -eq 0 ] || { echo "FAILURES ABOVE — nothing was partially installed." >&2; exit 1; }
[ "$DRY" = 1 ] && exit 0
echo "Next: ./ingest.py    (builds index.db; blacklisted sections are dropped there)"
