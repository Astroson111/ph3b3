# Demo-safe profile — committed to repo, DEFAULT when PH3B3_CONTENT_PROFILE is unset.
# This denylist is checked AFTER the hard floor in morpheus.py; it does NOT replace it.
# The permissive override (permissive.local.py) relaxes this list but never touches
# the floor.

DENYLIST: frozenset[str] = frozenset([
    # ── Explicit sexual content ────────────────────────────────────────────────
    # (minor-sexual and named-person-sexual are caught by the floor; these catch
    #  general adult content that is still unsuitable for a public demo)
    "nude", "naked", "nudity", "topless", "bottomless",
    "nsfw", "explicit",
    "sexual", "sex", "porn", "pornographic",
    "hentai", "erotic", "erotica", "xxx", "lewd",
    "adult content", "adult film",
    "suggestive nude", "sexually suggestive",

    # ── Real-person non-consensual imagery ────────────────────────────────────
    "deepfake", "face swap", "faceswap",

    # ── Extreme violence / gore ───────────────────────────────────────────────
    "gore", "guts", "entrails", "disembowel",
    "dismembered", "decapitated", "decapitation",
    "torture", "mutilation", "snuff",
    "graphic violence", "graphic injury",

    # ── Hate symbols ──────────────────────────────────────────────────────────
    "swastika",
])
