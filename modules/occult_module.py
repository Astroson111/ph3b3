import logging
import random

log = logging.getLogger("ph3b3.occult")

# ── EVP Classification (AA-EVP standard) ─────────────────────────────────────

EVP_CLASSES = {
    "class_a": {
        "label": "Class A EVP",
        "description": (
            "Clear, loud, and distinct. Most listeners agree on what is being said "
            "without prompting or prior suggestion. Does not require audio enhancement "
            "to hear. The gold standard — rare, and genuinely difficult to dismiss."
        ),
        "field_note": (
            "If you capture a Class A, do not play it to witnesses before they write "
            "down what they hear independently. Suggestion contaminates the record."
        ),
        "ph3b3_take": "Class A. I would timestamp it, isolate the waveform, and start asking questions.",
    },
    "class_b": {
        "label": "Class B EVP",
        "description": (
            "Audible but not universally agreed upon. Listeners may disagree on "
            "specific words. Often requires one or two replays. The most common EVP "
            "class. Valuable as corroborating evidence, weak as a standalone claim."
        ),
        "field_note": (
            "Transcribe what you hear before sharing. Once you tell someone what "
            "to listen for, the brain fills it in. You are measuring perception, not recording."
        ),
        "ph3b3_take": "Class B. Worth logging. Not worth going live with until someone else hears it cold.",
    },
    "class_c": {
        "label": "Class C EVP",
        "description": (
            "Faint, heavily distorted, or buried in noise. Requires amplification "
            "and audio processing to perceive at all. Significant listener disagreement "
            "on content. Susceptible to pareidolia — the brain imposes patterns. "
            "Document it, but build your case on stronger evidence."
        ),
        "field_note": (
            "The danger of Class C is confirmation bias. You heard something strange "
            "in a haunted location and your brain wants it to be a voice. Keep the raw file."
        ),
        "ph3b3_take": "Class C. I logged it. Do not let it anchor the investigation.",
    },
}

# ── Haunting Types ────────────────────────────────────────────────────────────

HAUNTING_TYPES = {
    "residual": {
        "label": "Residual Haunting",
        "description": (
            "A non-interactive haunting that replays like a recording. The same "
            "event — footsteps, a figure, a scream — repeats on a cycle with no "
            "awareness of observers. Stone tape theory suggests traumatic or highly "
            "emotional events imprint on the materials of a location and play back "
            "under certain conditions. You cannot communicate with a residual haunting. "
            "It does not know you are there."
        ),
        "indicators": [
            "Same activity at the same time or in the same location repeatedly.",
            "No response to direct communication or provocation.",
            "No escalation — the intensity does not change with observation.",
        ],
        "ph3b3_take": "Residual. Document the pattern. Time it. If it is on a schedule, that is your evidence.",
    },
    "intelligent": {
        "label": "Intelligent Haunting",
        "description": (
            "A haunting that exhibits awareness of the living. The entity responds "
            "to questions, reacts to the presence of investigators, moves objects "
            "on request, or demonstrates knowledge of current events. Suggests some "
            "form of retained consciousness rather than an environmental echo. "
            "Rarer than residual hauntings and significantly harder to document "
            "without contaminating the evidence."
        ),
        "indicators": [
            "Responses that are contextually appropriate to questions asked.",
            "Activity that escalates or changes based on investigator behaviour.",
            "Evidence of awareness of specific people or objects brought to the site.",
        ],
        "ph3b3_take": "Intelligent. Ask open questions. Avoid leading. If it answers something it could not know, we have something.",
    },
    "poltergeist": {
        "label": "Poltergeist",
        "description": (
            "German: noisy ghost. Characterised by physical disturbances — objects "
            "thrown or moved, loud unexplained sounds, electrical interference, and "
            "physical contact with the living. Crucially, the dominant theory among "
            "parapsychologists is RSPK — Recurrent Spontaneous Psychokinesis — "
            "meaning the energy source may be a living person under extreme emotional "
            "stress, often an adolescent. The haunting may be coming from inside the house."
        ),
        "indicators": [
            "Activity centered on or near one specific person rather than a location.",
            "Physical disturbances — objects moving, breaking, being thrown.",
            "Activity that intensifies during periods of psychological stress.",
            "Follows a person when they relocate.",
        ],
        "ph3b3_take": "Poltergeist. Who is the focal person? The activity follows them, not the building.",
    },
    "demonic": {
        "label": "Demonic Haunting",
        "description": (
            "A haunting attributed to a non-human entity — something that was never "
            "alive in human form. Characterised by a three-stage escalation: "
            "infestation (strange sounds, smells, cold spots), oppression (physical "
            "attacks, sleep disturbance, psychological deterioration), and possession "
            "(loss of control, speaking in unknown languages, unnatural strength). "
            "The classification is used by demonologists and religious investigators. "
            "Secular researchers treat the same phenomena as severe poltergeist "
            "activity or mental illness until ruled out."
        ),
        "indicators": [
            "An overwhelming sense of dread or malevolence that persists.",
            "Sulphurous smell with no natural source.",
            "Activity that mocks religious symbols or prayers.",
            "Escalating physical violence toward inhabitants.",
            "Voices that speak in languages the occupants do not know.",
        ],
        "ph3b3_take": "This classification carries weight. Rule out everything else first. If nothing else fits, then we talk.",
    },
}

