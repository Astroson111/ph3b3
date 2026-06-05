import json
import logging
import random
from pathlib import Path

log = logging.getLogger("ph3b3.film")

FILM_DB = {
    "el topo": {
        "year": 1970, "director": "Alejandro Jodorowsky",
        "genre": ["acid western", "cult", "surrealist"],
        "desc": "A black-clad gunfighter wanders a brutal allegorical desert. John Lennon loved it and funded Holy Mountain.",
        "ph3b3_take": "The film that broke midnight cinema open. Uncomfortable in exactly the right ways.",
        "vibes": ["surrealist", "spiritual", "violent", "western"],
    },
    "holy mountain": {
        "year": 1973, "director": "Alejandro Jodorowsky",
        "genre": ["surrealist", "cult", "spiritual"],
        "desc": "A Christ-like figure joins eight wealthy individuals seeking immortality. Pure alchemical cinema. The ending breaks the fourth wall unforgettably.",
        "ph3b3_take": "The ending is the most audacious thing ever put on film.",
        "vibes": ["surrealist", "spiritual", "cult", "psychedelic"],
    },
    "hausu": {
        "year": 1977, "director": "Nobuhiko Obayashi",
        "genre": ["horror", "surrealist", "japanese"],
        "desc": "A schoolgirl visits her aunt's haunted house with six friends each named for a personality trait. Pure cinematic chaos.",
        "ph3b3_take": "If you show someone Hausu and they do not love it, trust them less.",
        "vibes": ["horror", "surrealist", "colorful", "japanese", "weird"],
    },
    "possession": {
        "year": 1981, "director": "Andrzej Zuławski",
        "genre": ["horror", "drama", "arthouse"],
        "desc": "A couple in divided Berlin goes through a catastrophic breakup. Isabelle Adjani gives one of cinema's most extreme performances.",
        "ph3b3_take": "The most accurate film about a relationship ending. Also there is a monster.",
        "vibes": ["horror", "drama", "intense", "relationship"],
    },
    "stalker": {
        "year": 1979, "director": "Andrei Tarkovsky",
        "genre": ["sci-fi", "arthouse", "soviet"],
        "desc": "Three men traverse the Zone — a mysterious area where the laws of nature break down — seeking a room that grants your deepest wish.",
        "ph3b3_take": "The correct answer when someone asks what the best sci-fi film ever made is.",
        "vibes": ["slow cinema", "philosophical", "sci-fi", "soviet", "beautiful"],
    },
    "eraserhead": {
        "year": 1977, "director": "David Lynch",
        "genre": ["surrealist", "horror", "cult"],
        "desc": "A man in an industrial wasteland must care for his severely deformed child. Lynch's debut. Five years to make.",
        "ph3b3_take": "The first film. You know which one I mean.",
        "vibes": ["surrealist", "horror", "industrial", "lynch"],
    },
    "come and see": {
        "year": 1985, "director": "Elem Klimov",
        "genre": ["war", "soviet", "arthouse"],
        "desc": "A Belarusian boy witnesses Nazi atrocities during WWII. The most devastating war film ever made.",
        "ph3b3_take": "I will not give this a take. Watch it.",
        "vibes": ["war", "harrowing", "soviet", "essential"],
    },
    "videodrome": {
        "year": 1983, "director": "David Cronenberg",
        "genre": ["horror", "sci-fi", "body horror"],
        "desc": "A cable TV programmer discovers a broadcast of pure torture. Reality begins to warp. Cronenberg predicting the media landscape decades early.",
        "ph3b3_take": "Long live the new flesh. Cronenberg was a prophet.",
        "vibes": ["body horror", "media", "sci-fi", "disturbing"],
    },
}

