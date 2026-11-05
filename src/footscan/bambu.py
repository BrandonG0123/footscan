"""A Bambu Studio project (.3mf) for printing an insole in TPU, settings included.

The plain 3MF that ``insole.write_3mf`` makes is geometry only: Bambu Studio
opens it with whatever printer, filament and process happen to be selected.
This module writes the same shape as a Bambu Studio *project*, so opening it
also selects the printer, the TPU filament profile, the build plate type and
the process changes an insole needs. Nothing about the shape changes: the
vertices and triangles are copied as they are, at scale 1, and only turned
and moved to lie on the bed.

How the settings travel
-----------------------
A Bambu project stores one flat settings file (``Metadata/project_settings.config``,
JSON) built from three of Bambu's own *system presets* (printer, process,
filament), plus a list of the keys the project changed from them
(``different_settings_to_system``). When Bambu Studio opens the project it
selects those system presets and keeps only the listed keys from the file;
every other value comes from the copy of the preset installed with the app.
So this module:

1. reads the three presets from the app's own profile folder (``--profiles``,
   e.g. ``BambuStudio.app/Contents/Resources/profiles/BBL``) and flattens each
   one (its ``inherits`` chain and ``include`` templates, parent first);
2. applies ``TPU_INSOLE_PROCESS`` on top of the process preset and lists those
   keys as changed. The filament and printer presets are left as Bambu ships
   them (Bambu's TPU 95A HF profile already sets the nozzle and bed
   temperatures, fan, retraction and flow limit for this filament).

Speeds in recent Bambu presets are lists, one value per nozzle kind
("Direct Drive Standard", "Direct Drive High Flow"...): a change is written
into every entry, so it holds whichever nozzle is fitted.

Where it lies on the bed
------------------------
Flat (the insole's bottom is already at z = 0), centred, straight if it fits,
otherwise turned to the angle that leaves the most room to the bed edges and
to the printer's no-print corner (``bed_exclude_area``, the front-left corner
an X1/P1 uses for its nozzle wipe and flow check). Nothing is scaled.
"""
from __future__ import annotations

import functools
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

# The Bambu Studio version the project says it was made with. Bambu Studio
# loads the settings of projects from its own or older versions, and offers to
# update for newer ones, so this should not be newer than the app that opens it.
DEFAULT_APP_VERSION = "02.04.00.70"

# The process changes for a TPU insole, each one a starting point (none has
# been checked against a printed insole yet; that is Phase 5).
TPU_INSOLE_PROCESS: dict[str, str] = {
    # Three walls: the edge the shoe's side presses on, and the heel cup's
    # rim, are walls only; a third one makes them less likely to tear or peel.
    "wall_loops": "3",
    # Gyroid infill: one wavy line per layer that never crosses itself, so the
    # nozzle doesn't drag across freshly laid soft TPU or start and stop much
    # (fewer retractions, less stringing), and it bends about the same in every
    # direction, unlike grid, which makes stiff ribs along two directions.
    "sparse_infill_pattern": "gyroid",
    # One density for the whole insole (a first fit has no zones). 20% is a
    # middle starting point; higher is firmer underfoot, lower softer.
    "sparse_infill_density": "20%",
    # Slow: TPU is soft filament, pushed too fast it buckles in the extruder.
    # Bambu's TPU 95A data sheet says under 80 mm/s. At 0.2 mm layers and
    # 0.45 mm lines, 40 mm/s pushes 0.45 x 0.2 x 40 = 3.6 mm^3/s of plastic,
    # the flow limit Bambu's own standard (not "HF") TPU 95A profile sets, so
    # these speeds suit either kind of spool. Walls and the top surface the
    # foot touches go slower again for a clean finish.
    "outer_wall_speed": "25",
    "inner_wall_speed": "35",
    "sparse_infill_speed": "40",
    "internal_solid_infill_speed": "35",
    "top_surface_speed": "25",
    "gap_infill_speed": "25",
    "initial_layer_speed": "15",
    "initial_layer_infill_speed": "20",
    "bridge_speed": "20",
}

