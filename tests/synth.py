"""SYNTHETIC test scenes: rendered photos of the scan mat and the calibration object.

Everything in this file is synthetic. It exists so the reconstruction code can
be checked against an exact answer: here we *choose* the camera positions,
the lens, and the object's pose, then render what a phone would have seen.
Whatever the pipeline recovers from these images can be compared with the
truth to the micrometre.

Numbers from these scenes test the code. They say nothing about how
accurately a real phone scans a real object, and must never be reported as
if they did. The real accuracy number comes only from scanning the printed
calibration object (see docs/phase2-reconstruction.md).

How a picture is made (ray casting)
-----------------------------------
For every pixel, shoot a ray from the camera centre through that pixel and
find the first thing it hits: the object (a triangle mesh, via Embree) or
the floor plane z = 0 (solved directly: the ray p + t*d meets z = 0 at
t = -p_z / d_z). The colour is the surface's own colour (the real mat PDF,
or a speckle pattern on the object) times how much light reaches it:
some ambient light, plus a lamp whose contribution falls off with the angle
between the surface and the light (Lambert's cosine law). A second ray toward
the lamp decides whether the point is in the object's shadow.

Each image is rendered at twice the size and shrunk, which averages four
rays per pixel (anti-aliasing: edges come out soft, as in a real photo).
Then a little sensor noise and JPEG compression, as a phone would add.

Conventions: world = mat coordinates in mm (x right, y toward the toes,
z up). Cameras use OpenCV's convention (x right, y down, z forward) and
OpenCV's pixel convention (pixel centres at integer coordinates).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MAT_DIR = ROOT / "web" / "mat"
TEXTURE_PX_PER_MM = 6.0
LIGHT_DIR = np.array([0.35, -0.45, 1.0]) / np.linalg.norm([0.35, -0.45, 1.0])


def sample(img: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Bilinear lookup of img at float pixel positions (any number of them).

    cv2.remap only accepts maps under 32767 wide, so lay the points out as
    rows of 4096 and flatten again afterwards.
    """
    n = len(u)
    cols = 4096
    pad = (-n) % cols
    mu = np.pad(np.asarray(u, np.float32), (0, pad)).reshape(-1, cols)
    mv = np.pad(np.asarray(v, np.float32), (0, pad)).reshape(-1, cols)
    out = cv2.remap(img, mu, mv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out.ravel()[:n]


@dataclass
class Camera:
    K: np.ndarray            # 3x3, OpenCV pixel convention
    dist: np.ndarray         # OpenCV distortion (k1, k2, p1, p2, k3)
    R: np.ndarray            # world -> camera rotation
    t: np.ndarray            # world -> camera translation (mm)
    width: int
    height: int

    @property
    def center(self) -> np.ndarray:
        return -self.R.T @ self.t

    def project(self, X: np.ndarray) -> np.ndarray:
        rvec, _ = cv2.Rodrigues(self.R)
        uv, _ = cv2.projectPoints(np.asarray(X, float).reshape(-1, 1, 3), rvec, self.t, self.K, self.dist)
        return uv.reshape(-1, 2)

    def to_json(self) -> dict:
        return dict(K=self.K.tolist(), dist=self.dist.tolist(), R=self.R.tolist(), t=self.t.tolist(),
                    width=self.width, height=self.height)


def look_at(eye, target, roll_deg: float = 0.0, up=(0.0, 0.0, 1.0)) -> tuple[np.ndarray, np.ndarray]:
    """World->camera (R, t) for a camera at ``eye`` looking at ``target``.

    The camera's z axis is the viewing direction; its x axis is horizontal
    (perpendicular to both the view and world up), its y axis completes a
    right-handed frame pointing down the image. Roll then turns the image
    about the viewing axis, the way a hand-held phone is never quite level.
    """
    eye, target, up = (np.asarray(v, float) for v in (eye, target, up))
    z = target - eye
    z /= np.linalg.norm(z)
    x = np.cross(z, up)
    if np.linalg.norm(x) < 1e-6:  # looking straight down: any horizontal x will do
        x = np.cross(z, [0.0, 1.0, 0.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.vstack([x, y, z])
    c, s = np.cos(np.radians(roll_deg)), np.sin(np.radians(roll_deg))
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]) @ R
    return R, -R @ eye


@dataclass
class Scene:
    paper: str = "letter"
    object_pose: np.ndarray = field(default_factory=lambda: np.eye(4))  # object -> mat (mm)
    texture: str = "speckle"  # "speckle" (pen dots), "plain" (bare plastic), "skin" (faint mottling)
    mesh_in: object = None    # object to render (object coordinates); default the calibration object
    toe_sheet_offset: tuple = (0.0, 0.0, 0.0)  # (dx mm, dy mm, rotation deg): a slightly crooked tape seam
    seed: int = 0

    def __post_init__(self):
        import trimesh

        from footscan.recon import calib

        board = json.loads((MAT_DIR / f"footscan-mat-{self.paper}.json").read_text())
        self.board = board
        self.sheet_w, self.sheet_h = board["sheet_mm"]
        self.mesh = calib.build() if self.mesh_in is None else self.mesh_in.copy()
        self.mesh.apply_transform(self.object_pose)
        from trimesh.ray.ray_pyembree import RayMeshIntersector

        self.rays = RayMeshIntersector(self.mesh)
        self.sheet_tex = self._render_sheets()
        rng = np.random.default_rng(self.seed)
        # 3-D value noise: random values on a lattice, blended between lattice
        # points. Thresholding it gives irregular dots, like pen speckle.
        self.noise = rng.random((64, 64, 64)).astype(np.float32)
        self.floor_noise = cv2.GaussianBlur(rng.random((512, 512)).astype(np.float32), (0, 0), 6)
        self.floor_noise = (self.floor_noise - self.floor_noise.mean()) / (self.floor_noise.std() + 1e-9)

    # -- textures ---------------------------------------------------------
    def _render_sheets(self) -> list[np.ndarray]:
        import pymupdf

        doc = pymupdf.open(MAT_DIR / f"footscan-mat-{self.paper}.pdf")
        zoom = TEXTURE_PX_PER_MM * 25.4 / 72
        out = []
        for page in doc:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).astype(np.float32) / 255
            out.append(0.05 + 0.87 * img)  # printer black isn't 0, paper isn't 1
        return out

    def sheet_pose(self, index: int) -> np.ndarray:
        """Sheet -> mat transform (3x3 homogeneous 2-D). Sheet 2 may be slightly off its nominal place."""
        if index == 0:
            return np.eye(3)
        dx, dy, deg = self.toe_sheet_offset
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
        # rotate about the middle of the seam, then shift
        pivot = np.array([self.sheet_w / 2, self.sheet_h])
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        T = lambda v: np.array([[1, 0, v[0]], [0, 1, v[1]], [0, 0, 1.0]])
        return T(pivot + [dx, dy]) @ rot @ T(-pivot) @ T([0, self.sheet_h])

    def true_corners(self) -> dict[int, np.ndarray]:
        """Mat-frame 3-D position of every marker corner, as actually laid out in this scene."""
        out = {}
        for i, sheet in enumerate(self.board["sheets"]):
            P = self.sheet_pose(i)
            for mid, corners in sheet["markers"].items():
                c = np.c_[np.asarray(corners, float), np.ones(4)] @ P.T
                out[int(mid)] = np.c_[c[:, :2], np.zeros(4)]
        return out

    def _floor_albedo(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        alb = 0.42 + 0.06 * sample(self.floor_noise, x / 3 % 512, y / 3 % 512)
        for i, tex in enumerate(self.sheet_tex):
            inv = np.linalg.inv(self.sheet_pose(i))
            sx = inv[0, 0] * x + inv[0, 1] * y + inv[0, 2]
            sy = inv[1, 0] * x + inv[1, 1] * y + inv[1, 2]
            inside = (sx >= 0) & (sx <= self.sheet_w) & (sy >= 0) & (sy <= self.sheet_h)
            if not inside.any():
                continue
            # PDF rows run top-down; sheet y runs bottom-up. Texture pixel i
            # covers i/ppm..(i+1)/ppm mm, so its centre (where remap samples
            # it exactly) is half a texture pixel in: subtract 0.5.
            u = sx * TEXTURE_PX_PER_MM - 0.5
            v = (self.sheet_h - sy) * TEXTURE_PX_PER_MM - 0.5
            val = sample(tex, u, v)
            alb = np.where(inside, val, alb)
        return alb

    def _noise3(self, p: np.ndarray, spacing: float, offset: int = 0) -> np.ndarray:
        """Smooth value noise in 0-1 with features about ``spacing`` mm across."""
        g = p / spacing + offset * 17.3
        i0 = np.floor(g).astype(int)
        f = g - i0
        f = f * f * (3 - 2 * f)  # smoothstep blend: no visible lattice creases
        n = self.noise
        acc = np.zeros(len(p))
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    w = (f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2])
                    acc += w * n[(i0[:, 0] + dx) % 64, (i0[:, 1] + dy) % 64, (i0[:, 2] + dz) % 64]
        return acc

    def _object_albedo(self, p_world: np.ndarray) -> np.ndarray:
        if self.texture == "plain":
            return np.full(len(p_world), 0.78)
        inv = np.linalg.inv(self.object_pose)
        p = p_world @ inv[:3, :3].T + inv[:3, 3]  # texture is glued to the object, not the room
        if self.texture == "skin":
            # A GUESS at skin under room light: faint mottling at three scales
            # (pores ~0.8 mm, blotches ~3 mm, shading-like patches ~9 mm),
            # a few percent of brightness each. Real skin decides.
            return (0.70 + 0.05 * (self._noise3(p, 0.8) - 0.5) + 0.06 * (self._noise3(p, 3.0, 1) - 0.5)
                    + 0.06 * (self._noise3(p, 9.0, 2) - 0.5))
        dots = np.clip((self._noise3(p, 1.2) - 0.62) / 0.08, 0, 1)  # pen dots about a millimetre across
        return 0.80 - 0.62 * dots

    # -- rendering --------------------------------------------------------
    def render(self, cam: Camera, supersample: int = 2) -> np.ndarray:
        s = supersample
        W, H = cam.width * s, cam.height * s
        K = cam.K.copy()
        K[:2] *= s
        K[0, 2] = cam.K[0, 2] * s + (s - 1) / 2  # pixel centres move when the grid gets finer
        K[1, 2] = cam.K[1, 2] * s + (s - 1) / 2
        u, v = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
        pix = np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2)
        # Undo the lens distortion to find which straight-line ray each pixel sees.
        norm = cv2.undistortPoints(pix, K, cam.dist).reshape(-1, 2)
        d_cam = np.c_[norm, np.ones(len(norm))]
        d = d_cam @ cam.R  # camera -> world: R^T d, written as row vectors
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        o = np.broadcast_to(cam.center, d.shape)

        t_hit = np.full(len(d), np.inf)
        normal = np.zeros_like(d)
        loc, idx_ray, idx_tri = self.rays.intersects_location(o, d, multiple_hits=False)
        if len(idx_ray):
            t_hit[idx_ray] = np.einsum("ij,ij->i", loc - o[idx_ray], d[idx_ray])
            normal[idx_ray] = self.mesh.face_normals[idx_tri]
        with np.errstate(divide="ignore", invalid="ignore"):
            t_floor = np.where(d[:, 2] < -1e-9, -o[:, 2] / d[:, 2], np.inf)
        floor = t_floor < t_hit
        obj = np.isfinite(t_hit) & ~floor
        t = np.where(floor, t_floor, t_hit)
        p = o + d * np.where(np.isfinite(t), t, 0)[:, None]
        normal[floor] = (0.0, 0.0, 1.0)

        albedo = np.full(len(d), 0.6)  # sky / far wall
        albedo[floor] = self._floor_albedo(p[floor, 0], p[floor, 1])
        if obj.any():
            albedo[obj] = self._object_albedo(p[obj])
        lit = np.clip(normal @ LIGHT_DIR, 0, None)
        hit = floor | obj
        # Shadow rays: from just above the surface toward the lamp.
        sh_idx = np.flatnonzero(hit & (lit > 0))
        if len(sh_idx):
            origins = p[sh_idx] + normal[sh_idx] * 0.05
            blocked = self.rays.intersects_any(origins, np.broadcast_to(LIGHT_DIR, origins.shape))
            lit[sh_idx[blocked]] = 0
        shade = np.where(hit, 0.38 + 0.62 * lit, 1.0)
        img = (albedo * shade).reshape(H, W)
        img = cv2.resize(img.astype(np.float32), (cam.width, cam.height), interpolation=cv2.INTER_AREA)
        return img

    def photo(self, cam: Camera, rng: np.random.Generator) -> np.ndarray:
        """8-bit colour image with sensor noise (JPEG compression happens on save)."""
        img = self.render(cam)
        img = img + rng.normal(0, 1.5 / 255, img.shape)
        g = np.clip(img * 255, 0, 255).astype(np.uint8)
        # A faint colour cast so the image is genuinely 3-channel, like a phone's.
        return cv2.merge([g, np.clip(g.astype(int) + 3, 0, 255).astype(np.uint8), g])