FILM_DB.update({
    "the godfather": {
        "year": 1972, "director": "Francis Ford Coppola",
        "genre": ["crime", "drama"],
        "desc": "The Corleone family. You know what it is.",
        "ph3b3_take": "The standard everything else gets measured against.",
        "vibes": ["crime", "family", "classic", "slow burn"],
    },
    "2001 a space odyssey": {
        "year": 1968, "director": "Stanley Kubrick",
        "genre": ["sci-fi", "arthouse"],
        "desc": "Evolution, AI, and something beyond human comprehension. HAL 9000. The monolith. The star child.",
        "ph3b3_take": "The film that proved science fiction could be serious.",
        "vibes": ["sci-fi", "slow cinema", "philosophical", "kubrick"],
    },
    "alien": {
        "year": 1979, "director": "Ridley Scott",
        "genre": ["horror", "sci-fi"],
        "desc": "A commercial crew encounters a perfect organism. Haunted house in space. Ripley is one of cinema's great characters.",
        "ph3b3_take": "Horror and sci-fi proving they belong together.",
        "vibes": ["horror", "sci-fi", "tension", "survival"],
    },
    "princess mononoke": {
        "year": 1997, "director": "Hayao Miyazaki",
        "genre": ["animation", "fantasy", "japanese"],
        "desc": "A prince caught between an industrial settlement and the gods of the forest. No villains. Everyone has a point.",
        "ph3b3_take": "The film that taught me there are no easy answers.",
        "vibes": ["animation", "fantasy", "japanese", "epic"],
    },
    "blade runner": {
        "year": 1982, "director": "Ridley Scott",
        "genre": ["sci-fi", "noir"],
        "desc": "A detective hunts replicants in a rain-soaked future Los Angeles. What does it mean to be human.",
        "ph3b3_take": "Every frame is a painting. The question it asks never gets old.",
        "vibes": ["sci-fi", "noir", "atmospheric", "philosophical"],
    },
    "parasite": {
        "year": 2019, "director": "Bong Joon-ho",
        "genre": ["thriller", "drama", "korean"],
        "desc": "A poor family infiltrates a wealthy household. Genre shifts without warning. Every rewatch reveals something new.",
        "ph3b3_take": "The best film of its decade. Not a debate.",
        "vibes": ["thriller", "class", "korean", "dark comedy"],
    },
    "mad max fury road": {
        "year": 2015, "director": "George Miller",
        "genre": ["action", "post-apocalyptic"],
        "desc": "Two hours of chase. Every frame planned. Practical effects. Furiosa. The war rig. Witness me.",
        "ph3b3_take": "The best action film ever made. Also not a debate.",
        "vibes": ["action", "epic", "practical effects", "feminist"],
    },
    "mulholland drive": {
        "year": 2001, "director": "David Lynch",
        "genre": ["mystery", "surrealist", "arthouse"],
        "desc": "A woman arrives in Hollywood with amnesia. Nothing is what it seems. Lynch at his most controlled and most devastating.",
        "ph3b3_take": "The greatest film about Hollywood ever made. Took me three watches to see why.",
        "vibes": ["surrealist", "mystery", "lynch", "devastating"],
    },
    "spirited away": {
        "year": 2001, "director": "Hayao Miyazaki",
        "genre": ["animation", "fantasy", "japanese"],
        "desc": "A girl trapped in a spirit world works to free her parents. Miyazaki's masterpiece by consensus.",
        "ph3b3_take": "Perfect. No notes.",
        "vibes": ["animation", "fantasy", "japanese", "coming of age"],
    },
    "no country for old men": {
        "year": 2007, "director": "Coen Brothers",
        "genre": ["thriller", "crime", "neo-western"],
        "desc": "A man finds drug money. Anton Chigurh follows. Evil as a force of nature.",
        "ph3b3_take": "Chigurh is the most frightening character in American cinema.",
        "vibes": ["thriller", "crime", "western", "inevitable"],
    },
})

