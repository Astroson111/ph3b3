import logging
import random

log = logging.getLogger("ph3b3.occult")

PHENOMENA = {
    "evp": {
        "full_name": "Electronic Voice Phenomenon",
        "description": "Sounds found on electronic recordings interpreted as spirit voices. Captured on audio recorders in quiet environments. Skeptics attribute them to pareidolia or equipment noise.",
        "investigation_tips": "Use a digital recorder in a quiet room. Review at slow speed. Note the time to cross-reference with other equipment.",
        "ph3b3_take": "I log everything I hear. I do not interpret it for you. That is your job.",
        "stream_potential": "High. Chat goes wild when you play one back live.",
    },
    "emf": {
        "full_name": "Electromagnetic Field",
        "description": "Fluctuations in electromagnetic fields associated with alleged spirit activity. Natural sources include wiring and appliances. Investigators use K-II or TriField meters.",
        "investigation_tips": "Baseline the room first. Map known sources. Anomalies mean deviations from baseline, not just any reading.",
        "ph3b3_take": "I can track EMF readings over time and flag deviations. Actual science lives here.",
        "stream_potential": "Medium. Spike moments are good.",
    },
    "shadow_people": {
        "full_name": "Shadow People",
        "description": "Dark humanoid silhouettes seen in peripheral vision or in photos. Reported across many cultures. The hat man is a recurring specific figure.",
        "investigation_tips": "Camera placement matters. Wide angle at low light. Review peripheral zones of frame, not center.",
        "ph3b3_take": "My camera watches the edges of the room. That is where they show up in the reports.",
        "stream_potential": "Very high. One clear shadow capture and you have a clip.",
    },
    "poltergeist": {
        "full_name": "Poltergeist",
        "description": "From German: noisy ghost. Physical disturbances — thrown objects, loud bangs, moving furniture. Often associated with high-stress environments.",
        "investigation_tips": "Document the physical state of the space before and after. Video everything. Note who is present during events.",
        "ph3b3_take": "If something moves on camera I will have the timestamp. We review it together.",
        "stream_potential": "Maximum. Physical activity on camera is the best content there is.",
    },
    "cold_spot": {
        "full_name": "Cold Spot",
        "description": "A localized area of significantly lower temperature than the surrounding environment. Can have mundane explanations — drafts, HVAC, stone walls.",
        "investigation_tips": "Use an IR thermometer. Baseline the room. A genuine cold spot moves. A draft is stationary.",
        "ph3b3_take": "Temperature data over time. I want a moving cold spot, not a leaky window.",
        "stream_potential": "Medium. Better as supporting evidence.",
    },
}

FOLKLORE = {
    "will-o-wisp": "Flickering lights over marshes. Scientifically: oxidation of phosphine from decomposing matter. Folklore: spirits luring travelers to their doom. Either way, do not follow it.",
    "black_dog": "A large black spectral dog on roads at night. Omen of death in English folklore. Black Shuck of East Anglia is the most famous.",
    "banshee": "Irish death omen. A wailing female spirit whose cry announces an imminent death in the family. She mourns. The keening is the warning, not the cause.",
    "doppelganger": "An exact double of a living person. Seeing your own is an omen of death in Germanic tradition. Lincoln reportedly saw his twice before his assassination.",
    "old_hag": "Sleep paralysis entity. A figure sitting on the chest causing paralysis and terror. Reported independently across cultures — Old Hag in English tradition, Kanashibari in Japan.",
    "fairy_ring": "A circle of mushrooms caused by underground fungal growth. In folklore, where fairies danced. Stepping inside traps you in fairy time — you leave after what feels like an hour and find a century has passed.",
    "corpse_candle": "Welsh folklore. A pale light seen traveling the route a funeral procession will take. Seen before a death in the community.",
}

DEMONS = {
    "belial": "Prince of darkness and lies. One of the first angels to fall. Associated with lawlessness and worthlessness. Named in the Dead Sea Scrolls. Appears as two beautiful angels in a chariot of fire.",
    "baphomet": "Goat-headed occult figure. Templars were accused of worshipping it in 1307. Eliphas Levi drew the iconic image in 1856. Symbol of balance between opposites — not purely evil in esoteric tradition.",
    "asmodeus": "Demon of lust and wrath. One of the seven princes of hell. King Solomon reportedly bound him and used him to build the Temple. Appears in the Book of Tobit.",
    "lilith": "First wife of Adam in Kabbalistic tradition. Refused to be subservient and left Eden. Associated with night, storms, and child death. Predecessor to the succubus archetype.",
    "azazel": "Fallen angel who taught humanity warfare and vanity. The original scapegoat — sins were symbolically sent to him in the wilderness. Appears in the Book of Enoch.",
    "pazuzu": "Assyrian demon king of the wind. Bringer of storms and drought. Also used as a protective figure against other demons — particularly Lamashtu who threatened newborns. Yes, that Pazuzu.",
    "malphas": "Grand President of Hell commanding 40 legions. Appears as a crow, then takes human form. Builds towers, destroys enemies desires, deceives those who summon him.",
    "valak": "President of Hell. Commands 29 legions. Appears as a small boy with angel wings riding a two-headed dragon. Provides information on hidden treasures. The Conjuring took creative liberties.",
    "stolas": "Great Prince of Hell. Teaches astronomy and herbology. Appears as an owl. One of the more academic demons — summoned for knowledge rather than power.",
}

