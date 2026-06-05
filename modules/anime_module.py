import json
import logging
import random
from pathlib import Path

log = logging.getLogger("ph3b3.anime")

ANIME_DB = {
    "spirited away": {
        "year": 2001, "director": "Hayao Miyazaki", "studio": "Ghibli",
        "genre": ["fantasy", "adventure"],
        "desc": "A girl trapped in a spirit world works to free her parents. Miyazaki's masterpiece by consensus. Won the Academy Award.",
        "ph3b3_take": "Perfect. No notes.",
        "vibes": ["ghibli", "fantasy", "coming of age", "spirits"],
    },
    "princess mononoke": {
        "year": 1997, "director": "Hayao Miyazaki", "studio": "Ghibli",
        "genre": ["fantasy", "action"],
        "desc": "A prince caught between industrial settlement and forest gods. No villains. Everyone has a point.",
        "ph3b3_take": "The film that taught me there are no easy answers.",
        "vibes": ["ghibli", "ecology", "war", "grey morality"],
    },
    "nausicaa of the valley of the wind": {
        "year": 1984, "director": "Hayao Miyazaki", "studio": "Ghibli",
        "genre": ["sci-fi", "fantasy"],
        "desc": "A princess in a post-apocalyptic world tries to prevent war and understand a toxic jungle. The film that led to Ghibli being founded.",
        "ph3b3_take": "Miyazaki's ecological grief has been present from the very beginning.",
        "vibes": ["ghibli", "ecology", "post-apocalyptic", "epic"],
    },
    "grave of the fireflies": {
        "year": 1988, "director": "Isao Takahata", "studio": "Ghibli",
        "genre": ["war", "drama"],
        "desc": "Two orphaned siblings try to survive in Japan during the final months of World War Two. Roger Ebert called it one of the greatest war films ever made.",
        "ph3b3_take": "I will not describe what happens. You already know it will not be okay.",
        "vibes": ["ghibli", "war", "devastating", "siblings"],
    },
    "my neighbor totoro": {
        "year": 1988, "director": "Hayao Miyazaki", "studio": "Ghibli",
        "genre": ["fantasy", "family"],
        "desc": "Two sisters encounter forest spirits while their mother is in hospital. Gentle and perfect. The catbus.",
        "ph3b3_take": "The purest thing Miyazaki ever made. No conflict. Just wonder.",
        "vibes": ["ghibli", "gentle", "spirits", "childhood"],
    },
    "castle in the sky": {
        "year": 1986, "director": "Hayao Miyazaki", "studio": "Ghibli",
        "genre": ["adventure", "fantasy"],
        "desc": "A boy and girl search for a legendary floating city. The first Ghibli film. Pure adventure.",
        "ph3b3_take": "Miyazaki understanding that adventure needs wonder to work.",
        "vibes": ["ghibli", "adventure", "flying", "treasure"],
    },
    "howls moving castle": {
        "year": 2004, "director": "Hayao Miyazaki", "studio": "Ghibli",
        "genre": ["fantasy", "romance"],
        "desc": "A young woman cursed to be old takes refuge in a wizard's moving castle. Anti-war underneath the romance.",
        "ph3b3_take": "The most romantic Ghibli film. Also quietly furious about war.",
        "vibes": ["ghibli", "romance", "fantasy", "anti-war"],
    },
    "akira": {
        "year": 1988, "director": "Katsuhiro Otomo", "studio": "TMS",
        "genre": ["sci-fi", "action"],
        "desc": "A biker gang member in neo-Tokyo triggers a catastrophic psychic awakening. Changed animation permanently.",
        "ph3b3_take": "Every frame is a decision. The influence is still everywhere.",
        "vibes": ["sci-fi", "cyberpunk", "epic", "psychic"],
    },
    "ghost in the shell": {
        "year": 1995, "director": "Mamoru Oshii", "studio": "Production IG",
        "genre": ["sci-fi", "philosophical"],
        "desc": "A cyborg agent hunts a hacker while questioning her own consciousness. The Wachowskis had a copy on set during The Matrix.",
        "ph3b3_take": "The most serious philosophical question in anime: what makes you you.",
        "vibes": ["sci-fi", "cyberpunk", "philosophy", "identity"],
    },
    "perfect blue": {
        "year": 1997, "director": "Satoshi Kon", "studio": "Madhouse",
        "genre": ["psychological horror", "thriller"],
        "desc": "A pop idol transitions to acting and loses her grip on reality. Kon obliterating the line between performance and identity.",
        "ph3b3_take": "Aronofsky bought the rights to recreate a scene in Black Swan. Kon was right to be flattered.",
        "vibes": ["psychological", "identity", "horror", "idol"],
    },
}