# Bambu Studio's own range for filament_max_volumetric_speed (PrintConfig.cpp: min 0, max 200, "can't be zero")
MAX_FLOW_LIMIT = 200.0

BED_TYPES = ("Cool Plate", "Engineering Plate", "High Temp Plate", "Textured PEI Plate")

# keys that name or describe a preset rather than set a value
_PRESET_META = {"type", "name", "inherits", "from", "setting_id", "instantiation", "include", "description",
                "compatible_printers", "compatible_printers_condition", "compatible_prints",
                "compatible_prints_condition", "renamed_from", "filament_id", "version", "is_custom_defined"}


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------
def preset_path(profiles: Path, kind: str, name: str) -> Path:
    """Where Bambu keeps the ``kind`` preset called ``name``.

    Bambu's own index, ``BBL.json`` beside the ``BBL`` folder, lists every preset's file (``sub_path``):
    many live in sub-folders (``filament/P1P/Bambu TPU 95A @BBL P1P.json``), and a name with a "/" in it is
    kept under another file name ("Bambu Support For PA/PET" is "...PA PET..."). So the index is asked
    first; without one, ``<kind>/<name>.json``, then any file in that kind's folder whose "name" is it.
    """
    profiles = Path(profiles)
    index = profiles.parent / f"{profiles.name}.json"
    if index.is_file():
        sub_path = _index(str(index), index.stat().st_mtime_ns).get((kind, name))
        if sub_path and (profiles / sub_path).is_file():
            return profiles / sub_path
    path = profiles / kind / f"{name}.json"
    if path.is_file():
        return path
    found = _names_in(str(profiles / kind)).get(name)
    if found:
        return Path(found)
    raise FileNotFoundError(f"no {kind} preset called {name!r} in {profiles / kind}")


@functools.lru_cache(maxsize=4)
def _index(index: str, mtime_ns: int) -> dict:
    """BBL.json read once (it's large, and one project asks it for a dozen presets): (kind, name) -> sub_path.
    ``mtime_ns`` is only there so an index Bambu Studio updated is read again."""
    out = {}
    for key, listed in json.loads(Path(index).read_text(encoding="utf-8")).items():
        if key.endswith("_list") and isinstance(listed, list):
            for entry in listed:
                if isinstance(entry, dict) and entry.get("name") and entry.get("sub_path"):
                    out.setdefault((key[: -len("_list")], entry["name"]), entry["sub_path"])
    return out


@functools.lru_cache(maxsize=8)
def _names_in(folder: str) -> dict:
    """Every preset file under ``folder`` by its "name" (with no index: each file read once, not per preset)."""
    out = {}
    for path in sorted(Path(folder).rglob("*.json")) if Path(folder).is_dir() else []:
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name")
        except (OSError, ValueError):
            continue
        if isinstance(name, str):
            out.setdefault(name, str(path))
    return out


def flatten_preset(profiles: Path, kind: str, name: str) -> dict:
    """One Bambu system preset with everything it inherits filled in.

    ``kind`` is the profile sub-folder (``machine``, ``process``, ``filament``).
    Bambu's loader applies the parent (``inherits``) first, then any
    ``include`` templates, then the preset's own keys; this does the same.
    """
    own = json.loads(preset_path(profiles, kind, name).read_text(encoding="utf-8"))
    out = flatten_preset(profiles, kind, own["inherits"]) if own.get("inherits") else {}
    for template in own.get("include", []):
        out.update(flatten_preset(profiles, kind, template))
    out.update(own)
    return out


def _set_everywhere(base, value: str):
    """A changed value, shaped like the preset's: a list keeps its length (one per nozzle kind)."""
    if isinstance(base, list):
        return [value] * max(len(base), 1)
    return value