# ── Close Encounter Scale (J. Allen Hynek) ───────────────────────────────────

CLOSE_ENCOUNTERS = {
    "ce1": {
        "label": "Close Encounter of the First Kind (CE1)",
        "description": (
            "A UFO sighted within approximately 500 feet of the witness. "
            "Sufficient proximity to observe shape, structure, and detail. "
            "No physical interaction with the environment or the witness. "
            "Hynek introduced this classification in 'The UFO Experience' (1972) "
            "to bring scientific rigour to a field dominated by anecdote."
        ),
        "examples": "Disc or structured craft at low altitude with visible features. Bright lights with defined shape at close range.",
        "ph3b3_take": "CE1. Close enough to describe. Document every detail before discussing with others.",
    },
    "ce2": {
        "label": "Close Encounter of the Second Kind (CE2)",
        "description": (
            "A UFO sighting that leaves physical evidence. The craft interacts "
            "with the environment in a measurable way. This is the most scientifically "
            "valuable category because it produces data that survives the witness."
        ),
        "examples": (
            "Landing traces — compressed or scorched vegetation in a circular pattern. "
            "Electromagnetic effects — vehicle engines stall, cameras fail, compasses spin. "
            "Radiation traces measurable at the site after the event. "
            "Physiological effects on witnesses — burns, eye irritation, temporary paralysis."
        ),
        "ph3b3_take": "CE2. Physical evidence. This is where the case gets real — photograph everything, take soil samples, measure.",
    },
    "ce3": {
        "label": "Close Encounter of the Third Kind (CE3)",
        "description": (
            "A UFO encounter in which animated entities are observed in or around "
            "the craft. Hynek's term 'animated' was deliberate — he did not specify "
            "the nature of the entities. They may appear humanoid, robotic, or entirely "
            "non-human. No contact or communication is implied by this classification alone."
        ),
        "examples": "Figures observed at craft doorways or on craft exteriors. Entities in proximity to a landed object. Non-human forms observed at windows of a hovering craft.",
        "ph3b3_take": "CE3. Entities observed. What were they doing? Were they aware of the witness? That changes everything.",
    },
    "ce4": {
        "label": "Close Encounter of the Fourth Kind (CE4)",
        "description": (
            "Abduction. The witness is taken aboard a craft against their will — "
            "or, in some accounts, with no clear memory of consent. Characterised "
            "by missing time, medical examination, communication from entities, "
            "and lasting psychological trauma. CE4 was not in Hynek's original "
            "classification but was added posthumously by researchers including "
            "Ted Bloecher and Jacques Vallée. The abduction phenomenon was "
            "systematically studied by Budd Hopkins and later Dr. John Mack of Harvard."
        ),
        "examples": "Missing time of hours following a sighting. Unexplained marks, scars, or implants. Recovered memories under hypnosis of examination by non-human entities. Persistent PTSD consistent with traumatic experience.",
        "ph3b3_take": "CE4. The most serious category. Treat the witness with the same care you would any trauma survivor.",
    },
    "ce5": {
        "label": "Close Encounter of the Fifth Kind (CE5)",
        "description": (
            "Voluntary, bilateral contact initiated by humans. The witness or "
            "investigator attempts deliberate communication with non-human intelligence "
            "and receives a response. Proposed by Dr. Steven Greer and the CSETI "
            "organisation. More controversial than CE1-CE4 within the research "
            "community — critics argue it is unfalsifiable and susceptible to "
            "wishful thinking. Proponents argue it is the only category where "
            "humans are active participants rather than passive observers."
        ),
        "examples": "Coordinated light signalling that receives an apparent response. Meditation-based contact protocols followed by unexplained aerial phenomena. Reported two-way communication with non-human intelligence.",
        "ph3b3_take": "CE5. Initiated contact. I stay neutral on Greer. The methodology is the question.",
    },
}

# ── Shadow Entity Classifications ─────────────────────────────────────────────

