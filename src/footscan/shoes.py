"""Saved shoes: one fixed insole outline per shoe model and size.

Custom insole makers work per shoe: the outline of the insole is the shoe's,
the same for everyone who wears that shoe in that size, and only the top
surface (the arch support, the heel cup's depth) comes from the person's
foot. An insole cut to the shoe goes in the way the stock one came out,
whatever shape the foot is, and a scan that reads a few percent small or
large can't shrink or grow it.

A saved shoe is that outline, read once from a scan of the shoe's own stock
insole lying flat (``recon/shoe.py``, ``outline_from_scan``) and kept as a
small JSON file, ``<id>.json``, in the shoes folder (``data/shoes`` by
default). The id comes from the name and size, e.g. "ASICS Gel Resolution X",
"US men's 9.5" -> ``asics-gel-resolution-x-us-men-s-9-5``. One saved shoe can be
the default: an insole made without naming a shoe or a length takes its
outline. The outline is kept as scanned (heel at the origin, toes along +x);
either foot can use it, as ``fit_to_foot`` mirrors a shoe's outline for the
other foot.

Nothing here is measured from a person: a shoe's insole is not personal data.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "shoes"  # the studio's: <its data folder>/shoes
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
DEFAULT_FILE = "default.txt"
NAME_MAX = 60   # characters: the id keeps up to 55 of the name's and all of the size's
SIZE_MAX = 24


class ShoeLibraryError(ValueError):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def shoe_id(name: str, size: str) -> str:
    """"ASICS Gel Resolution X", "US men's 9.5" -> "asics-gel-resolution-x-us-men-s-9-5". The size is always
    whole in it, so two sizes of one shoe are never the same saved shoe."""
    n, z = _slug(name)[:55].strip("-"), _slug(size)
    slug = f"{n}-{z}" if n and z else ""
    if not ID_RE.match(slug):
        raise ShoeLibraryError("a saved shoe needs a name and a size with some letters or numbers")
    return slug


def _path(folder: Path, sid: str) -> Path:
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise ShoeLibraryError(f"not a saved shoe's id: {sid!r}")
    return Path(folder) / f"{sid}.json"


def save(folder: Path, outline, name: str, size: str, source: str, read: dict, default: bool = False) -> dict:
    """Keep a shoe's insole outline (shapely Polygon, from ``recon.shoe.outline_from_scan``) as a saved shoe.
    ``source``: what it was read from (a capture id or a file name); ``read``: that function's info.
    Saving the same name and size again replaces it. -> the saved shoe."""
    from .recon import shoe as shoe_mod

    name, size = (str(name or "").strip(), str(size or "").strip())
    if not name or not size:
        raise ShoeLibraryError("a saved shoe needs a name (e.g. ASICS Gel Resolution X) and a size (e.g. US men's 9.5)")
    if len(name) > NAME_MAX or len(size) > SIZE_MAX:
        raise ShoeLibraryError(f"name: at most {NAME_MAX} characters; size: at most {SIZE_MAX}")
    hand, _ = shoe_mod.handedness(outline)
    x0, y0, x1, y1 = outline.bounds
    shoe = dict(id=shoe_id(name, size), name=name, size=size,
                outline=[list(p) for p in shoe_mod.as_param(outline)],
                length_mm=round(x1 - x0, 1), width_mm=round(y1 - y0, 1), shoe=hand,
                read_from=str(source)[:200], table_found=bool(read.get("table_found")),
                saved=datetime.now().isoformat(timespec="seconds"))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = _path(folder, shoe["id"])
    tmp = path.with_name(f"{path.name}.part-{secrets.token_hex(4)}")  # this save's own: two at once never share one
    try:
        tmp.write_text(json.dumps(shoe, indent=1))
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    if default:
        set_default(folder, shoe["id"])
    return shoe


def load(folder: Path, sid: str) -> dict:
    path = _path(folder, sid)
    if not path.is_file():
        raise ShoeLibraryError(f"no saved shoe {sid!r} (footscan shoe list shows them)")
    try:
        shoe = json.loads(path.read_text())
        ok = (isinstance(shoe, dict) and all(isinstance(shoe.get(k), str) for k in ("name", "size"))
              and all(isinstance(shoe.get(k), (int, float)) for k in ("length_mm", "width_mm"))
              and isinstance(shoe.get("outline"), list) and len(shoe["outline"]) >= 3
              and all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p)
                      for p in shoe["outline"]))
    except (OSError, ValueError):
        ok = False
    if not ok:
        raise ShoeLibraryError(f"saved shoe {sid!r} can't be read: save it again from its insole's scan")
    return shoe


def load_stamped(folder: Path, sid: str) -> tuple[dict, str | None]:
    """A saved shoe and the stamp of exactly the file it was read from (saved again meanwhile: read again)."""
    for _ in range(3):
        before = stamp(folder, sid)
        shoe = load(folder, sid)
        if stamp(folder, sid) == before:
            return shoe, before
    raise ShoeLibraryError(f"saved shoe {sid!r} keeps changing while it's read: try again")


def listed(folder: Path) -> list[dict]:
    """Every saved shoe, without its outline, by name and size."""
    out = []
    for path in sorted(Path(folder).glob("*.json")) if Path(folder).is_dir() else []:
        try:
            s = load(folder, path.stem)
        except ShoeLibraryError:  # unreadable: left out (``footscan shoe add`` again replaces it)
            continue
        out.append({k: v for k, v in s.items() if k != "outline"})
    return sorted(out, key=lambda s: (s["name"].lower(), s["size"].lower()))


def default_id(folder: Path) -> str | None:
    """The default saved shoe's id, or None (none chosen, or it's gone)."""
    f = Path(folder) / DEFAULT_FILE
    if not f.is_file():
        return None
    sid = f.read_text().strip()
    if not ID_RE.match(sid):
        return None
    try:
        load(folder, sid)
    except ShoeLibraryError:  # gone or unreadable: no default, rather than every insole refused
        return None
    return sid


def set_default(folder: Path, sid: str | None) -> None:
    """Make a saved shoe the default (None: no default; insoles then follow the foot's outline)."""
    f = Path(folder) / DEFAULT_FILE
    if sid is None:
        f.unlink(missing_ok=True)
        return
    load(folder, sid)  # it has to exist
    f.write_text(sid + "\n")


def stamp(folder: Path, sid: str) -> str | None:
    """Cheap fingerprint of a saved shoe's file: changes when it's saved again (an insole made from it is stale)."""
    path = _path(folder, sid)
    if not path.is_file():
        return None
    st = path.stat()
    return f"{path.name}:{st.st_size}:{st.st_mtime_ns}"


def outline_param(shoe: dict) -> tuple:
    """A saved shoe's outline as ``InsoleParams.shoe_outline`` takes it."""
    return tuple((float(x), float(y)) for x, y in shoe["outline"])


def label(shoe: dict) -> str:
    return f"{shoe['name']}, {shoe['size']}"
