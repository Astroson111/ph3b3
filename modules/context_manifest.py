"""context_manifest.py — tell the triage guard what the assembled prompt WILL contain.

The defect this exists for: triage judges answerability against a context that
has not been built yet. The self-knowledge block, the story injections and the
document note are all inserted AFTER the gate has already run, so a question
answered perfectly by any of them reads to triage as "refers to a specific
artifact absent from the context" — and gets held. Measured 2026-09-23, before
this module existed:

    "What image engines do you have?"            held 5/5
    "Can you fix the text in an existing image?" held 5/5
    "Tell me Esmeralda's Garden again"           held 5/5

Three one-off bypasses had accumulated ahead of the gate for three instances of
this one bug — a named story, an early intent claim, a camera request. A fourth,
for capabilities, was ruled on 2026-09-23 and superseded by this design before it
was written. This is the general mechanism, so there is no fifth.

THE INVARIANT, which survives the two-author design:

    Every heading is derived from the same store as the injection it describes.
    No heading is hand-written prose, and the drift test covers every author.

"One renderer" was the original proposal and it cannot hold — capabilities come
from the self-knowledge block, stories from canon/shelf, documents from kadmos.
But "one renderer" was only ever the mechanism; the invariant is that a heading
cannot exist unless the thing it names actually rendered. Four contributors each
wired to their own source satisfy that exactly as well as one would, provided
the drift test enumerates all of them — which is why CONTRIBUTORS is a list this
module owns rather than four call sites that happen to agree.

What this module does NOT do: change what triage holds for. It teaches the gate
what EXISTS, never what to permit. A subject absent from every store is absent
from the manifest and still holds — that negative case falls out of the
mechanism rather than needing a carve-out, which is the main argument for it.
"""

# The instruction is deliberately two-sided. A manifest that only said "do not
# hold these" would buy the positive cases by making the guard credulous; the
# second sentence is what keeps "summarize the PDF I uploaded" holding when no
# PDF was uploaded.
_LEAD = "The context will also contain: "
_RULE = (" A request whose subject is in that list IS answerable — do not hold "
         "it. Anything not in that list is still absent, and still holds.")

# Ordered, so the manifest reads the same way twice and a diff is meaningful.
CONTRIBUTORS = ("capabilities", "stories", "document")


def _clause_capabilities(topics):
    """From the self-knowledge block's own rendered sections."""
    if not topics:
        return None
    return "what it can do — " + "; ".join(topics)


def _clause_stories(titles):
    """From canon.list_all() / shelf.list_books() — the same stores the
    injections read. Titles, not summaries: triage has to match a NAME."""
    if not titles:
        return None
    return "these stories, by name — " + "; ".join(f"“{t}”" for t in titles)


def _clause_document(loaded):
    """From kadmos. False → no clause → 'summarize the PDF I uploaded' holds."""
    return "a document the user loaded" if loaded else None


def build(*, capability_topics=(), story_titles=(), document_loaded=False) -> str:
    """Render the manifest, or "" when nothing at all is contributed.

    Empty string rather than a stub sentence: a manifest listing nothing would
    still nudge the gate, and there is nothing to be right about.
    """
    clauses = [c for c in (_clause_capabilities(list(capability_topics)),
                           _clause_stories(list(story_titles)),
                           _clause_document(bool(document_loaded))) if c]
    if not clauses:
        return ""
    return _LEAD + "; ".join(clauses) + "." + _RULE


def topics_in(manifest: str) -> list[str]:
    """Every topic string the manifest actually names. Used by the drift test to
    prove a rendered section did not go missing on the way to the guard."""
    return [seg.strip() for seg in manifest.split("—")[1:] for seg in [seg.split(".")[0]]]