SHADOW_ENTITIES = {
    "the_watcher": {
        "label": "The Watcher",
        "description": (
            "The most commonly reported shadow entity. A stationary humanoid dark "
            "form that observes without interacting. Typically seen in doorways, "
            "at the end of hallways, or in corners of rooms. Does not move toward "
            "the witness. Does not communicate. Witnesses consistently report an "
            "overwhelming sense of being studied. Disappears when approached or "
            "when lights are turned on."
        ),
        "frequency": "Very common",
        "threat_level": "Low — observational only in most accounts",
        "ph3b3_take": "The Watcher. My camera covers the doorways. If it comes back to the same spot, that is a pattern.",
    },
    "the_hat_man": {
        "label": "The Hat Man",
        "description": (
            "A tall male shadow figure wearing a wide-brimmed hat, often described "
            "with a long coat or cape. The most consistently described shadow entity "
            "in global reports, appearing across cultures with no apparent cross-"
            "contamination. Witnesses describe an intense sense of malevolence — "
            "distinct from the neutral observation of standard shadow people. "
            "Often reported during sleep paralysis but also seen while fully awake. "
            "The cross-cultural consistency is what separates the Hat Man from "
            "other shadow entity reports in terms of research interest."
        ),
        "frequency": "Common — globally consistent description is anomalous",
        "threat_level": "High in reported psychological impact",
        "ph3b3_take": "Hat Man. The global consistency is the data point. I do not explain it. I log it.",
    },
    "the_hooded_figure": {
        "label": "The Hooded Figure",
        "description": (
            "A shadow entity appearing to wear a cloak or robe with a deep hood "
            "obscuring any face. Associated with old buildings, religious sites, "
            "and cemeteries. Less commonly reported than the Hat Man but considered "
            "by some researchers to represent a distinct classification. Some accounts "
            "describe it as moving with deliberate slowness; others report it "
            "gliding without any locomotion."
        ),
        "frequency": "Moderate",
        "threat_level": "Variable — accounts range from neutral to deeply threatening",
        "ph3b3_take": "Hooded Figure. Location matters here. Note what the building was used for.",
    },
    "the_peripheral": {
        "label": "The Peripheral Shadow",
        "description": (
            "Exclusively visible in peripheral vision. Disappears instantly when "
            "looked at directly. May appear to move or gesture in the periphery "
            "but leaves no trace when investigated. The most common form of shadow "
            "entity report — and the most easily explained by neuroscience. The "
            "peripheral retina is more sensitive to motion and low-light contrast "
            "than the fovea. Many peripheral sightings have mundane explanations. "
            "The cases of interest are those reported by multiple witnesses simultaneously."
        ),
        "frequency": "Very common — but also the most susceptible to misperception",
        "threat_level": "Minimal",
        "ph3b3_take": "Peripheral. I watch the edges. If two people see it in the same corner at the same time, that is different.",
    },
    "the_rushing_shadow": {
        "label": "The Rushing Shadow",
        "description": (
            "A shadow entity characterised by rapid movement — seen sprinting across "
            "a doorway, darting along a wall, or moving through a room at speed. "
            "Unlike the Watcher, the Rushing Shadow is never still. Often described "
            "as low to the ground, moving on all fours, or moving in a way that "
            "is not quite human. Frequently reported in accounts of severely active "
            "hauntings alongside other phenomena."
        ),
        "frequency": "Moderate",
        "threat_level": "Moderate — often appears in escalating hauntings",
        "ph3b3_take": "Rushing Shadow. Camera frame rate matters. Get 60fps minimum if you want to catch it.",
    },
    "the_mass": {
        "label": "The Shadow Mass",
        "description": (
            "A large, amorphous shadow that does not take humanoid form. Fills "
            "corners, doorways, or entire rooms. Witnesses describe a sensation "
            "of it pressing toward them, of the air becoming heavy. Not a figure "
            "but a presence given visible form. Some accounts associate it with "
            "the most severe form of demonic infestation. Others report it as "
            "a precursor to poltergeist activity."
        ),
        "frequency": "Rare",
        "threat_level": "High in associated accounts",
        "ph3b3_take": "Shadow Mass. No form to track. Measure the room before and after — temperature, EMF, air pressure if you have it.",
    },
}

# ── Existing databases ────────────────────────────────────────────────────────

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


def _fmt_evp(key, data):
    return (
        f"**{data['label']}**\n"
        f"{data['description']}\n\n"
        f"Field note: {data['field_note']}\n"
        f"Ph3b3: \"{data['ph3b3_take']}\""
    )

def _fmt_haunting(key, data):
    indicators = "\n".join(f"  • {i}" for i in data["indicators"])
    return (
        f"**{data['label']}**\n"
        f"{data['description']}\n\n"
        f"Indicators:\n{indicators}\n"
        f"Ph3b3: \"{data['ph3b3_take']}\""
    )