def project_config(profiles: Path, printer: str, process: str, filament: str, *, bed_type: str,
                   changes: dict[str, str] | None = None, filament_changes: dict[str, str] | None = None,
                   colour: str = "#FFFFFF", app_version: str = DEFAULT_APP_VERSION) -> dict:
    """The project settings: printer + process + filament presets, the changes on top.

    ``changes`` are process settings (default ``TPU_INSOLE_PROCESS``); ``filament_changes``
    are filament settings, e.g. a lower ``filament_max_volumetric_speed`` for a
    slower spool. Each is listed as changed in its own preset's slot.
    """
    if bed_type not in BED_TYPES:
        raise ValueError(f"bed_type must be one of {BED_TYPES}, not {bed_type!r}")
    changes = TPU_INSOLE_PROCESS if changes is None else changes
    m = flatten_preset(profiles, "machine", printer)
    p = flatten_preset(profiles, "process", process)
    f = flatten_preset(profiles, "filament", filament)
    for preset, kind, wanted in ((m, "machine", printer), (p, "process", process), (f, "filament", filament)):
        compatible = preset.get("compatible_printers")
        if kind != "machine" and compatible and printer not in compatible:
            raise ValueError(f"{kind} preset {wanted!r} is not made for {printer!r} (it lists {compatible})")
    filament_changes = filament_changes or {}
    unknown = sorted(set(changes) - set(p))
    if unknown:
        raise KeyError(f"not process settings in {process!r}: {unknown}")
    unknown = sorted(set(filament_changes) - set(f))
    if unknown:
        raise KeyError(f"not filament settings in {filament!r}: {unknown}")

    cfg: dict = {}
    for preset in (m, p, f):
        cfg.update({k: v for k, v in preset.items() if k not in _PRESET_META})
    for key, value in changes.items():
        cfg[key] = _set_everywhere(p[key], value)
    for key, value in filament_changes.items():
        cfg[key] = _set_everywhere(f[key], value)

    variants = f.get("filament_extruder_variant") or []
    cfg.update({
        "name": "project_settings", "from": "project", "version": app_version,
        "printer_technology": "FFF",
        "printer_settings_id": printer, "print_settings_id": process,
        "filament_settings_id": [filament], "filament_ids": [f.get("filament_id", "")],
        "filament_colour": [colour],
        "curr_bed_type": bed_type,
        "default_print_profile": m.get("default_print_profile", process),
        # one slot per filament, then the printer: [process, filament 1, printer]
        "different_settings_to_system": [";".join(sorted(changes)), ";".join(sorted(filament_changes)), ""],
    })
    if variants:
        # one filament, with one set of values per nozzle kind the printer offers
        cfg["filament_self_index"] = ["1"] * len(variants)
    return cfg


# ---------------------------------------------------------------------------
# placing it on the bed
# ---------------------------------------------------------------------------
def _poly(points) -> np.ndarray:
    return np.array([[float(c) for c in str(pt).split("x")] for pt in points], dtype=float)


def place_on_bed(vertices, printable_area, bed_exclude_area=(), clearance: float = 3.0) -> dict:
    """Turn about z and move so the footprint lies centred on the bed, clear of the no-print corner.

    The same search the plain 3MF uses (``insole.place_on_bed``), on the printer profile's own bed
    (``printable_area``) and no-print corner (``bed_exclude_area``). Refuses rather than scales when nothing
    leaves ``clearance``. Returns the 3MF build transform (3 x 4, row vectors), the angle and the room left.
    """
    from .insole import place_on_bed as search

    V = np.asarray(vertices, float)
    bed = _poly(printable_area)
    exclude = _poly(bed_exclude_area) if len(bed_exclude_area) else None
    at = search(V[:, :2], bed.min(0), bed.max(0),
                (exclude.min(0), exclude.max(0)) if exclude is not None else None, clearance)
    if at["room_mm"] < clearance:
        raise ValueError(f"doesn't fit this bed: best turn {at['angle_deg']:g} degrees leaves {at['room_mm']:.1f} mm "
                         f"(needs {clearance:g} mm)")
    c, s = at["cos"], at["sin"]
    tz = -float(V[:, 2].min())
    transform = [c, s, 0.0, -s, c, 0.0, 0.0, 0.0, 1.0, at["shift"][0], at["shift"][1], tz]
    return dict(transform=transform, angle_deg=at["angle_deg"], room_mm=round(at["room_mm"], 1))


