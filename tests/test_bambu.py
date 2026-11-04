"""Bambu Studio TPU project files: the shape goes in unchanged, the settings name Bambu's own presets."""
import json
import zipfile

import numpy as np
import pytest
import trimesh

from footscan import bambu
from footscan.insole import write_3mf


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture
def profiles(tmp_path):
    """A small stand-in for Bambu Studio's BBL profile folder, shaped like the real one."""
    root = tmp_path / "BBL"
    _write(root / "machine" / "fdm_machine_common.json",
           {"name": "fdm_machine_common", "from": "system", "instantiation": "false",
            "printable_area": ["0x0", "100x0", "100x100", "0x100"], "machine_start_gcode": "OLD", "nozzle_diameter": ["0.4"]})
    _write(root / "machine" / "fdm_bbl_template.json",
           {"name": "fdm_bbl_template", "from": "system", "instantiation": "false", "machine_start_gcode": "G28 ; home"})
    _write(root / "machine" / "Bambu Lab X1 Carbon 0.4 nozzle.json",
           {"name": "Bambu Lab X1 Carbon 0.4 nozzle", "inherits": "fdm_machine_common", "include": ["fdm_bbl_template"],
            "from": "system", "instantiation": "true", "printer_model": "Bambu Lab X1 Carbon",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"], "bed_exclude_area": ["0x0", "18x0", "18x28", "0x28"],
            "default_print_profile": "0.20mm Standard @BBL X1C"})
    _write(root / "machine" / "Bambu Lab A1 0.4 nozzle.json",
           {"name": "Bambu Lab A1 0.4 nozzle", "inherits": "fdm_machine_common", "from": "system",
            "instantiation": "true", "printable_area": ["0x0", "256x0", "256x256", "0x256"]})
    _write(root / "process" / "fdm_process_common.json",
           {"name": "fdm_process_common", "from": "system", "instantiation": "false", "wall_loops": "2",
            "sparse_infill_pattern": "grid", "sparse_infill_density": "15%", "layer_height": "0.2"})
    speeds = {k: ["200", "350"] for k in ("outer_wall_speed", "inner_wall_speed", "sparse_infill_speed",
                                         "internal_solid_infill_speed", "top_surface_speed", "gap_infill_speed",
                                         "initial_layer_speed", "initial_layer_infill_speed", "bridge_speed")}
    _write(root / "process" / "0.20mm Standard @BBL X1C.json",
           {"name": "0.20mm Standard @BBL X1C", "inherits": "fdm_process_common", "from": "system",
            "instantiation": "true", "print_extruder_variant": ["Direct Drive Standard", "Direct Drive High Flow"],
            "compatible_printers": ["Bambu Lab X1 Carbon 0.4 nozzle"], **speeds})
    _write(root / "filament" / "Bambu TPU 95A HF @BBL X1C.json",
           {"name": "Bambu TPU 95A HF @BBL X1C", "from": "system", "instantiation": "true", "filament_id": "GFU00",
            "filament_type": ["TPU"], "nozzle_temperature": ["230", "230"], "hot_plate_temp": ["35"],
            "filament_extruder_variant": ["Direct Drive Standard", "Direct Drive High Flow"],
            "compatible_printers": ["Bambu Lab X1 Carbon 0.4 nozzle"]})
    return root


X1C = dict(printer="Bambu Lab X1 Carbon 0.4 nozzle", process="0.20mm Standard @BBL X1C",
           filament="Bambu TPU 95A HF @BBL X1C")


def _insole_like(length=275.0, width=100.0, height=6.0):
    """A sole-sized flat oval, bottom on z = 0 (placement and size checks need the size, not a foot's shape).

    Rounded ends like a real insole: a 275 mm rectangle wouldn't fit a 256 mm bed even turned, an oval does.
    """
    oval = trimesh.creation.cylinder(radius=0.5, height=1.0, sections=96)
    oval.apply_scale([length, width, height])
    oval.apply_translation([length / 2 - 3, 0, height / 2])
    return oval