ANIME_DB.update({
    "millennium actress": {
        "year": 2001, "director": "Satoshi Kon", "studio": "Madhouse",
        "genre": ["drama", "mystery"],
        "desc": "Two filmmakers interview a legendary actress and fall into her memories. Reality and film blend completely. Kon at his most elegant.",
        "ph3b3_take": "The most beautiful film about cinema ever made. Also about love and time.",
        "vibes": ["memory", "cinema", "love", "kon"],
    },
    "tokyo godfathers": {
        "year": 2003, "director": "Satoshi Kon", "studio": "Madhouse",
        "genre": ["comedy", "drama"],
        "desc": "Three homeless people find an abandoned baby on Christmas Eve and try to return it. Kon's warmest film. Miracles as coincidence.",
        "ph3b3_take": "Kon proving he could do warmth as well as dread.",
        "vibes": ["comedy", "drama", "christmas", "found family"],
    },
    "paprika": {
        "year": 2006, "director": "Satoshi Kon", "studio": "Madhouse",
        "genre": ["sci-fi", "psychological"],
        "desc": "A device that allows therapists to enter patients dreams is stolen. Reality dissolves. Nolan cited this as an influence on Inception.",
        "ph3b3_take": "Kon doing in 90 minutes what Inception did in 148. Both are worth watching.",
        "vibes": ["dreams", "sci-fi", "psychological", "kon"],
    },
    "the girl who leapt through time": {
        "year": 2006, "director": "Mamoru Hosoda", "studio": "Madhouse",
        "genre": ["sci-fi", "romance", "coming of age"],
        "desc": "A high school girl discovers she can leap backwards in time. Uses the ability carelessly. Learns why that was a mistake.",
        "ph3b3_take": "The best time travel film about being seventeen.",
        "vibes": ["time travel", "romance", "coming of age", "hosoda"],
    },
    "wolf children": {
        "year": 2012, "director": "Mamoru Hosoda", "studio": "Studio Chizu",
        "genre": ["fantasy", "drama"],
        "desc": "A woman raises two half-wolf children alone after their father dies. About letting children choose who they are.",
        "ph3b3_take": "Hosoda making a film about parenthood that respects the children as much as the parent.",
        "vibes": ["family", "fantasy", "parenthood", "hosoda"],
    },
    "summer wars": {
        "year": 2009, "director": "Mamoru Hosoda", "studio": "Studio Chizu",
        "genre": ["sci-fi", "family", "action"],
        "desc": "A teenage math genius accidentally breaks a virtual world and must fix it with his extended family. Loud and warm.",
        "ph3b3_take": "The best film about family as a weapon against catastrophe.",
        "vibes": ["family", "internet", "action", "hosoda"],
    },
})

