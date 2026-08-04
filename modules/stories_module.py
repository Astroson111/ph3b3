import json
import re
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
                results.append(f"[{s['date'][:10]}] {who}: {s.get('story','')}")
        if results:
            hint = ("[Delivery hint: If the user asked you to TELL or READ a story, recite it "
                    "IN FULL below — word for word, all the way to the end — and you may open "
                    "with one or two sentences of your own as a lead-in or transition. Do NOT "
                    "summarize, paraphrase, or shorten the body. If they only asked which "
                    "stories you know, a brief summary is fine.]")
            return hint + "\n\n" + "\n\n".join(results[-5:])
        return "No stories found."

    _TELL_VERBS = ("tell", "read", "recite", "narrate", "story of", "tale of", "hear the")

    @staticmethod
    def _squash(text):
        """Letters and digits only, so word boundaries stop mattering.

        Whisper decides where the spaces go, and it does not always agree with
        the title. "The Lamplighter's Apprentice" came back as "tell me the lamp
        lighter story" — a correct transcript that scored ZERO title hits,
        because "lamplighter" is not a substring of "lamp lighter". The request
        then fell through to inference, which invented a different story
        entirely. Comparing against a squashed copy makes the two spellings the
        same string. Any compound title can hit this, so fix it here rather than
        renaming stories around the speech recogniser.
        """
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    def tellable(self, message):
        """If the message asks to TELL/READ a saved story by title, return (title, full_text).

        Used to recite a saved story verbatim instead of letting inference summarise it.
        Requires a telling verb AND a title match (majority of the title's distinctive
        words, len>=4, present in the message), so ordinary chat never triggers it.
        Title words are matched against the message both as spoken and with all
        spacing removed — see _squash().
        """
        if not message:
            return None
        m = message.lower()
        m_squashed = self._squash(m)
        if not any(v in m for v in self._TELL_VERBS):
            return None
        all_stories = (self.stories["ph3b3_stories"] +
                       self.stories["told_to_ph3b3"] +
                       self.stories["stream_stories"])
        for s in all_stories:
            title = s.get("title") or ""
            words = re.findall(r"[a-z]{4,}", title.lower())
            hits = sum(1 for w in words if w in m or w in m_squashed)
            if words and hits >= max(1, (len(words) + 1) // 2):
                story = s.get("story", "")
                if story:
                    return (title, story)
        return None

    def summary(self):
        return (
            f"Ph3b3 has {len(self.stories['ph3b3_stories'])} of her own stories, "
            f"{len(self.stories['told_to_ph3b3'])} stories told to her, "
            f"and {len(self.stories['stream_stories'])} stream moments saved."
        )