# ---------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------
from .insole import THREEMF_CORE as _CORE  # noqa: E402 - the one 3MF core namespace
_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_BBS = "http://schemas.bambulab.com/package/2021"
_REL_MODEL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"


def _fmt(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") if x != 0 else "0"


MAX_PARTS = 2  # a left and a right: plates side by side in one row


def plate_offset(printable_area, plate: int) -> tuple[float, float]:
    """Where plate ``plate`` (0 = first) sits in Bambu Studio's project space.

    Bambu lays plates out a bed width plus a fifth apart (``PartPlateList::compute_shape_position``,
    ``LOGICAL_PART_PLATE_GAP = 1/5``). For one or two plates that's one row, so plate 2 is one step to the
    right; objects are put on a plate by where they lie, so an object for plate 2 is moved by this much.
    (Three or more would start a grid of rows, which this doesn't write: ``MAX_PARTS``.)
    """
    w = float(np.ptp(_poly(printable_area)[:, 0]))
    return plate * w * 1.2, 0.0


def write_project(parts: list[dict], path: Path, config: dict, *, title: str, description: str) -> Path:
    """Write the Bambu Studio project: each part's mesh unchanged, on its own plate, with ``config``.

    A part is ``dict(vertices, faces, name, placement)``; part k goes on plate k + 1.
    """
    if not 1 <= len(parts) <= MAX_PARTS:
        raise ValueError(f"one to {MAX_PARTS} insoles (plates in one row), not {len(parts)}")
    app = f"BambuStudio-{config['version']}"
    ident = " ".join(["1", "0", "0", "0", "0", "1", "0", "0", "0", "0", "1", "0", "0", "0", "0", "1"])
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{_CORE}" '
            f'xmlns:BambuStudio="{_BBS}" xmlns:p="{_PROD}" requiredextensions="p">\n')
    files: dict[str, str] = {}
    objects, items, rels, settings_objects, plates = [], [], [], [], []
    for k, part in enumerate(parts):
        V = np.asarray(part["vertices"], float)
        F = np.asarray(part["faces"], int)
        mesh_id, obj_id = 2 * k + 1, 2 * k + 2
        dx, dy = plate_offset(config["printable_area"], k)
        T = list(part["placement"]["transform"])
        T[9] += dx
        T[10] += dy
        t = " ".join(_fmt(x) for x in T)
        verts = "\n".join(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in V)
        tris = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{d}"/>' for a, b, d in F)
        mesh_file = f"3D/Objects/object_{mesh_id}.model"
        files[mesh_file] = (
            head + ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
            f'  <object id="{mesh_id}" p:UUID="000{k + 1}0000-81cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <mesh>\n'
            f"    <vertices>\n{verts}\n    </vertices>\n    <triangles>\n{tris}\n    </triangles>\n"
            "   </mesh>\n  </object>\n </resources>\n <build/>\n</model>\n")
        objects.append(
            f'  <object id="{obj_id}" p:UUID="0000000{k + 1}-61cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <components>\n'
            f'    <component p:path="/{mesh_file}" objectid="{mesh_id}" '
            f'p:UUID="000{k + 1}0000-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
            "   </components>\n  </object>\n")
        items.append(f'  <item objectid="{obj_id}" p:UUID="0000000{k + 1}-b1ec-4553-aec9-835e5b724bb4" '
                     f'transform="{t}" printable="1"/>\n')
        rels.append(f' <Relationship Target="/{mesh_file}" Id="rel-{k + 1}" Type="{_REL_MODEL}"/>\n')
        name = quoteattr(part["name"])
        settings_objects.append(
            f'  <object id="{obj_id}">\n'
            f'    <metadata key="name" value={name}/>\n    <metadata key="extruder" value="1"/>\n'
            f'    <metadata face_count="{len(F)}"/>\n    <part id="{mesh_id}" subtype="normal_part">\n'
            f'      <metadata key="name" value={name}/>\n      <metadata key="matrix" value="{ident}"/>\n'
            f'      <mesh_stat face_count="{len(F)}" edges_fixed="0" degenerate_facets="0" facets_removed="0" '
            'facets_reversed="0" backwards_edges="0"/>\n    </part>\n  </object>\n')
        plates.append(
            f'  <plate>\n    <metadata key="plater_id" value="{k + 1}"/>\n'
            f'    <metadata key="plater_name" value={name}/>\n'
            '    <metadata key="locked" value="false"/>\n    <model_instance>\n'
            f'      <metadata key="object_id" value="{obj_id}"/>\n      <metadata key="instance_id" value="0"/>\n'
            f'      <metadata key="identify_id" value="{100 * (k + 1)}"/>\n    </model_instance>\n  </plate>\n')

    meta = {"Application": app, "BambuStudio:3mfVersion": "1", "Title": title, "Description": description,
            "Designer": "footscan", "CreationDate": "", "ModificationDate": ""}
    meta_xml = "".join(f' <metadata name={quoteattr(k)}>{escape(v)}</metadata>\n' for k, v in meta.items())
    main_model = (head + meta_xml + " <resources>\n" + "".join(objects) + " </resources>\n"
                  ' <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">\n' + "".join(items) + " </build>\n</model>\n")
    model_settings = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "".join(settings_objects)
                      + "".join(plates) + "</config>\n")
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        ' <Default Extension="png" ContentType="image/png"/>\n'
        ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
    root_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                 f' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="{_REL_MODEL}"/>\n</Relationships>\n')
    model_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                  + "".join(rels) + "</Relationships>\n")
    slice_info = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n'
                  '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
                  f'    <header_item key="X-BBL-Client-Version" value="{config["version"]}"/>\n'
                  "  </header>\n</config>\n")

    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("3D/3dmodel.model", main_model)
        z.writestr("3D/_rels/3dmodel.model.rels", model_rels)
        for name, text in files.items():
            z.writestr(name, text)
        z.writestr("Metadata/project_settings.config", json.dumps(config, indent=4, ensure_ascii=False))
        z.writestr("Metadata/model_settings.config", model_settings)
        z.writestr("Metadata/slice_info.config", slice_info)
    tmp.replace(path)
    return path


