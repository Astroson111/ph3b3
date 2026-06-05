import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ph3b3.stories")

STORIES_FILE = Path.home() / "ph3b3_data" / "stories.json"

DEFAULT_STORIES = {
    "ph3b3_stories": [],
    "told_to_ph3b3": [],
    "stream_stories": [],
}

class StoriesModule:
    def __init__(self):
        STORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.stories = self._load()
        log.info(f"Stories loaded. {len(self.stories['told_to_ph3b3'])} told to Ph3b3.")

    def _load(self):
        if STORIES_FILE.exists():
            try:
                with open(STORIES_FILE) as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Could not load stories: {e}")
        return DEFAULT_STORIES.copy()

    def _save(self):
        with open(STORIES_FILE, "w") as f:
            json.dump(self.stories, f, indent=2)

    def add_story_from_person(self, name, story, source="conversation"):
        entry = {
            "from": name,
            "story": story,
            "source": source,
            "date": datetime.now().isoformat(),
        }
        self.stories["told_to_ph3b3"].append(entry)
        self._save()
        return f"Story from {name} saved. Ph3b3 will remember it."

    def add_ph3b3_story(self, title, story, category="general"):
        entry = {
            "title": title,
            "story": story,
            "category": category,
            "date": datetime.now().isoformat(),
        }
        self.stories["ph3b3_stories"].append(entry)
        self._save()
        return f"Story saved: {title}"

    def add_stream_story(self, title, story, timestamp=None):
        entry = {
            "title": title,
            "story": story,
            "timestamp": timestamp or datetime.now().isoformat(),
        }
        self.stories["stream_stories"].append(entry)
        self._save()
        return f"Stream story saved: {title}"

    def recall_stories(self, topic=None):
        results = []
        all_stories = (
            self.stories["told_to_ph3b3"] +
            self.stories["ph3b3_stories"] +
            self.stories["stream_stories"]
        )
        for s in all_stories:
            text = s.get("story","") + s.get("title","")
            if not topic or topic.lower() in text.lower():
                who = s.get("from", s.get("title", "unknown"))
                results.append(f"[{s['date'][:10]}] {who}: {s.get('story','')[:150]}")
        if results:
            return "\n\n".join(results[-5:])
        return "No stories found."

    def summary(self):
        return (
            f"Ph3b3 has {len(self.stories['ph3b3_stories'])} of her own stories, "
            f"{len(self.stories['told_to_ph3b3'])} stories told to her, "
            f"and {len(self.stories['stream_stories'])} stream moments saved."
        )
