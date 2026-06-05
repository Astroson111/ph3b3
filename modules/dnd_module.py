import json
import logging
from pathlib import Path

log = logging.getLogger("ph3b3.dnd")

BUILTIN_RULES = {
    "advantage": "Roll 2d20 keep highest. Granted by various features, spells, and conditions.",
    "disadvantage": "Roll 2d20 keep lowest. Cancels advantage — multiple instances do not stack.",
    "proficiency bonus": "Starts at +2 at level 1, scales to +6 at level 17. Added to attacks, saves, and skills you are proficient in.",
    "concentration": "Maintaining a spell. Taking damage requires CON save DC 10 or half damage taken. Can only concentrate on one spell.",
    "action economy": "On your turn: 1 Action, 1 Bonus Action if available, Movement, free object interaction. Reactions trigger off-turn.",
    "death saving throws": "At 0 HP roll d20. 10+ success, 1-9 failure. 3 successes stable. 3 failures dead. Nat 1 = 2 failures. Nat 20 = 1 HP.",
    "exhaustion": "6 levels. Level 1: disadvantage on checks. Level 3: halved speed. Level 5: halved max HP. Level 6: death.",
    "opportunity attack": "When a creature leaves your reach without Disengage, use your Reaction to make one melee attack.",
    "grapple": "Replace one attack with Athletics check vs opponent Athletics or Acrobatics. Success: target Grappled, speed 0.",
    "cover": "Half cover: +2 AC and DEX saves. Three-quarters: +5. Full: cannot be targeted directly.",
    "blinded": "Auto-fail sight checks. Attacks against you have advantage. Your attacks have disadvantage.",
    "poisoned": "Disadvantage on attack rolls and ability checks.",
    "prone": "Disadvantage on attacks. Melee attacks against you have advantage. Ranged attacks have disadvantage. Stand up costs half movement.",
    "stunned": "Incapacitated. Cannot move. Auto-fail STR and DEX saves. Attacks against you have advantage.",
    "fireball": "3rd level evocation. 150ft range, 20ft radius. 8d6 fire damage, DEX save for half. Upcasting: +1d6 per slot level above 3rd.",
    "counterspell": "3rd level abjuration. Reaction. Interrupt a spell of 3rd level or lower automatically. Higher: Arcana check DC 10 plus spell level.",
    "misty step": "2nd level conjuration. Bonus action. Teleport up to 30ft to unoccupied space you can see.",
    "shield": "1st level abjuration. Reaction. +5 AC until next turn. Immune to magic missile.",
    "hex": "1st level enchantment. Bonus action. Concentration 1hr. Target takes +1d6 necrotic on each of your attacks.",
    "wish": "9th level conjuration. Most powerful spell in 5e. 33% chance to never cast Wish again after using it for something other than spell replication.",
}

BUILTIN_MONSTERS = {
    "tarrasque": "CR 30. Gargantuan monstrosity. Reflective carapace reflects single-target spells on nat 20 save. Regenerates unless brought below 0 with a Wish.",
    "beholder": "CR 13. Eye rays with different effects each round. Central eye creates antimagic cone. Highly paranoid and territorial.",
    "mind flayer": "CR 7. Mind Blast cone stun. Extract Brain for instakill on grappled stunned target. Consume brains to survive.",
    "lich": "CR 21. Undead wizard. Soul-bound phylactery — destroyed and returns in 1d10 days unless phylactery destroyed.",
    "vampire": "CR 13. Charm, hypnotic gaze. Bite for HP drain. Regenerates 20 HP per turn. Weaknesses: sunlight, running water, stake through heart.",
    "aboleth": "CR 10. Ancient psionic aberration. Enslave via WIS save or charmed permanently. Predates the gods in lore.",
}

CLASSES = {
    "fighter": "Full martial. Action Surge is their signature. Battlemaster is mechanically richest subclass. Gets the most ASIs of any class.",
    "wizard": "INT full caster. Spellbook mechanic. Learns more spells than any caster. Chronurgy and Scribes are powerful subclasses.",
    "warlock": "CHA caster with Eldritch Blast. Short-rest spell slots. Hexblade extremely popular for SAD builds.",
    "druid": "WIS full caster. Wild Shape. Moon Druid is one of the strongest early-game subclasses.",
    "paladin": "Half-caster martial. Aura of Protection at level 6 is one of the most powerful features in 5e.",
    "rogue": "Sneak Attack. Cunning Action. Expertise. Assassin for burst damage. Arcane Trickster for spells.",
    "barbarian": "Rage for resistance to BPS damage. Reckless Attack for advantage. Totem Warrior Bear for absurd durability.",
    "cleric": "WIS full caster. Twilight and Order are powerful subclasses. Channel Divinity 2x per short rest.",
    "bard": "CHA full caster. Jack of All Trades. Bardic Inspiration. One of the strongest classes overall.",
    "sorcerer": "CHA full caster. Sorcery Points and Metamagic. Wild Magic for chaos. Limited spells known.",
    "monk": "WIS-DEX martial. Ki points. Stunning Strike is strong but ki-hungry.",
    "ranger": "WIS half-caster martial. Gloom Stalker is the strongest subclass. Most tables use UA ranger.",
}

class DnDModule:
    def __init__(self, db_path=None):
        self.rules = BUILTIN_RULES
        self.monsters = BUILTIN_MONSTERS
        self.classes = CLASSES
        if db_path and Path(db_path).exists():
            try:
                with open(db_path) as f:
                    external = json.load(f)
                self.rules.update(external.get("rules", {}))
                self.monsters.update(external.get("monsters", {}))
                log.info(f"D&D DB extended from {db_path}")
            except Exception as e:
                log.warning(f"Could not load D&D DB: {e}")
        log.info("D&D module ready.")

    def lookup(self, query, category="any", edition="5e"):
        q = query.lower().strip()
        matches = []
        if category in ("rule", "spell", "condition", "any"):
            for key, val in self.rules.items():
                if q in key.lower() or key.lower() in q:
                    matches.append(f"**{key.title()}**: {val}")
        if category in ("monster", "any"):
            for key, val in self.monsters.items():
                if q in key.lower() or key.lower() in q:
                    matches.append(f"**{key.title()}** (monster): {val}")
        if category in ("class", "any"):
            for key, val in self.classes.items():
                if q in key.lower() or key.lower() in q:
                    matches.append(f"**{key.title()}** (class): {val}")
        if matches:
            return "\n\n".join(matches[:3])
        all_keys = list(self.rules.keys()) + list(self.monsters.keys()) + list(self.classes.keys())
        close = [k for k in all_keys if any(word in k for word in q.split() if len(word) > 3)]
        if close:
            return f"No exact match for '{query}'. Related: {', '.join(close[:5])}"
        return f"'{query}' not in D&D database. Ph3b3 will reason from training knowledge."