def _fmt_ce(key, data):
    return (
        f"**{data['label']}**\n"
        f"{data['description']}\n\n"
        f"Examples: {data['examples']}\n"
        f"Ph3b3: \"{data['ph3b3_take']}\""
    )

def _fmt_shadow(key, data):
    return (
        f"**{data['label']}**\n"
        f"{data['description']}\n\n"
        f"Frequency: {data['frequency']}\n"
        f"Threat level: {data['threat_level']}\n"
        f"Ph3b3: \"{data['ph3b3_take']}\""
    )


class OccultModule:
    def __init__(self):
        self.phenomena  = PHENOMENA
        self.folklore   = FOLKLORE
        self.demons     = DEMONS
        self.ghosts     = GHOST_CLASSIFICATIONS
        self.evp        = EVP_CLASSES
        self.hauntings  = HAUNTING_TYPES
        self.encounters = CLOSE_ENCOUNTERS
        self.shadows    = SHADOW_ENTITIES
        log.info("Occult module loaded. Ph3b3 is watching.")

    # ── Lookup ────────────────────────────────────────────────────────────────

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

        if category in ("evp", "any"):
            for key, data in self.evp.items():
                if q in key.lower() or q in data["description"].lower() or q in data["label"].lower():
                    results.append(_fmt_evp(key, data))

        if category in ("haunting", "hauntings", "any"):
            for key, data in self.hauntings.items():
                if q in key.lower() or q in data["description"].lower() or q in data["label"].lower():
                    results.append(_fmt_haunting(key, data))

        if category in ("encounter", "encounters", "ufo", "ce", "any"):
            for key, data in self.encounters.items():
                if q in key.lower() or q in data["description"].lower() or q in data["label"].lower():
                    results.append(_fmt_ce(key, data))

        if category in ("shadow", "shadows", "any"):
            for key, data in self.shadows.items():
                if q in key.lower() or q in data["description"].lower() or q in data["label"].lower():
                    results.append(_fmt_shadow(key, data))

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

    # ── Classification-specific lookups ───────────────────────────────────────

    def evp_class(self, cls):
        """Look up a specific EVP class: 'a', 'b', or 'c'."""
        key = f"class_{cls.lower().strip('class_ ')}"
        data = self.evp.get(key) or self.evp.get(f"class_{cls.lower()}")
        if data:
            return _fmt_evp(key, data)
        return f"Unknown EVP class '{cls}'. Valid classes: A, B, C."

    def haunting_type(self, htype):
        """Look up a haunting type: residual, intelligent, poltergeist, demonic."""
        key = htype.lower().strip()
        data = self.hauntings.get(key)
        if data:
            return _fmt_haunting(key, data)
        return f"Unknown haunting type '{htype}'. Valid types: residual, intelligent, poltergeist, demonic."

    def close_encounter(self, level):
        """Look up a Close Encounter level: ce1 through ce5."""
        key = f"ce{str(level).lower().strip('ce')}"
        data = self.encounters.get(key)
        if data:
            return _fmt_ce(key, data)
        return f"Unknown encounter level '{level}'. Valid levels: CE1, CE2, CE3, CE4, CE5."

    def shadow_entity(self, etype):
        """Look up a shadow entity type."""
        q = etype.lower().strip()
        for key, data in self.shadows.items():
            if q in key.lower() or q in data["label"].lower():
                return _fmt_shadow(key, data)
        names = ", ".join(d["label"] for d in self.shadows.values())
        return f"Unknown shadow entity '{etype}'. Known types: {names}"

    # ── Random phenomenon ─────────────────────────────────────────────────────

    def random_phenomenon(self):
        """Pull a random entry from any of the classification systems."""
        pool = []

        for key, data in self.evp.items():
            pool.append(("evp", key, data))
        for key, data in self.hauntings.items():
            pool.append(("haunting", key, data))
        for key, data in self.encounters.items():
            pool.append(("encounter", key, data))
        for key, data in self.shadows.items():
            pool.append(("shadow", key, data))
        for key, data in self.phenomena.items():
            pool.append(("phenomenon", key, data))

        kind, key, data = random.choice(pool)

        if kind == "evp":
            return _fmt_evp(key, data)
        if kind == "haunting":
            return _fmt_haunting(key, data)
        if kind == "encounter":
            return _fmt_ce(key, data)
        if kind == "shadow":
            return _fmt_shadow(key, data)
        # phenomenon
        return (
            f"**{data['full_name']}**: {data['description']}\n\n"
            f"Ph3b3: \"{data['ph3b3_take']}\""
        )

    # ── Existing helpers ──────────────────────────────────────────────────────

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