def test_project_keeps_the_insole_exactly_its_size_and_lays_it_flat_on_the_bed(tmp_path, profiles):
    box = _insole_like()
    src = tmp_path / "left-insole.3mf"
    write_3mf(box, src, title="left-insole", notes="NOT A MEDICAL DEVICE.")
    out = tmp_path / "left-insole-tpu.3mf"
    info = bambu.tpu_project(src, out, profiles, bed_type="High Temp Plate", **X1C)

    r = bambu.read_project(out)
    assert np.allclose(r["vertices"], box.vertices, atol=1e-3)  # the mesh itself is untouched
    assert len(r["faces"]) == len(box.faces)
    M = np.asarray(r["transform"]).reshape(4, 3)[:3]
    assert np.allclose(M @ M.T, np.eye(3), atol=1e-5) and np.isclose(np.linalg.det(M), 1.0)  # a turn, no scaling
    placed = bambu.placed_vertices(r["transform"], r["vertices"])
    assert np.isclose(np.ptp(placed[:, 2]), 6.0) and np.isclose(placed[:, 2].min(), 0.0, atol=1e-6)
    assert np.isclose(np.ptp(r["vertices"][:, 0]), 275.0) and info["length_mm"] == 275.0
    # 275 mm doesn't lie straight on a 256 mm bed: turned, inside the bed, clear of the front-left no-print corner
    assert info["angle_deg"] != 0.0
    assert placed[:, :2].min() >= 3.0 - 1e-6 and placed[:, :2].max() <= 253.0 + 1e-6
    assert not np.any((placed[:, 0] < 18 + 3) & (placed[:, 1] < 28 + 3))


def test_project_settings_name_bambus_presets_and_list_only_the_tpu_process_changes(tmp_path, profiles):
    out = tmp_path / "insole.3mf"
    bambu.tpu_project(_stl(tmp_path), out, profiles,
                      bed_type="High Temp Plate", **X1C)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        model = z.read("3D/3dmodel.model").decode()
    for part in ("3D/3dmodel.model", "3D/Objects/object_1.model", "Metadata/project_settings.config",
                 "Metadata/model_settings.config", "[Content_Types].xml", "_rels/.rels"):
        assert part in names
    # Bambu Studio only loads a project's settings when the file says Bambu Studio made it
    assert ">BambuStudio-02.04.00.70</metadata>" in model

    cfg = bambu.read_project(out)["config"]
    assert cfg["printer_settings_id"] == X1C["printer"] and cfg["print_settings_id"] == X1C["process"]
    assert cfg["filament_settings_id"] == [X1C["filament"]] and cfg["filament_ids"] == ["GFU00"]
    assert cfg["curr_bed_type"] == "High Temp Plate"
    assert cfg["different_settings_to_system"] == [";".join(sorted(bambu.TPU_INSOLE_PROCESS)), "", ""]
    assert cfg["wall_loops"] == "3" and cfg["sparse_infill_pattern"] == "gyroid" and cfg["sparse_infill_density"] == "20%"
    assert cfg["outer_wall_speed"] == ["25", "25"]  # every nozzle kind gets the slow speed
    assert cfg["sparse_infill_speed"] == ["40", "40"]
    # the filament and printer presets go in as Bambu ships them
    assert cfg["nozzle_temperature"] == ["230", "230"] and cfg["hot_plate_temp"] == ["35"]
    assert cfg["filament_self_index"] == ["1", "1"]
    assert cfg["layer_height"] == "0.2"


def _stl(tmp_path):
    p = tmp_path / "insole.stl"
    _insole_like().export(p)
    return p


def test_a_preset_takes_its_parent_first_then_its_templates_then_its_own_values(profiles):
    m = bambu.flatten_preset(profiles, "machine", X1C["printer"])
    assert m["machine_start_gcode"] == "G28 ; home"  # template beats parent
    assert m["printable_area"] == ["0x0", "256x0", "256x256", "0x256"]  # own value beats both
    assert m["nozzle_diameter"] == ["0.4"]  # inherited


def test_a_filament_or_process_made_for_another_printer_is_refused(profiles):
    with pytest.raises(ValueError, match="not made for"):
        bambu.project_config(profiles, "Bambu Lab A1 0.4 nozzle", X1C["process"], X1C["filament"],
                             bed_type="Textured PEI Plate")


