"""
Sources Thoth will not take from, and why — recorded, not remembered.

NAMED source_policy AND NOT sources: `thoth/sources/` already exists as a
package holding the per-work adapters. Two different meanings of "sources" one
import apart is the `canon` collision this package bans by name, and the first
version of this file was silently shadowed by that directory.

Astro, 2026-09-18: "Lets not pirate anything over here. I want to run this as
clean as I can."

That is a standing position, so it is written as a mechanism rather than a habit.
Everything below refuses at MANIFEST LOAD, before any network call, because a
rule that only lives in a reviewer's head is one careless commit from being
gone — and the failures this guards against all LOOK correct at a glance. A
plagiarised edition has the right title. A blocked host returns a plausible 403
that a retry loop would paper over.

TWO KINDS OF REFUSAL, kept apart because they are different wrongs:

  BLOCKED HOSTS      The publisher does not permit automated access, or claims
                     rights over the digitisation itself. Their text may be
                     public domain and it is still not ours to take this way.
                     Working around a block is the thing being refused, not the
                     copyright question.

  TAINTED EDITIONS   The work is public domain; THIS rendering of it is someone
                     else's stolen labour. Storing it would put a pirated text
                     in the library under an honest author's name, which is
                     worse than not having the text at all.
"""
from __future__ import annotations

from urllib.parse import urlparse


class RefusedSource(ValueError):
    """A source this library will not take from."""


# Host → why. Checked against the registered domain, so subdomains are covered.
BLOCKED_HOSTS: dict[str, str] = {
    "sacred-texts.com": (
        "Returns 403 to automated requests on every path, including its own "
        "scrape. subdomain, and claims copyright on its HTML markup and on the "
        "collection (© J.B. Hare) separately from the public-domain texts. "
        "Reading it in a browser is fine; taking it programmatically is not, "
        "and spoofing a user agent to get past the block is the part we refuse."
    ),
}

# Gutenberg ebook id → why that specific edition is refused. The NUMBER is the
# key because the title is exactly what makes these dangerous: they are shelved
# under the name of the author they took from.
TAINTED_EDITIONS: dict[str, str] = {
    "43548": (
        "de Laurence, 'The Illustrated Key to the Tarot' — a near-verbatim lift "
        "of A. E. Waite's 'Pictorial Key to the Tarot' (1910), published without "
        "his permission. Waite's original is public domain and welcome; this "
        "edition is the theft of it, and ingesting it would file a pirated text "
        "under Waite's name."
    ),
}

# Sources whose terms have been READ and found clean. Recorded so the next
# person does not have to re-derive it, and so 'we checked' is a fact with a
# date rather than an impression.
CLEARED_HOSTS: dict[str, str] = {
    "archive.org": (
        "Read 2026-09-18. robots.txt disallows only /control/ and /report/, sets "
        "no crawl-delay and blocks no user-agent, so automated access is "
        "permitted. Their own guidance ('Let us serve you, but don't bring us "
        "down', 2023-05-29) asks bulk users to start slowly and ramp up, to "
        "contact info@archive.org before a large project, and — if blocked — to "
        "reach out rather than retry. UNLIKE GUTENBERG, clearing the HOST is "
        "not enough: the Archive hosts in-copyright lending scans beside public "
        "domain ones, so every item must pass archive_item_ok() as well."
    ),
    "gutenberg.org": (
        "Read 2026-09-18. Public-domain items may be redistributed, modified "
        "and used commercially — 'nobody can grant, or withhold, permission to "
        "do with this item as you please.' The trademark is the only "
        "restriction and the text may be redistributed without it. No "
        "restriction on storage in a private database."
    ),
}


def _host(url: str) -> str:
    net = (urlparse(url).hostname or "").lower()
    parts = net.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else net


def gutenberg_id(url: str) -> str | None:
    """The ebook number in a Gutenberg URL, whichever of their shapes it uses."""
    import re
    m = re.search(r"/(?:ebooks|files|cache/epub)/(\d+)", url or "")
    return m.group(1) if m else None