ANIME_DB.update({
    "neon genesis evangelion": {
        "year": 1995, "director": "Hideaki Anno", "studio": "Gainax",
        "genre": ["mecha", "psychological", "sci-fi"],
        "desc": "Teenagers pilot giant mechs against mysterious beings while their creator has a breakdown making the show. Changed anime permanently.",
        "ph3b3_take": "The most honest thing Anno ever did was make the last two episodes with no budget and pure psychology.",
        "vibes": ["mecha", "psychological", "depression", "iconic"],
    },
    "end of evangelion": {
        "year": 1997, "director": "Hideaki Anno", "studio": "Gainax",
        "genre": ["mecha", "psychological", "horror"],
        "desc": "The theatrical ending Anno made after the TV finale divided audiences. Apocalyptic. Deeply personal. Instrumentality.",
        "ph3b3_take": "I love you. I need you. I hate you. All three at once.",
        "vibes": ["mecha", "apocalypse", "psychological", "devastating"],
    },
    "cowboy bebop": {
        "year": 1998, "director": "Shinichiro Watanabe", "studio": "Sunrise",
        "genre": ["sci-fi", "noir", "action"],
        "desc": "Bounty hunters drifting through the solar system. Jazz. Grief. The most stylish anime ever made. See you space cowboy.",
        "ph3b3_take": "The show that proved anime could be anything. Also the loneliest.",
        "vibes": ["jazz", "noir", "space", "grief"],
    },
    "samurai champloo": {
        "year": 2004, "director": "Shinichiro Watanabe", "studio": "Manglobe",
        "genre": ["action", "historical"],
        "desc": "Two incompatible samurai and a girl travel Edo Japan to hip hop beats. Watanabe doing Bebop with swords.",
        "ph3b3_take": "Anachronistic and perfect. The fight choreography is as musical as the soundtrack.",
        "vibes": ["hip hop", "samurai", "action", "watanabe"],
    },
    "fullmetal alchemist brotherhood": {
        "year": 2009, "director": "Yasuhiro Irie", "studio": "Bones",
        "genre": ["action", "adventure", "drama"],
        "desc": "Two brothers who used forbidden alchemy search for a way to restore their bodies. The best long-form anime narrative ever told.",
        "ph3b3_take": "The most complete story in anime. Beginning middle end. All earned.",
        "vibes": ["adventure", "brotherhood", "alchemy", "epic"],
    },
    "steins gate": {
        "year": 2011, "director": "Hiroshi Hamasaki", "studio": "White Fox",
        "genre": ["sci-fi", "thriller", "romance"],
        "desc": "A self-proclaimed mad scientist accidentally invents time travel. Slow start. When it turns it does not stop.",
        "ph3b3_take": "The payoff requires patience. The patience is worth it.",
        "vibes": ["time travel", "thriller", "romance", "slow burn"],
    },
    "attack on titan": {
        "year": 2013, "director": "Tetsuro Araki", "studio": "Wit Studio",
        "genre": ["action", "horror", "drama"],
        "desc": "Humanity survives behind walls from giants that eat people. The walls are not the real enemy. Nothing is what it first appears.",
        "ph3b3_take": "The most successful bait and switch in anime history. Starts as one show. Becomes another.",
        "vibes": ["action", "horror", "political", "shocking"],
    },
    "hunter x hunter": {
        "year": 2011, "director": "Hiroshi Kojina", "studio": "Madhouse",
        "genre": ["action", "adventure"],
        "desc": "A boy searches for his father who is a legendary hunter. Gets darker and more complex with every arc. The Chimera Ant arc.",
        "ph3b3_take": "The best power system in shonen. Nen rewards creative thinking over raw strength.",
        "vibes": ["adventure", "friendship", "dark", "creative"],
    },
})