def test_a_change_that_is_not_a_process_setting_is_refused(profiles):
    with pytest.raises(KeyError, match="not process settings"):
        bambu.project_config(profiles, **X1C, bed_type="Textured PEI Plate", changes={"nozzle_temperature": "250"})


def test_an_insole_too_long_for_the_bed_is_refused_rather_than_scaled(tmp_path, profiles):
    with pytest.raises(ValueError, match="doesn't fit"):
        bambu.place_on_bed(_insole_like(length=380.0).vertices, ["0x0", "256x0", "256x256", "0x256"])


def test_the_printers_no_print_corner_is_kept_clear(profiles):
    """X1/P1 printers keep a front-left corner for the nozzle wipe and flow check; the insole turns away from it."""
    V = _insole_like().vertices
    corner = ["0x0", "70x0", "70x70", "0x70"]  # larger than a real one, so the plain diagonal would hit it
    placement = bambu.place_on_bed(V, ["0x0", "256x0", "256x256", "0x256"], corner, clearance=3.0)
    placed = bambu.placed_vertices(placement["transform"], V)
    assert not np.any((placed[:, 0] < 73) & (placed[:, 1] < 73))
    assert placement["room_mm"] >= 3.0


def test_a_pair_goes_on_two_plates_of_one_project_each_insole_unchanged(tmp_path, profiles):
    """Left on plate 1, right on plate 2: Bambu puts an object on a plate by where it lies, plates a bed + 1/5 apart."""
    left, right = _insole_like(), _insole_like(length=270.0)
    right.apply_scale([1, -1, 1])  # a mirror, like a right insole made from a left
    paths = []
    for name, m in (("left", left), ("right", right)):
        paths.append(tmp_path / f"{name}.stl")
        m.export(paths[-1])
    out = tmp_path / "pair.3mf"
    info = bambu.tpu_project(paths, out, profiles, bed_type="High Temp Plate", **X1C)

    r = bambu.read_project(out)
    assert [p["plate"] for p in info["plates"]] == [1, 2]
    assert [p["length_mm"] for p in info["plates"]] == [275.0, 270.0]
    assert r["model_settings"].count("<plate>") == 2
    stride = 256 * 1.2
    for k, (part, src) in enumerate(zip(r["parts"], (left, right))):
        # the same points (an STL round trip may list them in another order)
        got, want = part["vertices"], np.asarray(src.vertices)
        order = lambda v: v[np.lexsort(np.round(v, 2).T + 0.0)]  # noqa: E731
        assert len(got) == len(want) and np.allclose(order(got), order(want), atol=1e-3)
        placed = bambu.placed_vertices(part["transform"], part["vertices"])
        on_plate = placed[:, :2] - [k * stride, 0]
        assert on_plate.min() >= 3.0 - 1e-6 and on_plate.max() <= 253.0 + 1e-6, k
        assert np.isclose(placed[:, 2].min(), 0.0, atol=1e-6)


def test_a_slower_spool_lowers_the_filament_flow_limit_and_lists_it_as_a_filament_change(tmp_path, profiles):
    (profiles / "filament" / "Bambu TPU 95A HF @BBL X1C.json").write_text(json.dumps({
        "name": "Bambu TPU 95A HF @BBL X1C", "from": "system", "instantiation": "true", "filament_id": "GFU00",
        "filament_max_volumetric_speed": ["12", "12"], "nozzle_temperature": ["230", "230"],
        "filament_extruder_variant": ["Direct Drive Standard", "Direct Drive High Flow"],
        "compatible_printers": ["Bambu Lab X1 Carbon 0.4 nozzle"]}))
    cfg = bambu.project_config(profiles, **X1C, bed_type="High Temp Plate",
                               filament_changes={"filament_max_volumetric_speed": "2.5"})
    assert cfg["filament_max_volumetric_speed"] == ["2.5", "2.5"]
    assert cfg["different_settings_to_system"][1] == "filament_max_volumetric_speed"
    assert cfg["nozzle_temperature"] == ["230", "230"]
    with pytest.raises(KeyError, match="not filament settings"):
        bambu.project_config(profiles, **X1C, bed_type="High Temp Plate", filament_changes={"wall_loops": "4"})
