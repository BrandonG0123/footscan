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

BED_TYPES = ("Cool Plate", "Engineering Plate", "High Temp Plate", "Textured PEI Plate")

# keys that name or describe a preset rather than set a value
_PRESET_META = {"type", "name", "inherits", "from", "setting_id", "instantiation", "include", "description",
                "compatible_printers", "compatible_printers_condition", "compatible_prints",
                "compatible_prints_condition", "renamed_from", "filament_id", "version", "is_custom_defined"}


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------
def flatten_preset(profiles: Path, kind: str, name: str) -> dict:
    """One Bambu system preset with everything it inherits filled in.

    ``kind`` is the profile sub-folder (``machine``, ``process``, ``filament``).
    Bambu's loader applies the parent (``inherits``) first, then any
    ``include`` templates, then the preset's own keys; this does the same.
    """
    path = Path(profiles) / kind / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"no {kind} preset called {name!r} in {Path(profiles) / kind}")
    own = json.loads(path.read_text(encoding="utf-8"))
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
                   changes: dict[str, str] | None = None, colour: str = "#FFFFFF",
                   app_version: str = DEFAULT_APP_VERSION) -> dict:
    """The project settings: printer + process + filament presets, the process changes on top."""
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
    unknown = sorted(set(changes) - set(p))
    if unknown:
        raise KeyError(f"not process settings in {process!r}: {unknown}")

    cfg: dict = {}
    for preset in (m, p, f):
        cfg.update({k: v for k, v in preset.items() if k not in _PRESET_META})
    for key, value in changes.items():
        cfg[key] = _set_everywhere(p[key], value)

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
        "different_settings_to_system": [";".join(sorted(changes)), "", ""],
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


def _outline(xy: np.ndarray, step: float = 0.5) -> np.ndarray:
    """The footprint's convex outline, with points every ``step`` mm along it."""
    from scipy.spatial import ConvexHull

    hull = xy[ConvexHull(xy).vertices]
    pts = []
    for a, b in zip(hull, np.roll(hull, -1, axis=0)):
        n = max(int(np.ceil(np.linalg.norm(b - a) / step)), 1)
        pts.append(a + (b - a) * np.linspace(0, 1, n, endpoint=False)[:, None])
    return np.vstack(pts)


def _room(outline: np.ndarray, bed: np.ndarray, exclude: np.ndarray | None) -> float:
    """Smallest gap (mm) from the placed outline to the bed edge or the no-print corner; < 0 = overlaps."""
    lo, hi = bed.min(0), bed.max(0)
    gap = float(min((outline - lo).min(), (hi - outline).min()))
    if exclude is not None and len(exclude):
        elo, ehi = exclude.min(0), exclude.max(0)
        outside = np.maximum(np.maximum(elo - outline, outline - ehi), 0.0)
        dist = np.linalg.norm(outside, axis=1)
        inside = np.all((outline > elo) & (outline < ehi), axis=1)
        gap = min(gap, float(-1.0 if inside.any() else dist.min()))
    return gap


def place_on_bed(vertices, printable_area, bed_exclude_area=(), clearance: float = 3.0) -> dict:
    """Turn about z and move so the footprint lies centred on the bed, clear of the no-print corner.

    Straight (0 degrees) when that leaves ``clearance`` all round; otherwise
    the half-degree turn leaving the most room. Returns the 3MF build
    transform (3 x 4, row vectors), the angle and the room left.
    """
    V = np.asarray(vertices, float)
    bed = _poly(printable_area)
    exclude = _poly(bed_exclude_area) if len(bed_exclude_area) else None
    outline0 = _outline(V[:, :2])
    centre = (bed.min(0) + bed.max(0)) / 2

    def placed(deg):
        a = np.radians(deg)
        c, s = np.cos(a), np.sin(a)
        turned = outline0 @ np.array([[c, s], [-s, c]])
        shift = centre - (turned.min(0) + turned.max(0)) / 2
        return turned + shift, shift, (c, s)

    best = None
    for deg in np.arange(0.0, 360.0, 0.5):
        outline, shift, cs = placed(deg)
        room = _room(outline, bed, exclude)
        if deg == 0.0 and room >= clearance:
            best = (deg, room, shift, cs)
            break
        if best is None or room > best[1]:
            best = (float(deg), room, shift, cs)
    deg, room, shift, (c, s) = best
    if room < clearance:
        raise ValueError(f"doesn't fit this bed: best turn {deg:g} degrees leaves {room:.1f} mm "
                         f"(needs {clearance:g} mm)")
    tz = -float(V[:, 2].min())
    transform = [c, s, 0.0, -s, c, 0.0, 0.0, 0.0, 1.0, float(shift[0]), float(shift[1]), tz]
    return dict(transform=transform, angle_deg=float(deg), room_mm=round(float(room), 1))