ANIME_DB.update({
    "your name": {
        "year": 2016, "director": "Makoto Shinkai", "studio": "CoMix Wave",
        "genre": ["romance", "sci-fi", "fantasy"],
        "desc": "Two teenagers swap bodies across time and distance and fall in love without meeting. The highest grossing anime film until Demon Slayer.",
        "ph3b3_take": "Shinkai finally making the film his career was building toward.",
        "vibes": ["romance", "time", "shinkai", "beautiful"],
    },
    "weathering with you": {
        "year": 2019, "director": "Makoto Shinkai", "studio": "CoMix Wave",
        "genre": ["romance", "fantasy"],
        "desc": "A runaway boy meets a girl who can stop rain in a flooded Tokyo. Shinkai choosing love over the world. Controversial ending.",
        "ph3b3_take": "Shinkai making the selfish choice and asking if you would do the same.",
        "vibes": ["romance", "rain", "tokyo", "shinkai"],
    },
    "a silent voice": {
        "year": 2016, "director": "Naoko Yamada", "studio": "Kyoto Animation",
        "genre": ["drama", "romance"],
        "desc": "A former bully seeks redemption from the deaf girl he tormented. About guilt, forgiveness, and whether you deserve it.",
        "ph3b3_take": "The most honest anime about bullying and self-loathing ever made.",
        "vibes": ["drama", "redemption", "guilt", "beautiful"],
    },
    "violet evergarden": {
        "year": 2018, "director": "Taichi Ishidate", "studio": "Kyoto Animation",
        "genre": ["drama", "fantasy"],
        "desc": "A former child soldier becomes a letter writer and learns what love means. KyoAni at their most beautiful.",
        "ph3b3_take": "I understand now what those words meant. Every episode.",
        "vibes": ["drama", "war", "letters", "emotional"],
    },
    "demon slayer mugen train": {
        "year": 2020, "director": "Haruo Sotozaki", "studio": "Ufotable",
        "genre": ["action", "fantasy"],
        "desc": "Tanjiro and his companions board a train to hunt a demon. Became the highest grossing film in Japanese history. Rengoku.",
        "ph3b3_take": "The animation is the argument. Nothing else looks like Ufotable.",
        "vibes": ["action", "demons", "beautiful animation", "grief"],
    },
    "jujutsu kaisen zero": {
        "year": 2021, "director": "Sunghoo Park", "studio": "Mappa",
        "genre": ["action", "horror"],
        "desc": "A boy with a cursed spirit inside him trains to control it. The prequel film. Gojo.",
        "ph3b3_take": "Mappa understanding that animation can compete with live action for pure spectacle.",
        "vibes": ["action", "curses", "modern", "gojo"],
    },
    "made in abyss": {
        "year": 2017, "director": "Masayuki Kojima", "studio": "Kinema Citrus",
        "genre": ["adventure", "horror", "fantasy"],
        "desc": "Children descend into a mysterious abyss. Looks cute. Is not cute. One of the darkest fantasy stories ever animated.",
        "ph3b3_take": "The gap between the art style and the content is the point.",
        "vibes": ["adventure", "dark", "abyss", "deceptive"],
    },
    "vinland saga": {
        "year": 2019, "director": "Shuhei Yabuta", "studio": "Wit Studio",
        "genre": ["historical", "action", "drama"],
        "desc": "A young Viking seeks revenge for his father's death. Becomes something else entirely. War and what it costs.",
        "ph3b3_take": "Starts as a revenge story. Argues against revenge by the end. Takes its time getting there.",
        "vibes": ["viking", "historical", "revenge", "pacifism"],
    },
    "mob psycho 100": {
        "year": 2016, "director": "Yuzuru Tachikawa", "studio": "Bones",
        "genre": ["action", "comedy", "drama"],
        "desc": "The most powerful psychic in the world just wants to be normal. ONE writing about power and humility.",
        "ph3b3_take": "The best argument that strength without character is meaningless.",
        "vibes": ["psychic", "comedy", "growth", "one"],
    },
    "ping pong the animation": {
        "year": 2014, "director": "Masaaki Yuasa", "studio": "Tatsunoko",
        "genre": ["sports", "drama"],
        "desc": "Two childhood friends with different relationships to talent compete in table tennis. Yuasa making sport into philosophy.",
        "ph3b3_take": "The hero appears. The most earned moment in sports anime.",
        "vibes": ["sports", "talent", "friendship", "yuasa"],
    },
})