def check_source(url: str, where: str = "") -> None:
    """Raise RefusedSource if this URL is one we will not take from.

    Called at manifest load, so a refused source can never reach a downloader.
    """
    if not url:
        return
    host = _host(url)
    if host in BLOCKED_HOSTS:
        raise RefusedSource(
            f"{where + ': ' if where else ''}{host} is not a source this library "
            f"takes from. {BLOCKED_HOSTS[host]}")
    eid = gutenberg_id(url)
    if eid and eid in TAINTED_EDITIONS:
        raise RefusedSource(
            f"{where + ': ' if where else ''}Gutenberg #{eid} is refused. "
            f"{TAINTED_EDITIONS[eid]}")


def cleared(url: str) -> bool:
    """True when this host's terms have been read and recorded as clean.

    Deliberately NOT enforced — a host being unlisted means nobody has checked
    it yet, which is a prompt to go and read, not a verdict.
    """
    return _host(url) in CLEARED_HOSTS


# ── archive.org is cleared per HOST but must be checked per ITEM ─────────────
# Gutenberg curates: everything there is public domain, so the host check is the
# whole check. The Archive does not — it holds in-copyright lending scans in the
# same shelf space as public domain ones, and they look identical from the URL.
#
# THE TRAP, found while checking Heath's Euclid. Both of these have a
# `<id>_djvu.txt` full-text derivative listed in their files array:
#
#   thirteenbookseu02heibgoog   1908, NOT_IN_COPYRIGHT, collection americana
#   euclidselementsa0000eucl    2002 reprint, access-restricted-item: true,
#                               collections internetarchivebooks + printdisabled
#
# So "a full text file exists" is NOT the test — the second is a modern
# in-copyright translation digitised for print-disabled lending, and a scraper
# keying on the file pattern would take it without noticing. The metadata is
# the test.

RESTRICTED_COLLECTIONS = frozenset({
    "printdisabled",        # digitised under a disability exception, not for us
    "inlibrary",            # controlled digital lending
    "internetarchivebooks",  # the lending shelf
})


def archive_item_ok(meta: dict) -> None:
    """Raise RefusedSource unless this archive.org item is free to take.

    `meta` is the JSON from https://archive.org/metadata/<identifier>.
    Three independent reasons to refuse, checked in order of how loudly they
    say no.
    """
    md = (meta or {}).get("metadata") or {}
    ident = md.get("identifier", "?")

    if str(md.get("access-restricted-item", "")).lower() == "true":
        raise RefusedSource(
            f"archive.org item {ident!r} is access-restricted "
            f"(access-restricted-item: true). That is a lending or "
            f"print-disabled scan, not a public-domain copy — a _djvu.txt "
            f"derivative existing does not make it ours to take.")

    cols = md.get("collection") or []
    if isinstance(cols, str):
        cols = [cols]
    bad = sorted(set(cols) & RESTRICTED_COLLECTIONS)
    if bad:
        raise RefusedSource(
            f"archive.org item {ident!r} sits in {', '.join(bad)} — the "
            f"controlled-lending shelves. Public-domain scans live in open "
            f"collections such as 'americana'.")

    status = str(md.get("possible-copyright-status", "")).upper()
    if status and status != "NOT_IN_COPYRIGHT":
        raise RefusedSource(
            f"archive.org item {ident!r} reports copyright status {status!r}. "
            f"Only NOT_IN_COPYRIGHT items are taken.")
    if not status:
        raise RefusedSource(
            f"archive.org item {ident!r} states no copyright status. Silence is "
            f"not permission — find a copy that says NOT_IN_COPYRIGHT.")


# Their stated etiquette, as numbers a client can actually honour rather than a
# paragraph someone remembers reading.
ARCHIVE_ETIQUETTE = {
    "concurrency": 1,          # start slowly, ramp up — so: one at a time
    "min_delay_s": 2.0,        # be a guest, not a load test
    "on_429": "stop",          # "don't just start again, reach out"
    "contact_first_over": 50,  # items; "starting a large project? contact us"
    "contact": "info@archive.org",
}
