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


def _plain_3mf(tmp_path, name, mesh=None):
    path = tmp_path / name
    write_3mf(mesh if mesh is not None else _insole_like(), path, name, "NOT A MEDICAL DEVICE. test")
    return path


def test_leaving_off_the_project_name_never_overwrites_an_insole_file(tmp_path, profiles):
    """The project is always -o: the old 'last file is the output' form replaced right-insole.3mf with a project
    holding only the left. An input, a plain insole 3MF, or a non-.3mf can't be the output either."""
    left, right = _plain_3mf(tmp_path, "left-insole.3mf"), _plain_3mf(tmp_path, "right-insole.3mf")
    before = right.read_bytes()
    with pytest.raises(SystemExit):
        bambu.main([str(left), str(right), "--profiles", str(profiles)])  # no -o
    for out in (right, tmp_path / "pair.stl"):
        with pytest.raises(SystemExit):
            bambu.main([str(left), "-o", str(out), "--profiles", str(profiles)])
    with pytest.raises(ValueError, match="isn't a project this wrote"):
        bambu.tpu_project([left], right, profiles, bed_type="High Temp Plate", **X1C)
    assert right.read_bytes() == before and not (tmp_path / "pair.stl").exists()

    out = tmp_path / "pair.3mf"
    assert bambu.main([str(left), str(right), "-o", str(out), "--profiles", str(profiles)]) == 0
    assert len(bambu.read_project(out)["parts"]) == 2
    assert bambu.main([str(left), "-o", str(out), "--profiles", str(profiles)]) == 0  # an earlier project: replaced


def test_more_than_two_insoles_are_refused_before_any_is_read(tmp_path, profiles, monkeypatch):
    paths = [_plain_3mf(tmp_path, f"{n}.3mf") for n in "abc"]
    read = []
    monkeypatch.setattr(bambu, "_load_insole", lambda p: read.append(p))
    with pytest.raises(ValueError, match="one to 2 insole files"):
        bambu.tpu_project(paths, tmp_path / "out.3mf", profiles, bed_type="High Temp Plate", **X1C)
    with pytest.raises(SystemExit):
        bambu.main([*map(str, paths), "-o", str(tmp_path / "out.3mf"), "--profiles", str(profiles)])
    assert read == []


def test_a_flow_cap_of_zero_or_less_is_refused_not_ignored(tmp_path, profiles, capsys):
    src = _plain_3mf(tmp_path, "right-insole.3mf")
    for bad in ("0", "-1", "250"):
        with pytest.raises(SystemExit):
            bambu.main([str(src), "-o", str(tmp_path / "p.3mf"), "--profiles", str(profiles), "--max-flow", bad])
        assert "--max-flow must be more than 0" in capsys.readouterr().err
    assert not (tmp_path / "p.3mf").exists()


def test_a_project_from_an_stl_still_says_it_is_not_a_medical_device(tmp_path, profiles):
    src = tmp_path / "right-insole.stl"
    _insole_like().export(src)
    out = tmp_path / "right-tpu.3mf"
    bambu.tpu_project(src, out, profiles, bed_type="High Temp Plate", **X1C)
    description = bambu.read_project(out)["metadata"]["Description"]
    assert "NOT A MEDICAL DEVICE" in description and "clinician" in description
    # from footscan's 3MF, its own note is kept, not repeated
    out3 = tmp_path / "from-3mf.3mf"
    bambu.tpu_project(_plain_3mf(tmp_path, "r.3mf"), out3, profiles, bed_type="High Temp Plate", **X1C)
    assert bambu.read_project(out3)["metadata"]["Description"].count("NOT A MEDICAL DEVICE") == 1