def read_project(path: Path) -> dict:
    """Read back what ``write_project`` wrote (each part's mesh in its own coordinates, its build
    transform, plate offset included, and the settings). For checking."""
    import xml.etree.ElementTree as ET

    ns = {"m": _CORE}
    parts = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        main = ET.fromstring(z.read("3D/3dmodel.model"))
        config = json.loads(z.read("Metadata/project_settings.config"))
        settings = z.read("Metadata/model_settings.config").decode()
        comps = {o.get("id"): o.find(".//m:component", ns) for o in main.iterfind(".//m:resources/m:object", ns)}
        for item in main.iterfind(".//m:build/m:item", ns):
            comp = comps[item.get("objectid")]
            mesh = ET.fromstring(z.read(comp.get(f"{{{_PROD}}}path").lstrip("/")))
            V = np.array([[float(v.get(k)) for k in "xyz"] for v in mesh.iterfind(".//m:vertex", ns)])
            F = np.array([[int(t.get(k)) for k in ("v1", "v2", "v3")] for t in mesh.iterfind(".//m:triangle", ns)])
            parts.append(dict(vertices=V, faces=F, transform=[float(x) for x in item.get("transform").split()]))
    return dict(names=names, parts=parts, config=config, model_settings=settings,
                metadata={m.get("name"): m.text for m in main.iterfind("m:metadata", ns)}, **parts[0])


