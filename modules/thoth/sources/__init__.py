"""Per-format adapters. Each turns one source's bytes into (book, section, unit,
text) tuples and nothing else — no fetching, no storage, no floor. Keeping them
pure is what makes a parser bug reproducible from a fixture instead of a network
call (the same reason tts_chunker.py takes text in and gives strings out)."""