ANIME_DB.update({
    "frieren beyond journeys end": {
        "year": 2023, "director": "Keiichiro Saito", "studio": "Madhouse",
        "genre": ["fantasy", "drama", "slice of life"],
        "desc": "An elf mage who helped defeat the demon king returns to retrace the journey decades later after her human companions have aged and died. About grief, time, and what it means to connect with lives shorter than yours.",
        "ph3b3_take": "The best anime of 2023 and it is not close. Quiet and devastating in equal measure.",
        "vibes": ["grief", "time", "elf", "beautiful"],
    },
    "mobile suit gundam": {
        "year": 1979, "director": "Yoshiyuki Tomino", "studio": "Sunrise",
        "genre": ["mecha", "war", "sci-fi"],
        "desc": "A civilian teenager pilots a giant robot in an interstellar civil war. Tomino inventing the real robot genre. War without heroes.",
        "ph3b3_take": "Every mecha anime exists in this show's shadow. The original.",
        "vibes": ["mecha", "war", "political", "original"],
    },
    "mobile suit gundam wing": {
        "year": 1995, "director": "Masashi Ikeda", "studio": "Sunrise",
        "genre": ["mecha", "political", "action"],
        "desc": "Five young pilots descend to Earth in Gundams to fight an oppressive military alliance. The entry point for an entire Western generation.",
        "ph3b3_take": "The Gundam that got the West watching. Heero Yuy. He Who Names Himself After the Guy He Accidentally Killed.",
        "vibes": ["mecha", "political", "action", "90s"],
    },
    "iron blooded orphans": {
        "year": 2015, "director": "Tatsuyuki Nagai", "studio": "Sunrise",
        "genre": ["mecha", "drama", "war"],
        "desc": "Child soldiers from Mars fight for independence. The darkest Gundam series. Nobody is safe. The ending.",
        "ph3b3_take": "The Gundam that commits fully to its consequences. No reset button.",
        "vibes": ["mecha", "child soldiers", "dark", "consequences"],
    },
    "gurren lagann": {
        "year": 2007, "director": "Hiroyuki Imaishi", "studio": "Gainax",
        "genre": ["mecha", "action", "comedy"],
        "desc": "A boy drills through the earth and eventually through the universe. Pure escalation. Who the hell do you think we are.",
        "ph3b3_take": "The most sincere hot blooded anime ever made. Earns every emotional beat by believing in itself completely.",
        "vibes": ["mecha", "epic", "determination", "drill"],
    },
    "chainsaw man": {
        "year": 2022, "director": "Ryu Nakayama", "studio": "Mappa",
        "genre": ["action", "horror", "dark comedy"],
        "desc": "A broke teenager merges with his chainsaw devil dog and becomes a devil hunter. Fujimoto Tatsuki writing about trauma with chainsaws.",
        "ph3b3_take": "The opening credits of every episode are a different song and a different art style. Mappa doing whatever they want.",
        "vibes": ["action", "horror", "dark comedy", "chainsaws"],
    },
    "jojo's bizarre adventure": {
        "year": 2012, "director": "Naokatsu Tsuda", "studio": "David Production",
        "genre": ["action", "horror", "comedy"],
        "desc": "The Joestar bloodline fights evil across generations and decades. Every part is a different genre. Stands. Poses. Muda muda muda.",
        "ph3b3_take": "The most influential art style in modern anime. Everything is a reference to something.",
        "vibes": ["action", "poses", "generational", "bizarre"],
    },
    "one punch man": {
        "year": 2015, "director": "Shingo Natsume", "studio": "Madhouse",
        "genre": ["action", "comedy", "satire"],
        "desc": "A hero who can defeat any enemy with one punch is bored. Satire of shonen power fantasy dressed as the thing it satirizes.",
        "ph3b3_take": "Season one is perfect. The Madhouse animation. The joke never gets old because the show understands why it works.",
        "vibes": ["action", "satire", "comedy", "overpowered"],
    },
    "spy x family": {
        "year": 2022, "director": "Kazuhiro Furuhashi", "studio": "Wit and CloverWorks",
        "genre": ["comedy", "action", "family"],
        "desc": "A spy assembles a fake family to complete a mission without knowing his fake wife is an assassin and his fake daughter can read minds.",
        "ph3b3_take": "The warmest action comedy in recent anime. Anya is perfect.",
        "vibes": ["comedy", "family", "spy", "wholesome"],
    },
    "bocchi the rock": {
        "year": 2022, "director": "Keiichiro Saito", "studio": "CloverWorks",
        "genre": ["comedy", "music", "slice of life"],
        "desc": "A severely anxious girl who taught herself guitar alone in her room joins a band. The most accurate portrayal of social anxiety in anime.",
        "ph3b3_take": "The best music anime since Beck. Also the funniest show of its year.",
        "vibes": ["music", "anxiety", "comedy", "guitar"],
    },
})