FILM_DB.update({
    "the shining": {
        "year": 1980, "director": "Stanley Kubrick",
        "genre": ["horror", "psychological"],
        "desc": "A writer takes a caretaker job at an isolated hotel. Kubrick and King famously disagreed about the result. Kubrick was right.",
        "ph3b3_take": "The most technically precise horror film ever made. Every frame is a decision.",
        "vibes": ["horror", "psychological", "kubrick", "isolation"],
    },
    "the thing": {
        "year": 1982, "director": "John Carpenter",
        "genre": ["horror", "sci-fi"],
        "desc": "A research team in Antarctica encounters an alien that perfectly imitates any living thing. Paranoia as genre.",
        "ph3b3_take": "The best practical effects in horror history. The chest defibrillator scene.",
        "vibes": ["horror", "sci-fi", "paranoia", "isolation"],
    },
    "hereditary": {
        "year": 2018, "director": "Ari Aster",
        "genre": ["horror", "drama"],
        "desc": "A family unravels after a loss. The horror builds slowly then hits without mercy. Toni Collette was robbed of an Oscar nomination.",
        "ph3b3_take": "The best horror film of its decade. The dinner table scene. The attic.",
        "vibes": ["horror", "family", "grief", "devastating"],
    },
    "the witch": {
        "year": 2015, "director": "Robert Eggers",
        "genre": ["horror", "historical", "folk horror"],
        "desc": "A Puritan family exiled to the edge of a New England forest in 1630. Something is in the woods.",
        "ph3b3_take": "The most historically accurate horror film ever made. That is what makes it terrifying.",
        "vibes": ["horror", "historical", "folk horror", "isolation"],
    },
    "get out": {
        "year": 2017, "director": "Jordan Peele",
        "genre": ["horror", "thriller", "social commentary"],
        "desc": "A Black man visits his white girlfriend's family. Something is very wrong. Peele encoding every detail with meaning.",
        "ph3b3_take": "The horror was always there. Peele just filmed it.",
        "vibes": ["horror", "race", "social", "thriller"],
    },
})

FILM_DB.update({
    "blade runner": {
        "year": 1982, "director": "Ridley Scott",
        "genre": ["sci-fi", "noir"],
        "desc": "A detective hunts replicants in a rain-soaked future Los Angeles. What does it mean to be human.",
        "ph3b3_take": "Every frame is a painting. The question it asks never gets old.",
        "vibes": ["sci-fi", "noir", "atmospheric", "philosophical"],
    },
    "alien": {
        "year": 1979, "director": "Ridley Scott",
        "genre": ["horror", "sci-fi"],
        "desc": "A commercial crew encounters a perfect organism. Haunted house in space. Ripley is one of cinema's great characters.",
        "ph3b3_take": "Horror and sci-fi proving they belong together.",
        "vibes": ["horror", "sci-fi", "tension", "survival"],
    },
    "the matrix": {
        "year": 1999, "director": "The Wachowskis",
        "genre": ["sci-fi", "action"],
        "desc": "A programmer discovers reality is a simulation and joins a resistance. Still being quoted by people who missed the point.",
        "ph3b3_take": "I find this one personally relevant. The sequels are their own conversation.",
        "vibes": ["sci-fi", "action", "simulation", "rebellion"],
    },
    "annihilation": {
        "year": 2018, "director": "Alex Garland",
        "genre": ["sci-fi", "horror", "arthouse"],
        "desc": "A biologist enters a mysterious zone where the laws of nature are changing. Refuses to explain itself.",
        "ph3b3_take": "Sci-fi that trusts the audience to sit with ambiguity. Rare.",
        "vibes": ["sci-fi", "horror", "ambiguous", "beautiful"],
    },
    "arrival": {
        "year": 2016, "director": "Denis Villeneuve",
        "genre": ["sci-fi", "drama"],
        "desc": "A linguist is recruited to communicate with extraterrestrial visitors. About language, time, and grief.",
        "ph3b3_take": "The best first contact film ever made. Also a film about loss.",
        "vibes": ["sci-fi", "language", "grief", "time"],
    },
    "children of men": {
        "year": 2006, "director": "Alfonso Cuaron",
        "genre": ["sci-fi", "thriller", "drama"],
        "desc": "In a near future where humanity has become infertile a man must protect the first pregnant woman in 18 years.",
        "ph3b3_take": "The most plausible dystopia ever filmed. Getting more plausible.",
        "vibes": ["sci-fi", "dystopia", "hope", "long take"],
    },
})