# ---------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------
_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_BBS = "http://schemas.bambulab.com/package/2021"
_REL_MODEL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"


def _fmt(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") if x != 0 else "0"


def write_project(vertices, faces, path: Path, config: dict, *, title: str, description: str,
                  placement: dict) -> Path:
    """Write the Bambu Studio project: the mesh unchanged, placed by ``placement``, with ``config``."""
    V = np.asarray(vertices, float)
    F = np.asarray(faces, int)
    app = f"BambuStudio-{config['version']}"
    t = " ".join(_fmt(x) for x in placement["transform"])
    ident = " ".join(["1", "0", "0", "0", "0", "1", "0", "0", "0", "0", "1", "0", "0", "0", "0", "1"])

    verts = "\n".join(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in V)
    tris = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{d}"/>' for a, b, d in F)
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{_CORE}" '
            f'xmlns:BambuStudio="{_BBS}" xmlns:p="{_PROD}" requiredextensions="p">\n')
    mesh_model = (head + ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
                  '  <object id="1" p:UUID="00010000-81cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <mesh>\n'
                  f"    <vertices>\n{verts}\n    </vertices>\n    <triangles>\n{tris}\n    </triangles>\n"
                  "   </mesh>\n  </object>\n </resources>\n <build/>\n</model>\n")
    meta = {"Application": app, "BambuStudio:3mfVersion": "1", "Title": title, "Description": description,
            "Designer": "footscan", "CreationDate": "", "ModificationDate": ""}
    meta_xml = "".join(f' <metadata name={quoteattr(k)}>{escape(v)}</metadata>\n' for k, v in meta.items())
    main_model = (head + meta_xml + " <resources>\n"
                  '  <object id="2" p:UUID="00000001-61cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <components>\n'
                  '    <component p:path="/3D/Objects/object_1.model" objectid="1" '
                  'p:UUID="00010000-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
                  "   </components>\n  </object>\n </resources>\n"
                  ' <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">\n'
                  f'  <item objectid="2" p:UUID="00000002-b1ec-4553-aec9-835e5b724bb4" transform="{t}" printable="1"/>\n'
                  " </build>\n</model>\n")
    name = quoteattr(title)
    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <object id="2">\n'
        f'    <metadata key="name" value={name}/>\n    <metadata key="extruder" value="1"/>\n'
        f'    <metadata face_count="{len(F)}"/>\n    <part id="1" subtype="normal_part">\n'
        f'      <metadata key="name" value={name}/>\n      <metadata key="matrix" value="{ident}"/>\n'
        f'      <mesh_stat face_count="{len(F)}" edges_fixed="0" degenerate_facets="0" facets_removed="0" '
        'facets_reversed="0" backwards_edges="0"/>\n    </part>\n  </object>\n  <plate>\n'
        '    <metadata key="plater_id" value="1"/>\n    <metadata key="plater_name" value=""/>\n'
        '    <metadata key="locked" value="false"/>\n    <model_instance>\n'
        '      <metadata key="object_id" value="2"/>\n      <metadata key="instance_id" value="0"/>\n'
        '      <metadata key="identify_id" value="100"/>\n    </model_instance>\n  </plate>\n</config>\n')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        ' <Default Extension="png" ContentType="image/png"/>\n'
        ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="{_REL_MODEL}"/>\n</Relationships>\n')
    model_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                  f' <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="{_REL_MODEL}"/>\n'
                  "</Relationships>\n")
    slice_info = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n'
                  '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
                  f'    <header_item key="X-BBL-Client-Version" value="{config["version"]}"/>\n'
                  "  </header>\n</config>\n")

    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", main_model)
        z.writestr("3D/_rels/3dmodel.model.rels", model_rels)
        z.writestr("3D/Objects/object_1.model", mesh_model)
        z.writestr("Metadata/project_settings.config", json.dumps(config, indent=4, ensure_ascii=False))
        z.writestr("Metadata/model_settings.config", model_settings)
        z.writestr("Metadata/slice_info.config", slice_info)
    tmp.replace(path)
    return path