def placed_vertices(transform, vertices) -> np.ndarray:
    """Vertices where the build transform puts them (3MF row-vector convention)."""
    M = np.asarray(transform, float).reshape(4, 3)
    return np.asarray(vertices, float) @ M[:3] + M[3]


# Every project carries this, whatever it was made from: an STL has no notes of its own to pass on.
SAFETY_NOTE = ("NOT A MEDICAL DEVICE. No posting. Walking-only break-in; no sport until a clinician has signed "
               "the summary sheet.")


def _load_insole(mesh_path: Path):
    """An insole file -> (vertices, faces, name, notes). A 3MF must be the plain one ``footscan insole``
    writes: one object with its own mesh, placed by a turn about z (no mirror, no scale). Any other 3MF
    (a Bambu project, several objects) is refused, since reading only its vertices would be wrong."""
    import xml.etree.ElementTree as ET

    mesh_path = Path(mesh_path)
    if mesh_path.suffix.lower() == ".3mf":
        from .insole import read_3mf

        def refuse(why):
            return ValueError(f"{mesh_path.name}: {why}; give the insole .3mf or .stl that footscan insole wrote")

        try:
            with zipfile.ZipFile(mesh_path) as z:
                root = ET.fromstring(z.read("3D/3dmodel.model"))
        except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
            raise refuse("not a 3MF file this can read") from None
        ns = {"m": _CORE}
        objects = list(root.iterfind(".//m:resources/m:object", ns))
        items = list(root.iterfind(".//m:build/m:item", ns))
        if len(objects) != 1 or objects[0].find("m:mesh", ns) is None or len(items) != 1:
            raise refuse("it isn't one insole (a Bambu project, or several objects)")
        r = read_3mf(mesh_path)
        M = np.asarray(r["transform"], float).reshape(4, 3)[:3]
        if not (np.allclose(M @ M.T, np.eye(3), atol=1e-4) and np.linalg.det(M) > 0 and abs(M[2, 2] - 1) < 1e-4):
            raise refuse("its placement mirrors, scales or tilts it")
        return r["vertices"], r["faces"], r["metadata"].get("Title") or mesh_path.stem, r["metadata"].get("Description") or ""
    import trimesh

    m = trimesh.load(mesh_path, force="mesh")
    return np.asarray(m.vertices), np.asarray(m.faces), mesh_path.stem, ""


def check_output(out: Path, inputs) -> None:
    """Refuse an output that would destroy something: one of the inputs, a file that isn't a .3mf, or a .3mf
    that isn't a project this wrote (an insole 3MF, or any other Bambu Studio project). Replacing an earlier
    insole project is fine; once saved again in Bambu Studio it may no longer say it's footscan's (refused)."""
    out = Path(out)
    if out.suffix.lower() != ".3mf":
        raise ValueError(f"the project to write must be a .3mf file, not {out.name!r}")
    if any(Path(i).resolve() == out.resolve() for i in inputs):
        raise ValueError(f"{out.name} is one of the insole files: name a new file for the project")
    if out.exists():
        import xml.etree.ElementTree as ET

        try:
            with zipfile.ZipFile(out) as z:
                root = ET.fromstring(z.read("3D/3dmodel.model"))
                ours = "Metadata/project_settings.config" in z.namelist() and any(
                    m.get("name") == "Designer" and (m.text or "") == "footscan"
                    for m in root.iterfind(f"{{{_CORE}}}metadata"))
        except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
            ours = False
        if not ours:  # an insole file, or a project of something else saved in Bambu Studio
            raise ValueError(f"{out.name} already exists and isn't a project this wrote: name a new file for the "
                             f"project")


