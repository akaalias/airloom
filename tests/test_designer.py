"""Headless-Claude designer: brief building and reply parsing."""
import json

from framevo.designer import _build_brief, _parse_proposals
from framevo.genome import GENOME_SPEC, Genome


def _fake_reply(n=2):
    base = Genome.baseline().as_dict()
    items = []
    for i in range(n):
        genes = {k: v for k, v in base.items()}
        genes["arm_waist_scale"] = 0.6 + 0.1 * i
        items.append({"rationale": f"hypothesis {i}", "genes": genes})
    return json.dumps(items)


def test_parse_valid_reply():
    out = _parse_proposals(_fake_reply(3), 3)
    assert len(out) == 3
    genes, rationale = out[0]
    assert set(genes) == {n for n, _, _ in GENOME_SPEC}
    assert rationale == "hypothesis 0"


def test_parse_clips_out_of_bounds():
    base = Genome.baseline().as_dict()
    base["deck_gap"] = 99.0  # way out of bounds
    out = _parse_proposals(json.dumps([{"genes": base}]), 1)
    assert out and out[0][0]["deck_gap"] <= 0.045


def test_parse_rejects_garbage():
    assert _parse_proposals("no json here", 3) == []
    assert _parse_proposals('[{"genes": {"bogus": 1}}]', 3) == []
    # prose around the array is tolerated
    wrapped = "Sure! Here you go:\n" + _fake_reply(1) + "\nHope that helps."
    assert len(_parse_proposals(wrapped, 3)) == 1
