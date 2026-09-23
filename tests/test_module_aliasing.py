"""The two spellings of a module are ONE object.

sys.path carries both the repo root and modules/, so `import morpheus` and
`import modules.morpheus` would otherwise load the same file twice under two
names with separate state. Production imports the bare name. A test patching
the dotted one patches something the code under test never reaches, and then
passes while asserting nothing — which happened four times on 2026-09-23 before
it was named.

conftest aliases them AFTER the environment is settled. Not before: importing
the namespace early froze morpheus._LAYER_B_MODEL to the default, ahead of the
.env judge override, and the whole suite would have judged Layer B with the
wrong model while staying green.
"""
import pytest


@pytest.mark.parametrize("name", ["morpheus", "herakles", "watermark", "amphion"])
def test_the_two_spellings_are_one_object(name):
    import importlib
    bare = importlib.import_module(name)
    dotted = importlib.import_module(f"modules.{name}")
    assert bare is dotted, (
        f"modules.{name} and {name} are different objects again — a test that "
        f"patches one will silently not affect the code that imports the other")


def test_patching_either_spelling_reaches_the_other():
    """The property that actually matters, exercised rather than asserted."""
    import morpheus, modules.morpheus as dotted
    original = morpheus.qwen_open
    try:
        dotted.qwen_open = lambda: "sentinel"
        assert morpheus.qwen_open() == "sentinel"
    finally:
        morpheus.qwen_open = original