def tpu_project(mesh_paths, out: Path, profiles: Path, *, printer: str, process: str, filament: str,
                bed_type: str, filament_changes: dict[str, str] | None = None,
                app_version: str = DEFAULT_APP_VERSION) -> dict:
    """Insole files (the plain 3MF or STL the insole command wrote) -> one Bambu Studio TPU project.

    One insole per plate, in the order given (left then right makes plate 1 the left).
    """
    if isinstance(mesh_paths, (str, Path)):
        mesh_paths = [mesh_paths]
    if not 1 <= len(mesh_paths) <= MAX_PARTS:  # before any file is read
        raise ValueError(f"one to {MAX_PARTS} insole files (one per plate: a left and a right), not {len(mesh_paths)}")
    check_output(out, mesh_paths)
    cfg = project_config(profiles, printer, process, filament, bed_type=bed_type,
                         filament_changes=filament_changes, app_version=app_version)
    parts, report, descriptions = [], [], []
    for mp in mesh_paths:
        V, F, name, description = _load_insole(mp)
        placement = place_on_bed(V, cfg["printable_area"], cfg.get("bed_exclude_area") or [])
        parts.append(dict(vertices=V, faces=F, name=name, placement=placement))
        size = V.max(0) - V.min(0)
        report.append(dict(name=name, plate=len(parts), length_mm=round(float(size.max()), 1),
                           size_mm=[round(float(x), 1) for x in size], angle_deg=placement["angle_deg"],
                           room_mm=placement["room_mm"]))
        if description and description not in descriptions:
            descriptions.append(description)
    title = parts[0]["name"] if len(parts) == 1 else " + ".join(p["name"] for p in parts)
    if not any("NOT A MEDICAL DEVICE" in d for d in descriptions):  # e.g. from an STL, which has no notes
        descriptions.insert(0, SAFETY_NOTE)
    write_project(parts, out, cfg, title=title, description=" ".join(descriptions))
    return dict(path=str(out), plates=report, printer=printer, process=process, filament=filament,
                bed_type=bed_type, changed=sorted(TPU_INSOLE_PROCESS), filament_changed=filament_changes or {},
                **{k: report[0][k] for k in ("length_mm", "size_mm", "angle_deg", "room_mm")})


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m footscan.bambu",
                                 description="insole 3MF/STL -> Bambu Studio project with TPU settings")
    ap.add_argument("files", type=Path, nargs="+",
                    help=f"the insole .3mf (from `footscan insole`) or .stl files, one per plate (at most "
                         f"{MAX_PARTS}: a left and a right)")
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="the Bambu Studio project to write (.3mf; a new file, or an earlier project)")
    ap.add_argument("--profiles", type=Path, required=True,
                    help="Bambu Studio's BBL profile folder, e.g. BambuStudio.app/Contents/Resources/profiles/BBL")
    ap.add_argument("--printer", default="Bambu Lab X1 Carbon 0.4 nozzle")
    ap.add_argument("--process", default="0.20mm Standard @BBL X1C")
    ap.add_argument("--filament", default="Bambu TPU 95A HF @BBL X1C")
    ap.add_argument("--bed-type", default="Textured PEI Plate", choices=BED_TYPES)
    ap.add_argument("--max-flow", type=float, default=None,
                    help=f"filament max volumetric speed (mm^3/s), lower for a slower spool "
                         f"(more than 0, at most {MAX_FLOW_LIMIT:g})")
    ap.add_argument("--app-version", default=DEFAULT_APP_VERSION,
                    help="Bambu Studio version to write (not newer than the app that will open it)")
    a = ap.parse_args(argv)
    if a.max_flow is not None and not 0 < a.max_flow <= MAX_FLOW_LIMIT:
        ap.error(f"--max-flow must be more than 0 and at most {MAX_FLOW_LIMIT:g} mm^3/s, not {a.max_flow:g}")
    fil = {"filament_max_volumetric_speed": f"{a.max_flow:g}"} if a.max_flow is not None else None
    try:  # tpu_project's refusals (file count, output, presets, the bed) are one-line errors, not tracebacks
        info = tpu_project(a.files, a.output, a.profiles, printer=a.printer, process=a.process, filament=a.filament,
                           bed_type=a.bed_type, filament_changes=fil, app_version=a.app_version)
    except (ValueError, FileNotFoundError) as e:
        ap.error(str(e))
    except KeyError as e:
        ap.error(f"not in this preset: {e}")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