FILM_DB.update({
    "the godfather": {
        "year": 1972, "director": "Francis Ford Coppola",
        "genre": ["crime", "drama"],
        "desc": "The Corleone family. You know what it is.",
        "ph3b3_take": "The standard everything else gets measured against.",
        "vibes": ["crime", "family", "classic", "slow burn"],
    },
    "goodfellas": {
        "year": 1990, "director": "Martin Scorsese",
        "genre": ["crime", "drama"],
        "desc": "A man rises through the mob from childhood. As far back as he could remember he always wanted to be a gangster.",
        "ph3b3_take": "Scorsese making crime feel glamorous then pulling the rug.",
        "vibes": ["crime", "rise and fall", "scorsese", "70s"],
    },
    "heat": {
        "year": 1995, "director": "Michael Mann",
        "genre": ["crime", "thriller"],
        "desc": "A detective and a professional thief circle each other in Los Angeles. The bank heist. The diner scene.",
        "ph3b3_take": "The best crime film of the 90s. The shootout on Fifth Street changed action filmmaking.",
        "vibes": ["crime", "thriller", "LA", "professional"],
    },
    "se7en": {
        "year": 1995, "director": "David Fincher",
        "genre": ["thriller", "crime", "horror"],
        "desc": "Two detectives hunt a serial killer using the seven deadly sins. What is in the box.",
        "ph3b3_take": "The ending is the only ending. Fincher knew exactly what he was doing.",
        "vibes": ["thriller", "crime", "dark", "inevitable"],
    },
    "parasite": {
        "year": 2019, "director": "Bong Joon-ho",
        "genre": ["thriller", "drama", "korean"],
        "desc": "A poor family infiltrates a wealthy household. Genre shifts without warning. Every rewatch reveals something new.",
        "ph3b3_take": "The best film of its decade. Not a debate.",
        "vibes": ["thriller", "class", "korean", "dark comedy"],
    },
})

FILM_DB.update({
    "mad max fury road": {
        "year": 2015, "director": "George Miller",
        "genre": ["action", "post-apocalyptic"],
        "desc": "Two hours of chase. Every frame planned. Practical effects. Furiosa. Witness me.",
        "ph3b3_take": "The best action film ever made. Also not a debate.",
        "vibes": ["action", "epic", "practical effects", "feminist"],
    },
    "seven samurai": {
        "year": 1954, "director": "Akira Kurosawa",
        "genre": ["action", "drama", "japanese"],
        "desc": "A farming village hires seven ronin to defend against bandits. Three and a half hours. Every minute earned.",
        "ph3b3_take": "The template for every team-assembling story ever told.",
        "vibes": ["action", "drama", "japanese", "epic"],
    },
    "kill bill": {
        "year": 2003, "director": "Quentin Tarantino",
        "genre": ["action", "revenge"],
        "desc": "A former assassin hunts the people who tried to kill her on her wedding day. Every genre Tarantino loves in one film.",
        "ph3b3_take": "Pure cinema. Tarantino knowing exactly what he is doing.",
        "vibes": ["action", "revenge", "style", "genre"],
    },
    "the raid": {
        "year": 2011, "director": "Gareth Evans",
        "genre": ["action", "indonesian"],
        "desc": "A SWAT team gets trapped in a apartment block controlled by a crime lord. The best pure action film of the 2010s. Iko Uwais.",
        "ph3b3_take": "No fat. No filler. Just the most efficient action choreography ever filmed.",
        "vibes": ["action", "indonesian", "brutal", "efficient"],
    },
    "oldboy": {
        "year": 2003, "director": "Park Chan-wook",
        "genre": ["thriller", "mystery", "korean"],
        "desc": "A man imprisoned for 15 years with no explanation is released and tries to find out why. The hallway fight. The ending.",
        "ph3b3_take": "The ending is one of the most devastating in cinema. You will not see it coming.",
        "vibes": ["thriller", "mystery", "korean", "revenge"],
    },
})