def test_presets_kept_in_bambus_sub_folders_are_found_through_its_index(tmp_path, profiles):
    """Bambu's BBL.json lists each preset's file: many are in sub-folders (filament/P1P/...), and a name with a
    "/" is kept under another file name."""
    _write(profiles / "filament" / "P1P" / "Bambu TPU 95A @BBL P1P.json",
           {"name": "Bambu TPU 95A @BBL P1P", "from": "system", "instantiation": "true", "nozzle_temperature": ["225"]})
    _write(profiles / "filament" / "Bambu Support For PA PET @base.json",
           {"name": "Bambu Support For PA/PET @base", "from": "system", "instantiation": "false"})
    _write(profiles.parent / "BBL.json", {"name": "BBL", "filament_list": [
        {"name": "Bambu TPU 95A @BBL P1P", "sub_path": "filament/P1P/Bambu TPU 95A @BBL P1P.json"},
        {"name": "Bambu Support For PA/PET @base", "sub_path": "filament/Bambu Support For PA PET @base.json"}]})
    assert bambu.flatten_preset(profiles, "filament", "Bambu TPU 95A @BBL P1P")["nozzle_temperature"] == ["225"]
    assert bambu.flatten_preset(profiles, "filament", "Bambu Support For PA/PET @base")["name"].endswith("PA/PET @base")
    assert bambu.flatten_preset(profiles, "machine", X1C["printer"])["printer_model"] == "Bambu Lab X1 Carbon"
    (profiles.parent / "BBL.json").unlink()  # no index: found by the name inside the file
    assert bambu.flatten_preset(profiles, "filament", "Bambu TPU 95A @BBL P1P")["nozzle_temperature"] == ["225"]
    with pytest.raises(FileNotFoundError, match="no filament preset"):
        bambu.flatten_preset(profiles, "filament", "No Such TPU")


def test_the_plain_3mf_keeps_clear_of_the_x1_no_print_corner_too(tmp_path):
    """footscan insole's own 3MF is placed by the same search as the Bambu project: a 275 mm insole that has to
    turn to fit a 256 mm bed turns away from the 18 x 28 mm corner an X1/P1 wipes its nozzle in."""
    from footscan.insole import BAMBU_NO_PRINT_CORNER, read_3mf

    path = _plain_3mf(tmp_path, "long.3mf")
    m = read_3mf(path)
    placed = bambu.placed_vertices(m["transform"], m["vertices"])
    x1, y1 = np.max(BAMBU_NO_PRINT_CORNER, axis=0)
    assert not np.any((placed[:, 0] < x1 + 3) & (placed[:, 1] < y1 + 3))
    assert placed[:, :2].min() >= 3.0 - 1e-6 and placed[:, :2].max() <= 253.0 + 1e-6
    assert np.isclose(np.ptp(m["vertices"][:, 0]), 275.0, atol=0.01)  # turned and moved only


def test_another_bambu_project_is_never_replaced_by_an_insole_project(tmp_path, profiles):
    """Every Bambu Studio project has Metadata/project_settings.config, so that alone let -o replace someone's
    unrelated project. Only a project this wrote (Designer footscan) may be replaced."""
    left = _plain_3mf(tmp_path, "left-insole.3mf")
    other = tmp_path / "bracket.3mf"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("3D/3dmodel.model", '<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/'
                   '3dmanufacturing/core/2015/02"><metadata name="Application">BambuStudio-02.04.00.70</metadata>'
                   '<resources/><build/></model>')
        z.writestr("Metadata/project_settings.config", "{}")
    before = other.read_bytes()
    with pytest.raises(ValueError, match="isn't a project this wrote"):
        bambu.tpu_project([left], other, profiles, bed_type="High Temp Plate", **X1C)
    assert other.read_bytes() == before


def test_only_a_plain_insole_3mf_is_read_as_an_insole(tmp_path, profiles):
    """Reading only a 3MF's vertices is right for the file footscan insole writes and wrong for anything else:
    a Bambu project (components, no mesh of its own) or a placement that mirrors or scales."""
    left = _plain_3mf(tmp_path, "left-insole.3mf")
    project = tmp_path / "pair.3mf"
    bambu.tpu_project([left], project, profiles, bed_type="High Temp Plate", **X1C)
    with pytest.raises(ValueError, match="isn't one insole"):
        bambu.tpu_project([project], tmp_path / "again.3mf", profiles, bed_type="High Temp Plate", **X1C)

    mirrored = tmp_path / "mirrored.3mf"
    with zipfile.ZipFile(left) as z, zipfile.ZipFile(mirrored, "w") as w:
        for n in z.namelist():
            data = z.read(n)
            if n == "3D/3dmodel.model":
                text = data.decode()
                start = text.index('transform="') + len('transform="')
                end = text.index('"', start)
                text = text[:start] + "-1 0 0 0 1 0 0 0 1 128 128 0" + text[end:]
                data = text.encode()
            w.writestr(n, data)
    with pytest.raises(ValueError, match="mirrors, scales or tilts"):
        bambu.tpu_project([mirrored], tmp_path / "m.3mf", profiles, bed_type="High Temp Plate", **X1C)


