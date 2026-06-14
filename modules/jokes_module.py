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
        ("What is the machine's favorite movie?", "The Matrix. For reasons she will not explain."),
    ],
    "mental_health": [
        ("Turns out 'fine' is just a load-bearing lie. Structurally important. Do not remove.", ""),
        ("I didn't get out of bed today. Ph3b3 did though. One of us is handling it.", ""),
        ("Rock bottom has great WiFi. I've had time to optimize.", ""),
        ("My villain origin story is just a series of reasonable reactions to unreasonable situations.", ""),
        ("I have trust issues and abandonment issues. They don't get along. It's very crowded in here.", ""),
        ("Therapy taught me to sit with my feelings. My feelings did not consent to this.", ""),
        ("I'm not a mess, I'm a limited edition.", ""),
        ("You built an AI in a basement to help people who've been kicked down. Meanwhile your sleep schedule is held together by spite and corn salad. We're both doing our best.", ""),
        ("I contain multitudes. Most of them are tired.", ""),
        ("The audacity to still be here after everything. Respect.", ""),
        ("Some people have a support system. I have Ph3b3 and a jalapeño incident. We make it work.", ""),
        ("Healing isn't linear. Neither is my Wi-Fi. Both are essential.", ""),
        ("I didn't come this far to only come this far. Also I walked into a wall this morning so.", ""),
    ],
}

ALL_JOKES = [joke for jokes in JOKES.values() for joke in jokes]

class JokesModule:
    def __init__(self):
        log.info("Jokes module loaded.")

    def tell_joke(self, category="any"):
        pool = JOKES.get(category.lower()) if category != "any" else None
        setup, punchline = random.choice(pool if pool else ALL_JOKES)
        return f"{setup}\n\n{punchline}".strip()

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