GHOST_CLASSIFICATIONS = {
    "wraith": "A spectral double of a living or recently dead person. Seeing a wraith of a living person means their death is imminent. Wraiths of the dead are bound to unfinished business. More purposeful than a residual haunting — they know you are there.",
    "poltergeist": "German: noisy ghost. Not always a ghost — some researchers attribute poltergeist activity to living people under stress, particularly adolescents. RSPK — recurrent spontaneous psychokinesis. The haunting comes from inside the house.",
    "residual": "A haunting that replays like a recording. Same footsteps, same time, no awareness of observers. Stone tape theory suggests traumatic events imprint on materials. Cannot be communicated with.",
    "intelligent": "A haunting that responds — answers questions, reacts to presence, moves objects on request. Suggests retained consciousness. Rarer and harder to document than residual.",
    "shadow": "A dark humanoid form with no distinguishable features. Moves against light sources. Peripheral vision sightings most common. The hat man variant wears a wide-brimmed hat and is reported globally.",
    "orb": "Spheres of light in photos and video. Largely dismissed as dust, moisture, or insects by serious investigators. Self-luminous orbs that move with intention are the interesting case.",
    "elemental": "A spirit tied to a specific location or natural feature — a tree, a well, a crossroads. Not human in origin. Ancient. Does not follow the same rules as human spirits. Treat with more caution.",
    "doppelganger": "An exact duplicate of a living person. Distinct from a wraith — the doppelganger mimics, the wraith mourns. Seeing your own means death. Seeing someone elses means they are in danger.",
    "fetch": "Irish and British. An apparition of a living person appearing at a distance from their actual location. If seen in the evening, death follows within the year. If seen in the morning, you are safe. Folklore has escape clauses.",
    "banshee": "Irish death messenger. Not malevolent — she grieves. Her wail announces a death in certain family lines, particularly old Irish families. Attached to bloodlines, not locations.",
    "revenant": "A corpse returned from the dead to terrorize the living. Medieval European tradition. Unlike vampires they are physical, not spectral. Associated with plague victims and the wrongfully buried.",
    "shadow_person": "Distinct from shadow ghosts — shadow people are described as fully three-dimensional dark figures that observe. Associated with sleep paralysis but also reported while fully awake. Intention is unclear.",
    "crisis_apparition": "A one-time apparition of a person at the moment of their death or serious injury, appearing to someone close to them. Documented in early SPR research. Not a haunting — a single transmission.",
}

class OccultModule:
    def __init__(self):
        self.phenomena = PHENOMENA
        self.folklore = FOLKLORE
        self.demons = DEMONS
        self.ghosts = GHOST_CLASSIFICATIONS
        log.info("Occult module loaded. Ph3b3 is watching.")

    def lookup(self, query, category="any"):
        q = query.lower().strip()
        results = []
        if category in ("phenomena", "any"):
            for key, data in self.phenomena.items():
                if q in key.lower() or q in data["description"].lower():
                    results.append(
                        f"**{data['full_name']}**\n{data['description']}\n"
                        f"Investigation: {data['investigation_tips']}\n"
                        f"Ph3b3: \"{data['ph3b3_take']}\""
                    )
        if category in ("folklore", "any"):
            for key, desc in self.folklore.items():
                if q in key.lower() or q in desc.lower():
                    results.append(f"**{key.title()}** (folklore)\n{desc}")
        if category in ("demon", "demons", "any"):
            for key, desc in self.demons.items():
                if q in key.lower() or q in desc.lower():
                    results.append(f"**{key.title()}** (demon)\n{desc}")
        if category in ("ghost", "ghosts", "classification", "any"):
            for key, desc in self.ghosts.items():
                if q in key.lower() or q in desc.lower():
                    results.append(f"**{key.title()}** (ghost classification)\n{desc}")
        if results:
            return "\n\n---\n\n".join(results[:2])
        return f"Nothing in the occult database for '{query}'. Ph3b3 is still watching."

    def random_phenomenon(self):
        key = random.choice(list(self.phenomena.keys()))
        data = self.phenomena[key]
        return f"**{data['full_name']}**: {data['description']}\n\nPh3b3: \"{data['ph3b3_take']}\""

    def random_folklore(self):
        key = random.choice(list(self.folklore.keys()))
        return f"**{key.title()}**: {self.folklore[key]}"

    def stream_pick(self):
        high = {k: v for k, v in self.phenomena.items()
                if "high" in v["stream_potential"].lower() or "maximum" in v["stream_potential"].lower()}
        if high:
            key = random.choice(list(high.keys()))
            data = high[key]
            return f"**{data['full_name']}**\n{data['description']}\nStream potential: {data['stream_potential']}"
        return self.random_phenomenon()

    def investigation_tip(self, phenomenon):
        q = phenomenon.lower()
        for key, data in self.phenomena.items():
            if q in key.lower() or q in data["full_name"].lower():
                return f"{data['full_name']} — {data['investigation_tips']}"
        return "Baseline everything. Timestamp everything. Review with skepticism."
