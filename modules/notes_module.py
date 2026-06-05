import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ph3b3.notes")
NOTES_DIR = Path.home() / "ph3b3_data" / "notes"

class NotesModule:
    def __init__(self):
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Notes module ready.")

    def add(self, content, tag="general"):
        ts = datetime.now()
        filename = f"{ts.strftime('%Y%m%d_%H%M%S')}_{tag}.txt"
        path = NOTES_DIR / filename
        with open(path, "w") as f:
            f.write(f"DATE: {ts.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"TAG: {tag}\n\n")
            f.write(content)
        return f"Note saved: {filename}"

    def list_notes(self, tag=None):
        files = sorted(NOTES_DIR.glob("*.txt"), reverse=True)
        if tag:
            files = [f for f in files if tag in f.name]
        if not files:
            return "No notes found."
        return "\n".join(f.stem for f in files[:20])

    def read_last(self, tag=None):
        files = sorted(NOTES_DIR.glob("*.txt"), reverse=True)
        if tag:
            files = [f for f in files if tag in f.name]
        if not files:
            return "No notes found."
        return files[0].read_text()

    def search(self, query):
        results = []
        for f in sorted(NOTES_DIR.glob("*.txt"), reverse=True):
            content = f.read_text()
            if query.lower() in content.lower():
                results.append(f"[{f.stem}] {content[:100]}...")
        return "\n\n".join(results[:5]) if results else f"Nothing found for '{query}'"