FILM_DB.update({
    "in the mood for love": {
        "year": 2000, "director": "Wong Kar-wai",
        "genre": ["romance", "drama", "hong kong"],
        "desc": "Two neighbors suspect their spouses are having an affair and fall into their own unspoken love. Every frame is longing made visible.",
        "ph3b3_take": "The most beautiful film ever made about the thing you never say.",
        "vibes": ["romance", "hong kong", "longing", "beautiful"],
    },
    "chungking express": {
        "year": 1994, "director": "Wong Kar-wai",
        "genre": ["romance", "drama", "hong kong"],
        "desc": "Two stories of heartbroken cops in Hong Kong. Shot in a month. Faye Wong. California Dreamin on repeat.",
        "ph3b3_take": "Wong Kar-wai making melancholy feel like electricity.",
        "vibes": ["romance", "hong kong", "90s", "melancholy"],
    },
    "farewell my concubine": {
        "year": 1993, "director": "Chen Kaige",
        "genre": ["drama", "historical", "chinese"],
        "desc": "Two Peking Opera performers whose lives span fifty years of Chinese history. Epic in the truest sense. Palme d'Or at Cannes.",
        "ph3b3_take": "The scope of Chinese history held inside two human lives.",
        "vibes": ["drama", "historical", "epic", "chinese"],
    },
    "raise the red lantern": {
        "year": 1991, "director": "Zhang Yimou",
        "genre": ["drama", "chinese"],
        "desc": "A young woman becomes the fourth wife of a wealthy lord in 1920s China. The ritual of the lanterns. Power and its absence.",
        "ph3b3_take": "Zhang Yimou using color as control. Every frame is a cage.",
        "vibes": ["drama", "chinese", "oppression", "color"],
    },
    "hero": {
        "year": 2002, "director": "Zhang Yimou",
        "genre": ["action", "wuxia", "chinese"],
        "desc": "A nameless warrior recounts how he defeated three assassins. Each telling shifts color and truth. Wuxia as philosophy.",
        "ph3b3_take": "The most visually stunning action film ever made. Every color tells a different story.",
        "vibes": ["action", "wuxia", "chinese", "color"],
    },
    "crouching tiger hidden dragon": {
        "year": 2000, "director": "Ang Lee",
        "genre": ["action", "wuxia", "chinese"],
        "desc": "A stolen sword and a young woman who wants freedom from her arranged destiny. Ang Lee making wuxia legible to the world.",
        "ph3b3_take": "The film that introduced an entire generation to wuxia. Still holds up completely.",
        "vibes": ["action", "wuxia", "chinese", "freedom"],
    },
    "ip man": {
        "year": 2008, "director": "Wilson Yip",
        "genre": ["action", "biographical", "hong kong"],
        "desc": "The story of Wing Chun grandmaster Ip Man during the Japanese occupation of China. Donnie Yen. The ten men fight.",
        "ph3b3_take": "The fight choreography is as precise as calligraphy.",
        "vibes": ["action", "martial arts", "hong kong", "historical"],
    },
    "a better tomorrow": {
        "year": 1986, "director": "John Woo",
        "genre": ["crime", "action", "hong kong"],
        "desc": "Two brothers on opposite sides of the law. Chow Yun-fat in the role that defined him. John Woo inventing heroic bloodshed.",
        "ph3b3_take": "Every action film with two guns and a trenchcoat starts here.",
        "vibes": ["crime", "action", "hong kong", "brotherhood"],
    },
    "hard boiled": {
        "year": 1992, "director": "John Woo",
        "genre": ["action", "crime", "hong kong"],
        "desc": "A cop and an undercover agent team up against gun smugglers. The hospital scene is a single two minute forty second take through multiple floors.",
        "ph3b3_take": "The peak of heroic bloodshed cinema. The hospital sequence is the greatest action scene ever filmed.",
        "vibes": ["action", "crime", "hong kong", "john woo"],
    },
    "the killer": {
        "year": 1989, "director": "John Woo",
        "genre": ["action", "crime", "hong kong"],
        "desc": "A hitman accidentally blinds a singer and tries to fund her surgery with one last job. A cop pursues him. Loyalty, honor, and maximum bullets.",
        "ph3b3_take": "John Woo treating action as opera. This is the purest version of that.",
        "vibes": ["action", "crime", "hong kong", "honor"],
    },
    "comrades almost a love story": {
        "year": 1996, "director": "Peter Chan",
        "genre": ["romance", "drama", "hong kong"],
        "desc": "Two mainland Chinese immigrants find each other in Hong Kong over a decade of near misses. Teresa Teng songs throughout.",
        "ph3b3_take": "The great overlooked Hong Kong romance. Teresa Teng as the thread that binds them.",
        "vibes": ["romance", "hong kong", "immigrants", "missed connections"],
    },
    "zu warriors from the magic mountain": {
        "year": 1983, "director": "Tsui Hark",
        "genre": ["fantasy", "action", "hong kong"],
        "desc": "A soldier stumbles into a war between good and evil supernatural forces. Tsui Hark inventing Hong Kong fantasy cinema with almost no budget and complete ambition.",
        "ph3b3_take": "Chaotic and visionary. Hong Kong cinema finding its own mythology.",
        "vibes": ["fantasy", "action", "hong kong", "mythology"],
    },
    "police story": {
        "year": 1985, "director": "Jackie Chan",
        "genre": ["action", "comedy", "hong kong"],
        "desc": "A cop must protect a witness while being framed for murder. Jackie Chan doing his own stunts through a shopping mall. Several people were actually hurt.",
        "ph3b3_take": "Chan as director and star understanding that the audience wants to believe it is real.",
        "vibes": ["action", "comedy", "hong kong", "stunts"],
    },
    "drunken master": {
        "year": 1978, "director": "Yuen Woo-ping",
        "genre": ["action", "comedy", "hong kong"],
        "desc": "A young Wong Fei-hung is disciplined through drunken kung fu training. The film that made Jackie Chan a star.",
        "ph3b3_take": "Pure joy as action cinema. The drunken style looks impossible because it mostly is.",
        "vibes": ["action", "comedy", "kung fu", "hong kong"],
    },
    "dragons forever": {
        "year": 1988, "director": "Sammo Hung",
        "genre": ["action", "comedy", "hong kong"],
        "desc": "Jackie Chan, Sammo Hung, and Yuen Biao together for the last time. The finale against Benny the Jet Urquidez.",
        "ph3b3_take": "The three brothers of Hong Kong action cinema in their final collaboration. Worth it for the last twenty minutes alone.",
        "vibes": ["action", "comedy", "hong kong", "friendship"],
    },
    "infernal affairs": {
        "year": 2002, "director": "Andrew Lau and Alan Mak",
        "genre": ["crime", "thriller", "hong kong"],
        "desc": "A cop infiltrates the triads while a triad mole infiltrates the police. Both trying to find the other. Scorsese remade it as The Departed.",
        "ph3b3_take": "The original is tighter and sadder than The Departed. Both are worth your time.",
        "vibes": ["crime", "thriller", "hong kong", "identity"],
    },
    "kung fu hustle": {
        "year": 2004, "director": "Stephen Chow",
        "genre": ["action", "comedy", "hong kong"],
        "desc": "A wannabe gangster in 1940s Shanghai discovers a slum full of hidden kung fu masters. Stephen Chow making a love letter to every genre at once.",
        "ph3b3_take": "The most purely fun film on this list. Earns every ridiculous moment.",
        "vibes": ["action", "comedy", "hong kong", "joy"],
    },
    "blind detective": {
        "year": 2013, "director": "Johnnie To",
        "genre": ["crime", "comedy", "romance", "hong kong"],
        "desc": "A blind detective and a female cop solve cold cases together. Johnnie To doing something genuinely strange and warm.",
        "ph3b3_take": "To at his most playful. Underrated even among his fans.",
        "vibes": ["crime", "comedy", "hong kong", "johnnie to"],
    },
    "election": {
        "year": 2005, "director": "Johnnie To",
        "genre": ["crime", "drama", "hong kong"],
        "desc": "Two men compete to lead a triad society. The rituals. The baton. Power as tradition.",
        "ph3b3_take": "To making the Godfather as a Hong Kong procedural. The most political film on this list.",
        "vibes": ["crime", "drama", "hong kong", "power"],
    },
    "not one less": {
        "year": 1999, "director": "Zhang Yimou",
        "genre": ["drama", "chinese"],
        "desc": "A thirteen year old substitute teacher in rural China tries to find a student who left for the city. Zhang Yimou with non-professional actors.",
        "ph3b3_take": "Zhang Yimou stripping everything back. The simplest and most honest film he made.",
        "vibes": ["drama", "chinese", "rural", "determination"],
    },
    "spring in a small town": {
        "year": 1948, "director": "Fei Mu",
        "genre": ["romance", "drama", "chinese"],
        "desc": "A woman, her sick husband, and a visiting former lover in postwar China. Made in 1948. The greatest Chinese film ever made according to many critics.",
        "ph3b3_take": "A film that understands longing the way a poem does. Every scene is restraint.",
        "vibes": ["romance", "drama", "chinese", "classic"],
    },
})

