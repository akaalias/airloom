"""Headless-Claude designer: brief building and reply parsing."""
import json

from airloom.dbstore import Store
from airloom.designer import _build_brief, _parse_proposals
from airloom.genome import GENOME_SPEC, Genome


def _fresh_run_store(tmp_path):
    store = Store(tmp_path / "run.db")
    store.create_run("r1", seed=1, optimizer="ga", population=8,
                     generations=4, config_json="{}", root=tmp_path)
    return store


def test_brief_gen0_and_inspiration(tmp_path):
    store = _fresh_run_store(tmp_path)
    brief = _build_brief(store, "r1", 3)
    assert "generation 0" in brief          # no elites yet -> opening wording
    assert "USER INSPIRATION" not in brief  # none recorded
    assert "no generations evaluated yet" in brief
    assert "(none yet)" in brief            # no earlier designer proposals

    store.set_inspiration("r1", "ideas/frogs.md",
                          "think of the shapes of frogs")
    brief = _build_brief(store, "r1", 3)
    assert "USER INSPIRATION" in brief
    assert "shapes of frogs" in brief
    store.close()


def test_pivot_brief_and_history(tmp_path):
    from airloom.dbstore import CandidateRow
    store = _fresh_run_store(tmp_path)
    base = Genome.baseline()
    store.insert_candidate("r1", CandidateRow(
        hash=base.hash, generation_born=0, parent_a=None, parent_b=None,
        operator="designer", mutation_mag=None, genome=base.as_dict(),
        frame_mass=0.14, total_mass=0.9, material="cf_plate", valid=True,
        failure_reason=None, fitness=8.5, mean_whkm=8.0, worst_whkm=9.0,
        f1_hz=None, stl_path=None, png_path=None))
    store.record_designer_round("r1", 0, "opening", "PROMPT", [
        {"hash": base.hash, "rationale": "stock as anchor"}], [])
    for g in range(4):  # flat history -> a real stall
        store.set_population("r1", g, [(base.hash, 8.5)])
    brief = _build_brief(store, "r1", 3, kind="pivot")
    assert "PLATEAU" in brief and "step back" in brief.lower()
    assert "g0 8.500" in brief and "flat" in brief
    assert "stock as anchor" in brief    # its own past proposal + fate
    assert "fitness 8.500" in brief
    store.close()


def test_design_round_records_to_db(tmp_path, cfg, monkeypatch):
    import airloom.designer as dz
    store = _fresh_run_store(tmp_path)
    good = Genome.baseline().as_dict()
    doomed = dict(good, deck_gap=0.020)
    monkeypatch.setattr(dz, "_ask_claude", lambda prompt, n, model, t: (
        ([(good, "solid"), (doomed, "corner probe")]
         if "PRE-SCREEN FEEDBACK" not in prompt else []),
        "claude-test-model"))
    out = dz.design_round(store, "r1", cfg, generation=3, n=2, model="",
                          timeout_s=5, log_dir=tmp_path, kind="pivot")
    assert len(out) == 1
    rnd = store.designer_round_for("r1", 3)
    assert rnd["kind"] == "pivot" and "PLATEAU" in rnd["prompt"]
    assert rnd["model"] == "claude-test-model"
    acc = json.loads(rnd["accepted_json"])
    rej = json.loads(rnd["rejected_json"])
    assert acc[0]["rationale"] == "solid"
    assert rej[0]["rationale"] == "corner probe" and "stack" in rej[0]["reason"]
    store.close()


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


def test_prescreen_splits_valid_from_doomed(cfg):
    from airloom.designer import _prescreen, _repair_brief
    good = Genome.baseline().as_dict()
    doomed = dict(good, deck_gap=0.020)  # fails the FC-stack constraint
    ok, rejected = _prescreen([(good, "stock"), (doomed, "squat")], cfg)
    assert [r for _, r in ok] == ["stock"]
    assert len(rejected) == 1 and "stack" in rejected[0][2]
    brief = _repair_brief("BRIEF", rejected, 1)
    assert "PRE-SCREEN FEEDBACK" in brief and "stack" in brief


def test_parse_rejects_garbage():
    assert _parse_proposals("no json here", 3) == []
    assert _parse_proposals('[{"genes": {"bogus": 1}}]', 3) == []
    # prose around the array is tolerated
    wrapped = "Sure! Here you go:\n" + _fake_reply(1) + "\nHope that helps."
    assert len(_parse_proposals(wrapped, 3)) == 1