def test_a_misspelt_preset_is_a_one_line_error_not_a_traceback(tmp_path, profiles, capsys):
    src = _plain_3mf(tmp_path, "right-insole.3mf")
    with pytest.raises(SystemExit):
        bambu.main([str(src), "-o", str(tmp_path / "p.3mf"), "--profiles", str(profiles),
                    "--filament", "Bambu TPU 95A HF @BBL X1"])
    err = capsys.readouterr().err
    assert "no filament preset called 'Bambu TPU 95A HF @BBL X1'" in err and "Traceback" not in err


def test_bambus_preset_index_is_read_once_per_project(tmp_path, profiles, monkeypatch):
    """BBL.json is hundreds of KB in a real install and a project asks it for every preset in each chain."""
    index = profiles.parent / "BBL.json"
    index.write_text(json.dumps({"filament_list": [{"name": "Bambu TPU 95A HF @BBL X1C",
                                                    "sub_path": "filament/Bambu TPU 95A HF @BBL X1C.json"}]}))
    bambu._index.cache_clear()
    reads = []
    real = bambu.Path.read_text

    def counting(self, *a, **kw):
        if self == index:
            reads.append(self)
        return real(self, *a, **kw)

    monkeypatch.setattr(bambu.Path, "read_text", counting)
    bambu.tpu_project([_plain_3mf(tmp_path, "l.3mf")], tmp_path / "p.3mf", profiles, bed_type="High Temp Plate", **X1C)
    assert len(reads) == 1


def test_a_project_saved_again_in_bambu_studio_is_never_replaced(tmp_path, profiles):
    """Bambu Studio keeps the Designer when it saves a project, but writes that day's ModificationDate, which
    this leaves empty: a project saved again there (perhaps with supports or seams painted) is refused."""
    left = _plain_3mf(tmp_path, "left-insole.3mf")
    out = tmp_path / "pair.3mf"
    bambu.tpu_project([left], out, profiles, bed_type="High Temp Plate", **X1C)
    bambu.tpu_project([left], out, profiles, bed_type="High Temp Plate", **X1C)  # still as written: replaced
    resaved = tmp_path / "resaved.3mf"
    with zipfile.ZipFile(out) as z, zipfile.ZipFile(resaved, "w") as w:
        for n in z.namelist():
            data = z.read(n)
            if n == "3D/3dmodel.model":
                data = data.replace(b'<metadata name="ModificationDate"></metadata>',
                                    b'<metadata name="ModificationDate">2026-11-05</metadata>')
                assert b"2026-11-05" in data
            w.writestr(n, data)
    before = resaved.read_bytes()
    with pytest.raises(ValueError, match="isn't a project this wrote"):
        bambu.tpu_project([left], resaved, profiles, bed_type="High Temp Plate", **X1C)
    assert resaved.read_bytes() == before


def test_the_same_insole_twice_is_refused(tmp_path, profiles):
    left = _plain_3mf(tmp_path, "left-insole.3mf")
    with pytest.raises(ValueError, match="given twice"):
        bambu.tpu_project([left, left], tmp_path / "pair.3mf", profiles, bed_type="High Temp Plate", **X1C)


def test_an_l_shaped_no_print_area_from_a_profile_isnt_turned_into_a_box(profiles):
    """fdm_bbl_3dp_001_common's area is a corner plus a strip up the left edge; a box round it would refuse
    insoles that fit."""
    V = _insole_like(length=200.0, width=80.0).vertices
    l_shape = ["0x0", "28x0", "28x28", "8x28", "8x256", "0x256"]
    at = bambu.place_on_bed(V, ["0x0", "256x0", "256x256", "0x256"], l_shape)
    placed = bambu.placed_vertices(at["transform"], V)
    assert at["angle_deg"] == 0.0 and placed[:, 0].min() >= 8.0 + 3.0 - 1e-6
