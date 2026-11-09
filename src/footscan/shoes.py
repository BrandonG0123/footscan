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
import unicodedata
from datetime import datetime
from pathlib import Path

from .filestamp import file_stamp

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "shoes"  # the studio's: <its data folder>/shoes
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,89}$")
DEFAULT_FILE = "default.txt"
NAME_MAX = 60   # characters. The id keeps all of the name's and the size's letters and numbers (at most 60 + 1 +
SIZE_MAX = 24   # 24 = 85 characters). Two shoes can still share an id (save() refuses the second; see same_shoe)


class ShoeLibraryError(ValueError):
    pass


def slug(text: str) -> str:
    """Lower case letters and numbers, runs of anything else as one "-": how ids and names are compared.
    Accents are dropped first ("é" -> "e", "ö" -> "o"); other letters outside a-z are dropped ("Größe" -> "groe")."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def same_shoe(a: dict, b: dict) -> bool:
    """Are two saved shoes' names and sizes the same, apart from case, spacing and punctuation? Two that share an
    id but aren't ("Nike Pegasus 40", "US 9" and "Nike Pegasus", "40 US 9"; "Große" and "Größe") are different
    shoes, and save() won't let one replace the other."""
    def key(s: dict):
        return tuple(re.sub(r"[\W_]+", " ", str(s.get(k, "")).casefold()).strip() for k in ("name", "size"))
    return key(a) == key(b)


def shoe_id(name: str, size: str) -> str:
    """"ASICS Gel Resolution X", "US men's 9.5" -> "asics-gel-resolution-x-us-men-s-9-5". The name and the size
    are both whole in it (nothing is cut off). Two different shoes can still get one id, when the split between
    name and size moves or only accented or non-Latin letters differ: save() refuses the second (same_shoe)."""
    n, z = slug(name), slug(size)
    sid = f"{n}-{z}" if n and z else ""
    if not ID_RE.match(sid):
        raise ShoeLibraryError("a saved shoe needs a name and a size with some letters or numbers")
    return sid


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
    if path.is_file():  # saving the same shoe again replaces it; a different shoe with the same id doesn't
        try:
            old = load(folder, shoe["id"])
        except ShoeLibraryError:
            old = None  # unreadable: replaced (the way to repair it)
        if old is not None and not same_shoe(old, shoe):
            raise ShoeLibraryError(f"a different saved shoe already has the id {shoe['id']} ({label(old)}): "
                                   f"give this one a name or size that tells them apart")
    tmp = path.with_name(f"{path.name}.part-{secrets.token_hex(4)}")  # this save's own: two at once never share one
    try:
        tmp.write_text(json.dumps(shoe, indent=1), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    if default:
        set_default(folder, shoe["id"])
    return shoe


def load(folder: Path, sid: str) -> dict:
    """A saved shoe by its id. The id is the file's name (``<id>.json``), whatever the file says inside: a file
    copied or renamed by hand is the shoe its name says."""
    path = _path(folder, sid)
    if not path.is_file():
        raise ShoeLibraryError(f"no saved shoe {sid!r} (footscan shoe list shows them)")
    try:
        shoe = json.loads(path.read_text(encoding="utf-8"))
        ok = (isinstance(shoe, dict) and all(isinstance(shoe.get(k), str) for k in ("name", "size"))
              and all(isinstance(shoe.get(k), (int, float)) for k in ("length_mm", "width_mm"))
              and isinstance(shoe.get("outline"), list) and len(shoe["outline"]) >= 3
              and all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p)
                      for p in shoe["outline"]))
    except (OSError, ValueError):
        ok = False
    if not ok:
        raise ShoeLibraryError(f"saved shoe {sid!r} can't be read: save it again from its insole's scan")
    shoe["id"] = sid
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


def default_id(folder: Path, strict: bool = False) -> str | None:
    """The default saved shoe's id, or None when none is chosen.

    A default that was chosen but can't be used (its file is gone or can't be read, or default.txt itself is
    garbled) is None too, unless ``strict``: then it raises ShoeLibraryError saying so. Making an insole asks
    strictly, so a broken default stops it with that message rather than quietly cutting the insole to another
    outline (the generic insole outline, not this shoe's)."""
    f = Path(folder) / DEFAULT_FILE
    if not f.is_file():
        return None
    try:
        sid = f.read_text(encoding="utf-8").strip()
        if not ID_RE.match(sid):
            raise ShoeLibraryError(f"the default saved shoe ({f}) names no saved shoe: {sid[:40]!r}")
        load(folder, sid)
    except (ShoeLibraryError, OSError, UnicodeDecodeError) as e:
        if not strict:
            return None
        raise ShoeLibraryError(f"the default saved shoe can't be used ({e}). Save it again, or choose another "
                               f"(footscan shoe default <id>, or none for the generic insole outline)") from None
    return sid


def set_default(folder: Path, sid: str | None) -> None:
    """Make a saved shoe the default (None: no default; insoles then take the generic insole outline)."""
    f = Path(folder) / DEFAULT_FILE
    if sid is None:
        f.unlink(missing_ok=True)
        return
    load(folder, sid)  # it has to exist
    # Written whole, then swapped in, as save() writes a shoe: an insole made at that moment reads the old
    # default or the new one, never an empty file (which would read as no default).
    tmp = f.with_name(f"{f.name}.part-{secrets.token_hex(4)}")
    try:
        tmp.write_text(sid + "\n", encoding="utf-8")
        tmp.replace(f)
    finally:
        tmp.unlink(missing_ok=True)


def stamp(folder: Path, sid: str) -> str | None:
    """Cheap fingerprint of a saved shoe's file: changes when it's saved again (an insole made from it is stale)."""
    return file_stamp(_path(folder, sid))


def outline_param(shoe: dict) -> tuple:
    """A saved shoe's outline as ``InsoleParams.shoe_outline`` takes it."""
    return tuple((float(x), float(y)) for x, y in shoe["outline"])


def label(shoe: dict) -> str:
    return f"{shoe['name']}, {shoe['size']}"
