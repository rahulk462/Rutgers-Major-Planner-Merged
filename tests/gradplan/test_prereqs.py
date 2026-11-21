from gradplan.prereqs import Leaf, Op, parse, satisfied, to_text

REAL_344 = ("((01:198:112 DATA STRUCTURES  or 14:332:351 PROGRM METHODOLOGYII ) and (01:198:206 INTRODUCTION TO "
            "DISCRETE STRUCTURES II ))<em> OR </em> ((01:198:112 DATA STRUCTURES  or 14:332:351 PROGRM METHODOLOGYII ) "
            "and (01:640:477 MATHEMATICAL THEORY OF PROBABILITY ))")


def test_real_soc_string():
    r = parse(REAL_344)
    assert r.ok
    assert satisfied(r.tree, {"01:198:112", "01:198:206"})
    assert satisfied(r.tree, {"14:332:351", "01:640:477"})
    assert not satisfied(r.tree, {"01:198:112"})
    assert not satisfied(r.tree, {"01:198:206", "01:640:477"})


def test_title_words_are_not_operators():
    r = parse("(01:640:244 DIFFERENTIAL EQUATIONS FOR ENGINEERING AND PHYSICS and 01:640:300 INTRO MATH REASONING )")
    assert r.ok
    assert to_text(r.tree) == "01:640:244 AND 01:640:300"


def test_uppercase_and_and_duplicates():
    r = parse("(14:332:331 ARCH and 14:332:331 ARCH and 14:332:351 PM2 ) OR (14:332:331 ARCH and 01:198:112 DS )")
    assert r.ok
    assert satisfied(r.tree, {"14:332:331", "01:198:112"})
    r2 = parse("(14:332:231 DIGITAL LOGIC DESIGN ) AND (14:332:233 DIGITAL LOGIC DESIGN LAB )")
    assert isinstance(r2.tree, Op) and r2.tree.op == "and"


def test_or_higher():
    r = parse("Any Course EQUAL or GREATER Than: (01:640:112 PRECALCULUS PART II )")
    assert r.tree == Leaf("01:640:112", or_higher=True)
    assert satisfied(r.tree, {"01:640:151"})
    assert not satisfied(r.tree, {"01:640:111"})


def test_absorption_simplifies():
    r = parse("(01:640:152 C2 ) OR (01:640:152 C2 and 01:750:203 PHYS )")
    assert r.tree == Leaf("01:640:152")


def test_flags_unparseable_text():
    r = parse("Permission of instructor required")
    assert not r.ok
    r = parse("((01:198:111 INTRO ) or (01:198:112 DS )")
    assert any("parenthes" in f for f in r.flags)
    r = parse("(01:198:111 INTRO ) or")
    assert not r.ok


def test_override_syntax_with_coreq():
    r = parse("01:750:203 and coreq:01:750:204", source="override")
    assert r.ok
    assert satisfied(r.tree, {"01:750:203"}, same_term={"01:750:204"})
    assert not satisfied(r.tree, {"01:750:203"})


def test_empty_is_none():
    assert parse("").tree is None
    assert satisfied(None, set())
