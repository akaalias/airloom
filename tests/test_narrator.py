"""Narrator: reply parsing must survive one bad note without losing all."""
import json

from airloom.narrator import _parse_notes

H1, H2, H3 = "aaa111", "bbb222", "ccc333"


def _sections(tag):
    return {"hypothesis": f"hyp {tag}", "method": f"met {tag}",
            "result": f"res {tag}"}


def test_parse_strict_json():
    text = json.dumps({H1: _sections(1), H2: _sections(2)})
    got = _parse_notes("preamble " + text + " postamble", [H1, H2])
    assert set(got) == {H1, H2}
    assert got[H1]["hypothesis"] == "hyp 1"


def test_salvages_around_one_malformed_note():
    # H2's note has an unescaped quote -> full-object json.loads fails;
    # per-candidate salvage must still recover H1 and H3
    text = ('{"%s": %s, "%s": {"hypothesis": "said "oops" here", '
            '"method": "m", "result": "r"}, "%s": %s}'
            % (H1, json.dumps(_sections(1)), H2, H3, json.dumps(_sections(3))))
    got = _parse_notes(text, [H1, H2, H3])
    assert H1 in got and H3 in got and H2 not in got
    assert got[H3]["result"] == "res 3"


def test_no_json_at_all():
    assert _parse_notes("I could not do that, sorry.", [H1]) == {}