def read_project(path: Path) -> dict:
    """Read back what ``write_project`` wrote (mesh in its own coordinates, transform, settings). For checking."""
    import xml.etree.ElementTree as ET

    ns = {"m": _CORE}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        mesh = ET.fromstring(z.read("3D/Objects/object_1.model"))
        main = ET.fromstring(z.read("3D/3dmodel.model"))
        config = json.loads(z.read("Metadata/project_settings.config"))
    V = np.array([[float(v.get(k)) for k in "xyz"] for v in mesh.iterfind(".//m:vertex", ns)])
    F = np.array([[int(t.get(k)) for k in ("v1", "v2", "v3")] for t in mesh.iterfind(".//m:triangle", ns)])
    item = main.find(".//m:build/m:item", ns)
    return dict(names=names, vertices=V, faces=F, transform=[float(x) for x in item.get("transform").split()],
                config=config, metadata={m.get("name"): m.text for m in main.iterfind("m:metadata", ns)})


def placed_vertices(transform, vertices) -> np.ndarray:
    """Vertices where the build transform puts them (3MF row-vector convention)."""
    M = np.asarray(transform, float).reshape(4, 3)
    return np.asarray(vertices, float) @ M[:3] + M[3]


def tpu_project(mesh_path: Path, out: Path, profiles: Path, *, printer: str, process: str, filament: str,
                bed_type: str, app_version: str = DEFAULT_APP_VERSION) -> dict:
    """An insole file (the plain 3MF or the STL the insole command wrote) -> Bambu Studio TPU project."""
    mesh_path = Path(mesh_path)
    if mesh_path.suffix.lower() == ".3mf":
        from .insole import read_3mf

        r = read_3mf(mesh_path)
        V, F = r["vertices"], r["faces"]
        title = r["metadata"].get("Title") or mesh_path.stem
        description = r["metadata"].get("Description") or ""
    else:
        import trimesh

        m = trimesh.load(mesh_path, force="mesh")
        V, F = np.asarray(m.vertices), np.asarray(m.faces)
        title, description = mesh_path.stem, ""
    cfg = project_config(profiles, printer, process, filament, bed_type=bed_type, app_version=app_version)
    placement = place_on_bed(V, cfg["printable_area"], cfg.get("bed_exclude_area") or [])
    write_project(V, F, out, cfg, title=title, description=description, placement=placement)
    size = V.max(0) - V.min(0)
    return dict(path=str(out), length_mm=round(float(size.max()), 1), size_mm=[round(float(s), 1) for s in size],
                angle_deg=placement["angle_deg"], room_mm=placement["room_mm"], printer=printer, process=process,
                filament=filament, bed_type=bed_type, changed=sorted(TPU_INSOLE_PROCESS))


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m footscan.bambu",
                                 description="insole 3MF/STL -> Bambu Studio project with TPU settings")
    ap.add_argument("mesh", type=Path, help="the insole's .3mf (from `footscan insole`) or .stl")
    ap.add_argument("out", type=Path, help="the project file to write (.3mf)")
    ap.add_argument("--profiles", type=Path, required=True,
                    help="Bambu Studio's BBL profile folder, e.g. BambuStudio.app/Contents/Resources/profiles/BBL")
    ap.add_argument("--printer", default="Bambu Lab X1 Carbon 0.4 nozzle")
    ap.add_argument("--process", default="0.20mm Standard @BBL X1C")
    ap.add_argument("--filament", default="Bambu TPU 95A HF @BBL X1C")
    ap.add_argument("--bed-type", default="Textured PEI Plate", choices=BED_TYPES)
    ap.add_argument("--app-version", default=DEFAULT_APP_VERSION,
                    help="Bambu Studio version to write (not newer than the app that will open it)")
    a = ap.parse_args(argv)
    info = tpu_project(a.mesh, a.out, a.profiles, printer=a.printer, process=a.process, filament=a.filament,
                       bed_type=a.bed_type, app_version=a.app_version)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
