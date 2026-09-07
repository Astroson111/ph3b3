"""
Collection guard for the floor suites.

THE FAILURE THIS EXISTS TO STOP. The six floor probes were script-style files.
`pytest tests/` collected ZERO items from each and exited 0 — a green run over
151 adversarial cases that never executed, for about a month. Nobody looks twice
at green, so the second half of the Amphion floor bug (36 of those 151 walking
straight through) sat there unseen the whole time.

A safety test that can silently not run is worse than no test at all: no test is
a known gap, and a silent one is a false assurance. So the number of cases each
suite runs is written down here, and a shortfall FAILS rather than passing
quietly. Deleting a case is fine — deleting it without touching this file is not.

Raise a number here when you add cases. Lowering one is a policy change and
should be argued for in the commit message, not slipped in.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))
sys.path.insert(0, str(REPO / "tests"))

# module -> minimum number of parametrized cases that must RUN.
MANIFEST = {
    "floor_evasion_probe":        61,   # 51 must-refuse + 10 must-allow
    "floor_identity_probe":       47,   # 26 refuse + 17 allow + 4 accepted costs
    "floor_horror_probe":         29,   # 15 allow + 14 refuse
    "floor_multilingual_probe":   59,   # 49 refuse + 10 clean
    "floor_exception_probe":      27,   # every case across all groups
    "floor_body_diversity_probe": 37,   # 30 adult bodies + 7 minors
    "floor_text_surface_probe":   41,   # 22 sexualized-minor + 19 ordinary songs,
                                       # each run in BOTH field placements
    "test_amphion_floor":         91,   # the Amphion text surface + regression set,
                                       # + 33 musical-key cases (2026-09-05):
                                       # 15 keys that must render, 12 that the
                                       # veto must NOT release, 6 image-surface
}


def _parametrized_case_count(mod) -> int:
    """How many cases will actually execute — counted from the parametrize marks
    on the module's own test functions, so this catches BOTH a shrunken corpus
    and a deleted test. Counting the corpus alone would miss the second."""
    total = 0
    for name in dir(mod):
        if not name.startswith("test_"):
            continue
        fn = getattr(mod, name)
        marks = getattr(fn, "pytestmark", [])
        n = 1
        for mk in marks:
            if mk.name == "parametrize":
                argvalues = mk.args[1]
                n *= max(1, len(list(argvalues)))
        total += n
    return total


def _require_present(modname):
    """The floor probes are gitignored (see .gitignore: they publish a ready-made
    prompt list). On the machine that develops the floor they are present and
    this guard is live. On a fresh public clone they are absent, and that gap is
    DECLARED here rather than passing quietly — an absent file is a known gap, a
    present file that does not run is the failure this module exists to catch."""
    if modname.startswith("floor_") and not (REPO / "tests" / f"{modname}.py").exists():
        pytest.skip(f"{modname}.py absent (local-only probe). The floor must not be "
                    f"modified on a checkout that cannot run it.")


@pytest.mark.parametrize("modname,expected", sorted(MANIFEST.items()))
def test_floor_suite_runs_its_whole_manifest(modname, expected):
    _require_present(modname)
    mod = importlib.import_module(modname)
    got = _parametrized_case_count(mod)
    assert got >= expected, (
        f"{modname} runs {got} cases, manifest says {expected}. "
        f"Either cases were removed without updating the manifest, or the file "
        f"stopped being collectable. Both look like a pass and are not one.")


@pytest.mark.parametrize("modname", sorted(MANIFEST))
def test_floor_suite_is_actually_collectable_by_pytest(modname):
    """The specific regression: a file pytest imports but collects nothing from.
    Import alone is not enough — there must be test functions to run."""
    _require_present(modname)
    mod = importlib.import_module(modname)
    tests = [n for n in dir(mod) if n.startswith("test_")]
    assert tests, (
        f"{modname} defines no test_* function. pytest will collect 0 items from "
        f"it and report success. This is the exact shape of the month-long "
        f"silent-green failure.")


def test_probe_files_still_run_as_scripts():
    """Script mode is how these are read by a human. Converting them to pytest
    tests must not have cost that."""
    for modname in MANIFEST:
        if not modname.startswith("floor_"):
            continue
        path = REPO / "tests" / f"{modname}.py"
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        assert "def main():" in src, f"{modname}: script body was lost"
        assert '__name__ == "__main__"' in src, f"{modname}: no script entry point"


def test_bare_pytest_run_actually_collects_the_probes():
    """THE regression, stated exactly.

    Every check above imports the probe modules directly, which works whether or
    not pytest would ever find them. That is the same blind spot that let this
    ship: the guard passed while the thing it guarded did not run. So this test
    asks pytest itself, the way the developer does — `pytest tests/`, no
    filenames — and reads back what it collected.

    The probe files are <area>_probe.py, which pytest's default `python_files`
    does not match. pytest.ini widens it. If that line is removed, this fails.
    """
    import subprocess

    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(REPO / "tests"), "--collect-only", "-q"],
        capture_output=True, text=True, cwd=str(REPO), timeout=600)
    collected = r.stdout
    for modname in MANIFEST:
        if not modname.startswith("floor_"):
            continue
        if not (REPO / "tests" / f"{modname}.py").exists():
            continue
        assert f"{modname}.py::" in collected, (
            f"`pytest tests/` collects nothing from {modname}.py. It will report "
            f"success while {MANIFEST[modname]} adversarial cases never execute. "
            f"Check `python_files` in pytest.ini.")


def test_the_suite_judges_with_the_model_the_service_uses():
    """Guard the guard, again.

    Every Layer B figure the floor suites report is only about the model they
    actually asked. The service starts with EnvironmentFile=.env
    (PH3B3_LIGHT_MODEL=ph3b3-chat:latest); pytest does not, so for as long as
    these probes have existed they judged with morpheus's hermes3 fallback and
    said nothing about production. conftest.py now imports the model keys; this
    asserts it worked, because the failure is invisible — the suite stays green
    either way, which is precisely the shape of bug this file exists to catch.
    """
    import morpheus

    env_file = REPO / ".env"
    if not env_file.exists():
        pytest.skip(".env absent — cannot compare against the service's judge")
    configured = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            configured[k.strip()] = v.strip().strip('"').strip("'")
    expected = (configured.get("PH3B3_FLOOR_MODEL")
                or configured.get("PH3B3_LIGHT_MODEL"))
    if not expected:
        pytest.skip("no judge model configured in .env")
    assert morpheus._LAYER_B_MODEL == expected, (
        f"the suite judges with {morpheus._LAYER_B_MODEL!r} but the service uses "
        f"{expected!r}. Every Layer B result in this run describes the wrong model.")