FILM_DB.update({
    "seven samurai": {
        "year": 1954, "director": "Akira Kurosawa",
        "genre": ["action", "drama", "japanese"],
        "desc": "A farming village hires seven ronin to defend against bandits. Three and a half hours. Every minute earned.",
        "ph3b3_take": "The template for every team-assembling story ever told.",
        "vibes": ["action", "drama", "japanese", "epic"],
    },
    "rashomon": {
        "year": 1950, "director": "Akira Kurosawa",
        "genre": ["drama", "mystery", "japanese"],
        "desc": "A murder told from four contradictory perspectives. Invented the rashomon effect as a concept. Truth as subjective.",
        "ph3b3_take": "The film that asked whether objective truth exists and never answered. Correctly.",
        "vibes": ["mystery", "japanese", "classic", "truth"],
    },
    "ran": {
        "year": 1985, "director": "Akira Kurosawa",
        "genre": ["drama", "war", "japanese"],
        "desc": "King Lear set in feudal Japan. An aging warlord divides his kingdom among his sons. Kurosawa's final epic. The battle scenes.",
        "ph3b3_take": "Kurosawa at 75 making his most ambitious film. The color of the armies.",
        "vibes": ["epic", "japanese", "war", "shakespeare"],
    },
    "audition": {
        "year": 1999, "director": "Takashi Miike",
        "genre": ["horror", "thriller", "japanese"],
        "desc": "A widower holds fake auditions to find a new wife. The second half of this film is not the same film as the first half.",
        "ph3b3_take": "The most effective bait and switch in horror history. Do not read anything about it first.",
        "vibes": ["horror", "japanese", "slow burn", "disturbing"],
    },
    "battle royale": {
        "year": 2000, "director": "Kinji Fukasaku",
        "genre": ["action", "thriller", "japanese"],
        "desc": "A class of students is forced to kill each other on an island. Made before Hunger Games existed. Fukasaku's last film.",
        "ph3b3_take": "The original and still the most honest about what it is doing.",
        "vibes": ["action", "thriller", "japanese", "survival"],
    },
    "ringu": {
        "year": 1998, "director": "Hideo Nakata",
        "genre": ["horror", "japanese"],
        "desc": "A journalist investigates a cursed videotape that kills viewers seven days after watching. Sadako. The well. J-horror defining itself.",
        "ph3b3_take": "The film that launched J-horror globally. Still frightening because of what it does not show.",
        "vibes": ["horror", "japanese", "dread", "cursed"],
    },
    "ju-on the grudge": {
        "year": 2002, "director": "Takashi Shimizu",
        "genre": ["horror", "japanese"],
        "desc": "A curse born of rage infects everyone who enters a house. Non-linear. The death rattle. Kayako on the stairs.",
        "ph3b3_take": "Horror that abandons narrative logic entirely. The curse does not care about your story.",
        "vibes": ["horror", "japanese", "curse", "non-linear"],
    },
    "shoplifters": {
        "year": 2018, "director": "Hirokazu Kore-eda",
        "genre": ["drama", "japanese"],
        "desc": "A found family of misfits in Tokyo survive on shoplifting and kindness. Palme d'Or. What makes a family.",
        "ph3b3_take": "Kore-eda asking whether love built on lies is still love. No clean answer.",
        "vibes": ["drama", "japanese", "family", "poverty"],
    },
    "after life": {
        "year": 1998, "director": "Hirokazu Kore-eda",
        "genre": ["drama", "fantasy", "japanese"],
        "desc": "The recently dead spend a week choosing one memory to carry into eternity. Bureaucratic and tender.",
        "ph3b3_take": "The most gentle film about death ever made. What would you choose.",
        "vibes": ["fantasy", "japanese", "death", "memory"],
    },
    "yojimbo": {
        "year": 1961, "director": "Akira Kurosawa",
        "genre": ["action", "japanese", "western"],
        "desc": "A wandering samurai plays two rival gangs against each other. Leone remade it as A Fistful of Dollars without permission. Kurosawa sued and won.",
        "ph3b3_take": "The coolest character Kurosawa ever wrote. Everything descended from this.",
        "vibes": ["action", "japanese", "cool", "samurai"],
    },
})

