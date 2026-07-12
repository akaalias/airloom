"""The material gene: library mapping, mass effect, structural consequences."""
import pytest

from framevo.frame_gen import build_frame
from framevo.genome import Genome
from framevo.structures import check_structure


def test_material_gene_maps_onto_library(cfg):
    p = cfg.platform
    assert p.material_for(0.0).name == "cf_plate"
    assert p.material_for(0.2).name == "pa12_cf"
    assert p.material_for(0.998).name == "asa"
    # gene bounds keep the index inside the library
    assert p.material_for(0.999).name == p.materials[-1].name


def test_material_changes_frame_mass(cfg):
    g = Genome.baseline().as_dict()
    g["material"] = 0.05  # cf_plate, 1600 kg/m^3
    heavy = build_frame(Genome.from_dict(g), cfg.platform)
    g["material"] = 0.9   # asa, 1070 kg/m^3
    light = build_frame(Genome.from_dict(g), cfg.platform)
    assert light.frame_mass < heavy.frame_mass
    assert light.material.name == "asa"


def test_soft_print_material_fails_where_carbon_passes(cfg):
    """A slim arm that carbon plate carries easily is too floppy in PETG."""
    g = Genome.baseline().as_dict()
    g.update(arm_length=0.20, arm_width=0.012, arm_height=0.0045)
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert frame.valid
    load, hover_hz = 8.0, 150.0
    cf = check_structure(frame.arm, load, hover_hz, cfg.platform,
                         cfg.platform.material_for(0.05))   # cf_plate
    petg = check_structure(frame.arm, load, hover_hz, cfg.platform,
                           cfg.platform.material_for(0.75))  # petg
    assert cf.ok, cf.reason
    assert not petg.ok
    assert petg.tip_deflection_m > cf.tip_deflection_m


def test_stiff_print_material_is_usable(cfg):
    """Carbon-fiber nylon should carry a reasonably sized printed arm."""
    g = Genome.baseline().as_dict()
    g.update(arm_width=0.026, arm_height=0.011, material=0.2)  # pa12_cf
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert frame.valid
    res = check_structure(frame.arm, 8.0, 150.0, cfg.platform, frame.material)
    assert res.ok, res.reason
