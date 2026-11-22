from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPIES = [ROOT / "NOTICE", ROOT / "js" / "NOTICE", ROOT / "python" / "NOTICE"]


def test_every_package_carries_the_notice():
    missing = [str(p.relative_to(ROOT)) for p in COPIES if not p.is_file()]
    assert not missing, f"the LGPL notice is missing from: {missing}"


def test_the_copies_have_not_drifted():
    texts = {p: p.read_text() for p in COPIES}
    first = texts[COPIES[0]]
    differ = [str(p.relative_to(ROOT)) for p, t in texts.items() if t != first]
    assert not differ, (
        f"these NOTICE copies differ from the root one: {differ}. Copy the root "
        f"over them; a notice that says different things in different packages "
        f"is worse than one that says nothing.")


def test_it_names_what_it_is_for():
    text = COPIES[0].read_text()
    for needle in ("myuri", "@jwriter20/myuri", "cursory", "cursory-js", "LGPL-3.0-or-later", "Vinyzu"):
        assert needle in text, f"the notice does not mention {needle!r}"


def test_it_records_that_we_do_not_bundle():
    text = COPIES[0].read_text()
    assert "vendor" in text.lower() and "bundle" in text.lower(), (
        "the notice no longer records that these are installed dependencies "
        "rather than vendored code, which is the arrangement the licence "
        "analysis depends on")