def ring_cameras(target, *, width=540, height=960, focal=700.0, k1=0.04, distance=380.0,
                 rings=((22, 10), (42, 10), (64, 8), (84, 3)), seed=0) -> list[Camera]:
    """Cameras circling a target like a person walking around the foot.

    ``rings`` is (elevation in degrees above the floor, number of photos).
    Each camera is jittered a little (distance, aim, roll) because no one
    holds a phone on a perfect circle.
    """
    rng = np.random.default_rng(seed)
    target = np.asarray(target, float)
    K = np.array([[focal, 0, (width - 1) / 2 + 3.0], [0, focal, (height - 1) / 2 - 4.0], [0, 0, 1]])
    dist = np.array([k1, 0, 0, 0, 0], float)
    cams = []
    for elev, n in rings:
        for i in range(n):
            az = 2 * np.pi * (i + 0.5 * (elev // 20 % 2)) / n
            r = distance * rng.uniform(0.92, 1.08)
            e = np.radians(elev + rng.uniform(-3, 3))
            eye = target + r * np.array([np.cos(e) * np.cos(az), np.cos(e) * np.sin(az), np.sin(e)])
            aim = target + rng.uniform(-12, 12, 3) * [1, 1, 0.3]
            R, t = look_at(eye, aim, roll_deg=rng.uniform(-6, 6))
            cams.append(Camera(K, dist, R, t, width, height))
    return cams


def object_pose(x: float, y: float, yaw_deg: float) -> np.ndarray:
    """Object -> mat transform: the object's centre placed at (x, y), turned by yaw."""
    from footscan.recon import calib

    c, s = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    T = np.eye(4)
    T[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    centre = np.array([calib.LENGTH / 2, calib.WIDTH / 2, 0])
    T[:3, 3] = np.array([x, y, 0]) - T[:3, :3] @ centre
    return T


def make_capture(out_dir: Path, *, scene: Scene | None = None, cameras: list[Camera] | None = None,
                 seed: int = 0, jpeg_quality: int = 92) -> dict:
    """Render a whole synthetic capture in the same layout the website saves.

    Writes frame_NNNN.jpg, capture.json (as the server writes it, marked
    synthetic) and truth.json (the cameras and object pose we chose).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Lengthwise on the mat (like a foot), slightly turned, between the marker columns.
    scene = scene or Scene(object_pose=object_pose(108.0, 279.4, 98.0), seed=seed)
    b = scene.mesh.bounds  # already placed on the mat
    centre = np.array([(b[0, 0] + b[1, 0]) / 2, (b[0, 1] + b[1, 1]) / 2, (b[1, 2]) * 0.45])
    cameras = cameras or ring_cameras(centre, seed=seed)
    rng = np.random.default_rng(seed + 1)
    frames = []
    for i, cam in enumerate(cameras, 1):
        name = f"frame_{i:04d}.jpg"
        cv2.imwrite(str(out_dir / name), scene.photo(cam, rng), [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        frames.append(dict(file=name, original_n=i, width=cam.width, height=cam.height, excluded=False))
    capture = dict(capture_id=out_dir.name, synthetic=True, condition="object", foot=None, measurable=False,
                   mat_paper=scene.paper, frames=frames,
                   note="SYNTHETIC: rendered for testing the reconstruction code; not a real scan")
    (out_dir / "capture.json").write_text(json.dumps(capture, indent=1))
    truth = dict(synthetic=True, paper=scene.paper, object_pose=scene.object_pose.tolist(),
                 texture=scene.texture, toe_sheet_offset=list(scene.toe_sheet_offset),
                 cameras={f["file"]: c.to_json() for f, c in zip(frames, cameras)})
    (out_dir / "truth.json").write_text(json.dumps(truth))
    return truth


def block_foot(yaw_deg: float = 0.0, foot: str = "right", origin=(100.0, 150.0), floor_cut: bool = True):
    """SYNTHETIC 'foot' for tests: exact, simple geometry with known answers.

    In its own coordinates (x forward, y toward the foot's left, z up), mm:
    a 240 x 90 x 25 body whose back end is a half-cylinder (a rounded heel,
    rearmost point (0, 45)); a 12 mm high arch tunnel under the inner 36 mm
    (x 70-150; inner = left for a right foot); a 30 mm radius leg standing
    over the heel at (45, 45). Then turned by ``yaw_deg`` and placed at
    ``origin`` on the mat. ``floor_cut`` removes the bottom faces, as a
    standing scan has none.
    """
    import manifold3d as m3
    import trimesh

    M = m3.Manifold
    body = M.cube((195.0, 90.0, 25.0)).translate((45.0, 0.0, 0.0)) + M.cylinder(25.0, 45.0, 45.0, 128).translate((45.0, 45.0, 0.0))
    medial_y0 = 54.0 if foot == "right" else 0.0
    tunnel = M.cube((80.0, 36.0, 12.0)).translate((70.0, medial_y0, 0.0))
    leg = M.cylinder(120.0, 30.0, 30.0, 96).translate((45.0, 45.0, 20.0))
    solid = (body - tunnel) + leg
    mm = solid.to_mesh()
    m = trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=True)
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=2.0)
    m = trimesh.Trimesh(v, f, process=True)
    if floor_cut:
        m.update_faces(~((m.face_normals[:, 2] < -0.99) & (m.triangles_center[:, 2] < 0.01)))
        m.remove_unreferenced_vertices()
    m.apply_transform(foot_pose(yaw_deg, origin))
    return m


def foot_pose(yaw_deg: float = 0.0, origin=(100.0, 150.0)) -> np.ndarray:
    """Foot coordinates -> mat coordinates for block_foot."""
    c, s = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    T = np.eye(4)
    T[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    T[:3, 3] = [origin[0], origin[1], 0.0]
    return T


def dome_foot(length: float = 240.0, width: float = 92.0, height: float = 58.0):
    """SYNTHETIC smooth, foot-sized dome: the top half of an ellipsoid, open at the floor.

    Not a foot, but smooth and curved everywhere like one (no edges, no flat
    faces), which is what the smoothing and low-texture experiments need. A
    gentle forward-leaning bulge breaks the symmetry.
    """
    import trimesh

    m = trimesh.creation.icosphere(subdivisions=6, radius=1.0)
    v = m.vertices.copy()
    v[:, 0] *= length / 2
    v[:, 1] *= width / 2
    v[:, 2] *= height
    v[:, 2] *= 1.0 - 0.25 * np.clip(v[:, 0] / (length / 2), 0, 1)  # lower toward the toes
    m = trimesh.Trimesh(v + [length / 2, width / 2, 0.0], m.faces, process=True)
    m.update_faces(m.triangles_center[:, 2] > 0)
    m.remove_unreferenced_vertices()
    return m


def shaped_foot(foot: str = "right", leg: bool = True):
    """SYNTHETIC foot-shaped solid for tests, with a heel narrower than the ball of the foot.

    Foot coordinates (x forward, y toward the foot's left, z up), mm: the
    plan is the rubber band round three circles (heel r 32 at x 32, ball
    r 50 at x 165, toes r 28 at x 222, all on y = 45): 250 long, 64 wide
    at the heel, 100 at the ball. 25 mm thick; a 12 mm high arch tunnel
    under the inner side (x 70-150, from 14 mm inside the centre line
    outward; inner = left for a right foot); optionally a 28 mm radius leg
    over the heel at (45, 45), up to 140 mm. Closed (the sole is a surface).
    """
    import manifold3d as m3
    import shapely
    import trimesh
    from shapely.geometry import Point

    M = m3.Manifold
    plan = shapely.convex_hull(shapely.union_all([Point(32, 45).buffer(32, 64), Point(165, 45).buffer(50, 64),
                                                  Point(222, 45).buffer(28, 64)]))
    ring = np.asarray(shapely.geometry.polygon.orient(plan, 1.0).exterior.coords)[:-1]
    body = M.extrude(m3.CrossSection([ring], m3.FillRule.Positive), 25.0)
    y0 = 59.0 if foot == "right" else -40.0
    solid = body - M.cube((80.0, 71.0, 13.0)).translate((70.0, y0, -1.0))
    if leg:
        solid = solid + M.cylinder(120.0, 28.0, 28.0, 96).translate((45.0, 45.0, 20.0))
    mm = solid.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=True)


def foam_print(foot: str = "right", depth: float = 30.0, shape: str = "shaped"):
    """SYNTHETIC foam impression box: a 330 x 130 x 70 mm block with ``shaped_foot`` (or, with
    ``shape="curved"``, ``curved_foot``) pressed
    ``depth`` mm straight down into it (the foam is crushed everywhere above the sole,
    and left alone under the arch), on a table. Closed, as Object Capture leaves a model."""
    import manifold3d as m3
    import trimesh

    M = m3.Manifold
    foot_mm = shaped_foot(foot, leg=False) if shape == "shaped" else curved_foot(foot, leg=False)
    f = M(m3.Mesh(vert_properties=np.asarray(foot_mm.vertices, dtype=np.float32),
                  tri_verts=np.asarray(foot_mm.faces, dtype=np.uint32)))
    sole_z = 70.0 - depth
    # Everything above the sole is crushed: the foot itself, plus its plan view from the arch's
    # height (12 mm) upward, so foam stays only where the foot never reached (under the arch).
    import shapely
    from shapely.geometry import Point

    plan = shapely.convex_hull(shapely.union_all([Point(32, 45).buffer(32, 64), Point(165, 45).buffer(50, 64),
                                                  Point(222, 45).buffer(28, 64)]))
    ring = np.asarray(shapely.geometry.polygon.orient(plan, 1.0).exterior.coords)[:-1]
    above = M.extrude(m3.CrossSection([ring], m3.FillRule.Positive), 120.0).translate(
        (0.0, 0.0, sole_z + (12.0 if shape == "shaped" else 40.0)))  # from inside the foot (above its arch) up
    sweep = f.translate((0.0, 0.0, sole_z)) + above
    block = M.cube((330.0, 130.0, 70.0)).translate((-40.0, -20.0, 0.0))
    mm = (block - sweep).to_mesh()
    m = trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=True)
    table = trimesh.Trimesh([[-120, -100, 0], [370, -100, 0], [370, 210, 0], [-120, 210, 0]], [[0, 1, 2], [0, 2, 3]])
    return trimesh.util.concatenate([m, table])


def bumps(mesh, amp: float, waves=(3.0, 8.0), n: int = 40, seed: int = 0):
    """SYNTHETIC scan noise: smooth bumps along the surface normal, a sum of ``n`` random
    waves with wavelengths in ``waves`` (mm), scaled to a standard deviation of ``amp`` mm."""
    import trimesh

    rng = np.random.default_rng(seed)
    m = mesh.copy()
    V, N = m.vertices, m.vertex_normals
    d = np.zeros(len(V))
    for _ in range(n):
        k = rng.normal(size=3)
        k /= np.linalg.norm(k)
        d += np.sin(V @ k * 2 * np.pi / rng.uniform(*waves) + rng.uniform(0, 2 * np.pi))
    d *= amp / d.std()
    return trimesh.Trimesh(V + N * d[:, None], m.faces, process=False)


def refined(mesh, edge: float = 2.0):
    """The same shape split into triangles no longer than ``edge`` mm (so noise has points to move)."""
    import trimesh

    v, f = trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces, max_edge=edge)
    return trimesh.Trimesh(v, f, process=True)


# The shape of curved_foot's sole, in foot coordinates (x forward from the heel, y toward the
# foot's left), heights in mm above the floor plane it rests on. Public so tests can compare.
CURVED_ARCH_MM = 14.0     # arch peak above the floor
CURVED_EDGE_MM = 4.0      # how far the sole curls up over the last few mm to the edge


def curved_plan():
    import shapely
    from shapely.geometry import Point

    return shapely.convex_hull(shapely.union_all([Point(32, 45).buffer(32, 64), Point(165, 45).buffer(50, 64),
                                                  Point(222, 45).buffer(28, 64)]))


def curved_sole(x, y, foot: str = "right"):
    """SYNTHETIC sole height (mm) at foot coordinates x, y: flat where the heel pad and the ball
    of the foot touch the floor, a smooth arch rising toward the inner side through the midfoot
    (peak ``CURVED_ARCH_MM`` at x = 110, 12 mm in from the inner edge), and a rounded edge all
    round (rising ``CURVED_EDGE_MM`` over the last 6 mm), like a real sole. No sharp corners."""
    import shapely

    x, y = np.asarray(x, float), np.asarray(y, float)
    plan = curved_plan()
    inner = 1.0 if foot == "right" else -1.0  # inner side is +y (the foot's left) for a right foot
    d_edge = np.asarray(shapely.distance(plan.exterior, shapely.points(np.c_[x.ravel(), y.ravel()]))).reshape(x.shape)
    inside_side = inner * (y - 45.0)  # > 0 on the inner half
    along = np.exp(-0.5 * ((x - 110.0) / 28.0) ** 2)
    across = 1.0 / (1.0 + np.exp(-(inside_side - 15.0) / 6.0))
    arch = CURVED_ARCH_MM * along * across
    edge = CURVED_EDGE_MM * np.clip(1 - d_edge / 6.0, 0, 1) ** 2
    return arch + edge


def curved_foot(foot: str = "right", leg: bool = True, top: float = 45.0, cell: float = 2.0):
    """SYNTHETIC foot with a realistic, smooth sole (``curved_sole``), closed, in foot coordinates
    (z up, the floor the sole rests on at z = 0). Built by extruding the plan to ``top`` mm and
    bending each point's height so the bottom follows the sole and the top stays flat:
    z -> sole + z * (top - sole) / top. Optionally a 28 mm radius leg over the heel."""
    import manifold3d as m3
    import trimesh

    plan = curved_plan()
    import shapely

    ring = np.asarray(shapely.geometry.polygon.orient(plan, 1.0).exterior.coords)[:-1]
    solid = m3.Manifold.extrude(m3.CrossSection([ring], m3.FillRule.Positive), top).refine_to_length(cell)

    def bend(v):
        v = np.array(v, dtype=float, copy=True)
        s = curved_sole(v[:, 0], v[:, 1], foot)
        v[:, 2] = s + v[:, 2] * (top - s) / top
        return v

    solid = solid.warp_batch(bend)
    if leg:
        solid = (solid + m3.Manifold.cylinder(120.0, 28.0, 28.0, 64).translate((45.0, 45.0, top - 5.0))).refine_to_length(cell)
    mm = solid.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=True)


def speckle(mesh, sigma: float, grain_mm: float = 2.0, seed: int = 0):
    """SYNTHETIC scan noise with a set strength and grain: random per-point offsets along the
    surface normal, blurred over the surface to about ``grain_mm`` across, then scaled to a
    standard deviation of ``sigma`` mm. Unlike ``bumps`` (waves through space, which can lie
    along the surface as long, shape-like undulations), every bump here is about the grain size."""
    import trimesh
    import trimesh.smoothing

    rng = np.random.default_rng(seed)
    m = mesh.copy()
    d = rng.normal(size=len(m.vertices))
    edge = float(np.median(m.edges_unique_length))
    L = trimesh.smoothing.laplacian_calculation(m, equal_weight=True)
    for _ in range(int(np.ceil((grain_mm / edge) ** 2))):
        d = L.dot(d)
    d *= sigma / d.std()
    return trimesh.Trimesh(m.vertices + m.vertex_normals * d[:, None], m.faces, process=False)