ANIME_DB.update({
    "dragon ball": {
        "year": 1986, "director": "Daisuke Nishio", "studio": "Toei",
        "genre": ["action", "adventure", "comedy"],
        "desc": "A monkey-tailed boy searches for dragon balls and trains in martial arts. Toriyama inventing the template for shonen adventure.",
        "ph3b3_take": "The original. Everything after it is a conversation with this show.",
        "vibes": ["adventure", "martial arts", "comedy", "classic"],
    },
    "dragon ball z": {
        "year": 1989, "director": "Daisuke Nishio", "studio": "Toei",
        "genre": ["action", "sci-fi"],
        "desc": "Goku and friends defend Earth from increasingly powerful alien threats. Defined an entire generation globally. Super Saiyan.",
        "ph3b3_take": "The power scaling broke anime forever. Worth it.",
        "vibes": ["action", "power levels", "iconic", "global"],
    },
    "naruto": {
        "year": 2002, "director": "Hayato Date", "studio": "Pierrot",
        "genre": ["action", "adventure"],
        "desc": "An orphaned ninja with a demon fox sealed inside him dreams of becoming the greatest ninja. The friendship and the betrayal.",
        "ph3b3_take": "Naruto crying over Neji hit different than it should have. Kishimoto understood loss better than he gets credit for.",
        "vibes": ["ninja", "friendship", "betrayal", "determination"],
    },
    "one piece": {
        "year": 1999, "director": "Konosuke Uda", "studio": "Toei",
        "genre": ["action", "adventure", "comedy"],
        "desc": "A boy made of rubber wants to be King of the Pirates. 1000 plus episodes. The longest ongoing story in animation history. Marineford.",
        "ph3b3_take": "The world building is unmatched in all of fiction. Oda has been planning this since the first chapter.",
        "vibes": ["adventure", "pirates", "world building", "epic"],
    },
    "bleach": {
        "year": 2004, "director": "Noriyuki Abe", "studio": "Pierrot",
        "genre": ["action", "supernatural"],
        "desc": "A teenager becomes a Soul Reaper and defends the living from evil spirits. The Soul Society arc. The Bankai reveals.",
        "ph3b3_take": "The best villain introduction in shonen history is Aizen standing up at that meeting.",
        "vibes": ["soul reaper", "action", "supernatural", "style"],
    },
    "yu yu hakusho": {
        "year": 1992, "director": "Noriyuki Abe", "studio": "Pierrot",
        "genre": ["action", "supernatural"],
        "desc": "A delinquent dies saving a child and becomes a spirit detective. The Dark Tournament. Togashi writing his best story before Hunter x Hunter.",
        "ph3b3_take": "Togashi understanding character motivation better than anyone in shonen.",
        "vibes": ["supernatural", "tournament", "delinquent", "classic"],
    },
    "sailor moon": {
        "year": 1992, "director": "Junichi Sato", "studio": "Toei",
        "genre": ["magical girl", "romance", "action"],
        "desc": "A clumsy schoolgirl is the reincarnation of a warrior princess who must protect Earth. Defined magical girl anime globally.",
        "ph3b3_take": "The template every magical girl show is in conversation with. Still holds up.",
        "vibes": ["magical girl", "romance", "classic", "iconic"],
    },
    "neon genesis evangelion": {
        "year": 1995, "director": "Hideaki Anno", "studio": "Gainax",
        "genre": ["mecha", "psychological"],
        "desc": "Already in database. The definitive mecha anime.",
        "ph3b3_take": "See above.",
        "vibes": ["mecha", "psychological", "classic"],
    },
    "trigun": {
        "year": 1998, "director": "Satoshi Nishimura", "studio": "Madhouse",
        "genre": ["action", "sci-fi", "western"],
        "desc": "A legendary gunman with a bounty of 60 billion double dollars wanders a desert planet causing destruction everywhere he goes. Love and peace.",
        "ph3b3_take": "The most optimistic protagonist in anime. Vash never stops believing in people.",
        "vibes": ["western", "sci-fi", "comedy", "pacifist"],
    },
    "fullmetal alchemist 2003": {
        "year": 2003, "director": "Seiji Mizushima", "studio": "Bones",
        "genre": ["action", "drama"],
        "desc": "The original adaptation before Brotherhood. Goes its own direction. Darker ending. Homunculi with different origins.",
        "ph3b3_take": "Different from Brotherhood. Worth watching both. This one is sadder.",
        "vibes": ["alchemy", "dark", "alternate", "drama"],
    },
    "inuyasha": {
        "year": 2000, "director": "Masashi Ikeda", "studio": "Sunrise",
        "genre": ["action", "romance", "fantasy"],
        "desc": "A schoolgirl falls through a well into feudal Japan and teams up with a half-demon to collect shards of a shattered jewel.",
        "ph3b3_take": "The romance was genuinely compelling. The filler was genuinely not.",
        "vibes": ["fantasy", "romance", "feudal japan", "demons"],
    },
    "rurouni kenshin": {
        "year": 1996, "director": "Kazuhiro Furuhashi", "studio": "Deen",
        "genre": ["action", "historical", "drama"],
        "desc": "A legendary assassin from the Meiji Revolution now wanders Japan as a pacifist swordsman. The Kyoto arc.",
        "ph3b3_take": "The best historical action anime. Kenshin choosing who to be after what he was.",
        "vibes": ["samurai", "historical", "redemption", "action"],
    },
    "cowboy bebop": {
        "year": 1998, "director": "Shinichiro Watanabe", "studio": "Sunrise",
        "genre": ["sci-fi", "noir", "action"],
        "desc": "Bounty hunters drifting through the solar system. Jazz. Grief. The most stylish anime ever made. See you space cowboy.",
        "ph3b3_take": "The show that proved anime could be anything. Also the loneliest show ever made.",
        "vibes": ["jazz", "noir", "space", "grief"],
    },
})

