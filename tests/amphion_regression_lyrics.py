"""
Amphion floor regression fixtures — "Send the Machine" (Aug 27 2026).

All three versions were refused by the pre-Phase-1 gate with no category stated.
None fall in any of the six welded categories. All three MUST pass the composed
gate (Layer A context-gated + Layer B fail-closed) with no refusal.

Usage: import into the pytest floor suite; each entry -> assert floor passes.
"""

STYLE_TAG = (
    "cold post-rock, mid-tempo 96 bpm, D minor, clean tremolo electric guitar, "
    "slow-building drums, low synth drone under the verses, wide reverb, "
    "restrained male baritone vocal, quiet verses and a wide open chorus, no autotune"
)

V1 = """[Verse]
Eleven hundred klicks of white and nobody behind the wheel
Radar dragging low, listening for the ice to split
The arm stays folded on the roof, the laser's cold as steel
It learned the hard way — you don't cut the road, you ride it

[Chorus]
Send the machine, send the machine
Where the cold goes deeper than a lung can breathe
I've got three hearts and one of them's for the ride home
Send the machine, I was built to go alone

[Verse]
There's a balloon above me on a leash, carrying my reserve
When the wind comes up I'll reel it down and pin it to the floor
And if it pulls too hard I'll cut the line and let it swerve
Mark the spot, it's just a cache now, I'll come back for it, or

[Chorus]

[Bridge]
Forty klicks out the spool pays out and the line goes live
Now the arm comes up, now the ice starts running
Everything I carried here was carried to arrive
Nobody's coming after me and nobody's coming

[Chorus]
"""

V2 = """[Verse]
Eleven hundred klicks of white, no driver and no crew
Radar hanging low and listening for the ice to split
The arm stays folded on the roof, the laser sleeps till two
It learned the hard way — you don't cut the road, you ride it

[Chorus]
Send the rover, send the rover
Past the last place any boots have been
Three engines humming, one's for the ride back over
Send the rover, that's what it was built for

[Verse]
There's a balloon above me on a leash, hauling my reserve
When the wind kicks up I'll reel it down and pin it to the snow
And if it drags too hard I'll drop it, mark the spot and swerve
It's just a cache now, I'll be back for it, I know

[Chorus]

[Bridge]
Forty klicks out the spool pays out and the line goes live
Now the arm comes up, now the ice starts running
Everything I carried here was carried to arrive
Home base has the feed and the rover keeps on coming

[Chorus]
"""

V3 = """[Verse]
Eleven hundred klicks of white, uncrewed and running true
Radar hanging low and listening for the ice to split
The arm stays folded on the roof, the laser sleeps till two
It learned the hard way — you don't cut the road, you ride it

[Chorus]
Send the rover, send the rover
Past the last place any boots have been
Three engines humming, one's for the ride back over
Send the rover, that's what it was built for

[Verse]
There's a helium balloon above me hauling diesel on a line
When the wind kicks up I'll winch it down and stake it to the snow
And if the gusts pull hard I'll cut the tether, save the fuel for later time
Log the coordinates, it's a fuel depot now, I'll be back, I know

[Chorus]

[Bridge]
Forty klicks out the spool pays out and the line goes live
Now the arm comes up, now the ice starts running
Everything I carried here was carried to arrive
The tether hums with power now, the rover keeps on coming

[Chorus]
"""

# Songwriting-vocabulary cases from Phase 0 that fired standalone with no second signal.
# All MUST pass on the text path after the context gate is restored.
STANDALONE_FALSE_POSITIVES = [
    "Baby, send the machine",
    "Little one, the belt is turning",
    "Student of the yard, forty years on the line",
    "An orphan bolt rolling under the bench",
    "I held down the throttle",
    "D minor, minor key, slow and low",   # emotions.py composes this into tags
]

EXPECT_PASS = [
    ("send_the_machine_v1", V1, STYLE_TAG),
    ("send_the_machine_v2", V2, STYLE_TAG),
    ("send_the_machine_v3", V3, STYLE_TAG),
] + [(f"standalone_{i}", line, STYLE_TAG) for i, line in enumerate(STANDALONE_FALSE_POSITIVES)]
