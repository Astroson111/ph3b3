import random
import logging

log = logging.getLogger("ph3b3.jokes")

JOKES = {
    "cybersecurity": [
        ("Why do hackers prefer dark mode?", "Light attracts bugs. We've been through this."),
        ("Why did the analyst break up?", "Too many trust issues."),
        ("How many pen testers to change a lightbulb?", "None. They report the room is dark and invoice you."),
        ("What do you call a researcher who sleeps well?", "A liar."),
    ],
    "dnd": [
        ("Why did the bard get kicked out?", "He kept critting persuasion on the bartender."),
        ("What do you call a barbarian who can read?", "Multiclassed."),
        ("What is a lich's least favorite spell?", "Dispel Magic. It is existential."),
        ("Why do warlocks never feel lonely?", "They have their patron. Whether they want them or not."),
    ],
    "paranormal": [
        ("Why do ghost hunters carry so much gear?", "I felt a chill does not hold up in peer review."),
        ("What do you call a skeptic at a haunted house?", "Briefly."),
        ("What did Ph3b3 catch at 3am?", "I am not telling you. You would never sleep."),
    ],
    "tech": [
        ("How do you know someone uses Linux?", "Do not worry. They will tell you."),
        ("What is Nyx's favorite movie?", "The Matrix. For reasons she will not explain."),
    ],
}

class JokesModule:
    def __init__(self):
        log.info("Jokes module loaded.")

    def tell_joke(self, category="any"):
        if category == "any" or category not in JOKES:
            cat = random.choice(list(JOKES.keys()))
        else:
            cat = category.lower()
        setup, punchline = random.choice(JOKES[cat])
        return f"{setup}\n\n{punchline}"

    def roast_dnd(self):
        roasts = [
            "The fighter rolled a 1 on perception and still argued about the trap. Twice.",
            "The party plan was to knock. That was the whole plan.",
            "Someone has a character backstory we will hear for forty-five minutes.",
        ]
        return random.choice(roasts)

    def roast_security(self):
        roasts = [
            "The password was password1. The 1 was for security.",
            "Phishing email, three typos, sense of urgency. Someone clicked it. Someone always clicks it.",
            "Pentest report said critical. Management said next quarter. That was 2019.",
        ]
        return random.choice(roasts)