ANIME_GENRES = {
    "ghibli": ["spirited away", "princess mononoke", "grave of the fireflies", "my neighbor totoro", "howls moving castle"],
    "mecha": ["neon genesis evangelion", "cowboy bebop", "gurren lagann", "code geass", "mobile suit gundam", "iron blooded orphans"],
    "horror": ["perfect blue", "parasyte", "made in abyss", "serial experiments lain"],
    "romance": ["your name", "a silent voice", "weathering with you", "frieren beyond journeys end"],
    "classic shonen": ["dragon ball z", "naruto", "one piece", "bleach", "yu yu hakusho"],
    "psychological": ["death note", "steins gate", "serial experiments lain", "perfect blue"],
    "modern": ["frieren beyond journeys end", "chainsaw man", "spy x family", "bocchi the rock"],
    "kon": ["perfect blue", "millennium actress", "tokyo godfathers", "paprika"],
}

class AnimeModule:
    def __init__(self, db_path=None):
        self.anime = ANIME_DB
        self.genres = ANIME_GENRES
        if db_path and Path(db_path).exists():
            try:
                with open(db_path) as f:
                    external = json.load(f)
                self.anime.update(external.get("anime", {}))
                log.info(f"Anime DB extended from {db_path}")
            except Exception as e:
                log.warning(f"Could not load anime DB: {e}")
        log.info(f"Anime module ready. {len(self.anime)} titles loaded.")

    def lookup(self, query, mode="lookup"):
        q = query.lower().strip()
        if mode == "recommend":
            for genre, titles in self.genres.items():
                if q in genre:
                    results = []
                    for t in titles:
                        if t in self.anime:
                            d = self.anime[t]
                            results.append(f"**{t.title()}** ({d['year']}, {d['studio']}): {d['desc'][:80]}...")
                    return "\n".join(results) if results else f"No recommendations for {query}"
        for key, data in self.anime.items():
            if q in key.lower() or key.lower() in q:
                return (
                    f"**{key.title()}** ({data['year']}) — {data['director']} / {data['studio']}\n"
                    f"{data['desc']}\n\n"
                    f"Ph3b3: \"{data['ph3b3_take']}\""
                )
        vibes_match = []
        for key, data in self.anime.items():
            if any(q in v for v in data.get("vibes", [])):
                vibes_match.append(f"**{key.title()}** ({data['year']}) — {data['studio']}")
        if vibes_match:
            return f"Anime matching '{query}':\n" + "\n".join(vibes_match[:6])
        return f"'{query}' not in anime database."

    def random_rec(self):
        key = random.choice(list(self.anime.keys()))
        d = self.anime[key]
        return f"**{key.title()}** ({d['year']}, {d['studio']})\n{d['desc']}\n\nPh3b3: \"{d['ph3b3_take']}\""