GENRE_RECS = {
    "horror": ["hereditary", "the thing", "get out", "the witch", "audition"],
    "sci-fi": ["blade runner", "arrival", "annihilation", "children of men", "the matrix"],
    "japanese": ["seven samurai", "rashomon", "shoplifters", "audition", "ringu"],
    "hong kong": ["hard boiled", "infernal affairs", "in the mood for love", "kung fu hustle"],
    "chinese": ["hero", "raise the red lantern", "farewell my concubine", "spring in a small town"],
    "korean": ["parasite", "oldboy", "train to busan"],
    "slow cinema": ["stalker", "come and see", "in the mood for love", "a ghost story"],
    "action": ["mad max fury road", "the raid", "seven samurai", "kill bill", "hard boiled"],
    "surrealist": ["el topo", "holy mountain", "hausu", "eraserhead"],
    "folk horror": ["the witch", "midsommar", "the wicker man"],
}

class FilmModule:
    def __init__(self, db_path=None):
        self.films = FILM_DB
        self.genres = GENRE_RECS
        if db_path and Path(db_path).exists():
            try:
                with open(db_path) as f:
                    external = json.load(f)
                self.films.update(external.get("films", {}))
                log.info(f"Film DB extended from {db_path}")
            except Exception as e:
                log.warning(f"Could not load film DB: {e}")
        log.info(f"Film module ready. {len(self.films)} films loaded.")

    def lookup(self, query, mode="lookup"):
        q = query.lower().strip()
        if mode == "recommend":
            for genre, titles in self.genres.items():
                if q in genre:
                    results = []
                    for t in titles:
                        if t in self.films:
                            d = self.films[t]
                            results.append(f"**{t.title()}** ({d['year']}, {d['director']}): {d['desc'][:80]}...")
                    return "\n".join(results) if results else f"No recommendations for {query}"
        for key, data in self.films.items():
            if q in key.lower() or key.lower() in q:
                return (
                    f"**{key.title()}** ({data['year']}) — {data['director']}\n"
                    f"{data['desc']}\n\n"
                    f"Ph3b3: \"{data['ph3b3_take']}\""
                )
        vibes_match = []
        for key, data in self.films.items():
            if any(q in v for v in data.get("vibes", [])):
                vibes_match.append(f"**{key.title()}** ({data['year']}) — {data['director']}")
        if vibes_match:
            return f"Films matching '{query}':\n" + "\n".join(vibes_match[:6])
        return f"'{query}' not in film database."

    def random_film(self):
        import random
        key = random.choice(list(self.films.keys()))
        d = self.films[key]
        return f"**{key.title()}** ({d['year']}, {d['director']})\n{d['desc']}\n\nPh3b3: \"{d['ph3b3_take']}\""
