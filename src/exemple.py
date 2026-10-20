"""Procedural planet generator -> GLB (no Blender needed).

Builds a realistic planet from scratch with numpy + Pillow:

* an equirectangular colour texture and an emission texture
  (lava glow, city lights) with crisp detail,
* a displaced sphere mesh, so mountains and craters really change the
  silhouette and catch the light,
* an embedded GLB (JPEG textures) that raylib loads directly.

Styles: ``lava`` (default), ``terran`` (oceans, continents, clouds, city
lights) and ``desert`` (rust plains, craters, polar caps).

Usage:
    python3 make_planet_glb.py --style lava --seed 12 --out planet.glb
    python3 make_planet_glb.py --style lava --size 1024 --mesh 128 \
        --out planet_low.glb
"""
import argparse
import io
import json
import math
import struct
import time
from typing import Dict, List, Sequence, Tuple

import numpy as np
from PIL import Image

F32 = np.float32
Array = np.ndarray

_GRADS = np.array(
    [[1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
     [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
     [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1]], dtype=F32)


# ----------------------------------------------------------------- noise
class Noise:
    """3D gradient (Perlin) noise, fractal sums and ridged noise."""

    def __init__(self, seed: int) -> None:
        """Create a noise source; the same seed gives the same planet."""
        self.seed = int(seed) & 0xFFFF

    def _hash(self, ix: Array, iy: Array, iz: Array) -> Array:
        h = (ix * 374761393 + iy * 668265263 + iz * 1274126177
             + self.seed * 144665)
        h = (h ^ (h >> 13)) * 1103515245
        h = h ^ (h >> 16)
        return np.asarray(h & 0x7FFFFFFF, dtype=np.int64)

    def perlin(self, p: Array) -> Array:
        """Gradient noise, roughly in [-1, 1]. ``p`` has shape (..., 3)."""
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        x0, y0, z0 = np.floor(x), np.floor(y), np.floor(z)
        fx, fy, fz = x - x0, y - y0, z - z0
        ix, iy, iz = (x0.astype(np.int64), y0.astype(np.int64),
                      z0.astype(np.int64))
        ux = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
        uy = fy * fy * fy * (fy * (fy * 6 - 15) + 10)
        uz = fz * fz * fz * (fz * (fz * 6 - 15) + 10)
        total = np.zeros(x.shape, dtype=F32)
        for dx in (0, 1):
            wx = ux if dx else 1 - ux
            for dy in (0, 1):
                wy = uy if dy else 1 - uy
                for dz in (0, 1):
                    wz = uz if dz else 1 - uz
                    grad = _GRADS[self._hash(ix + dx, iy + dy, iz + dz) % 12]
                    dot = (grad[..., 0] * (fx - dx) + grad[..., 1] * (fy - dy)
                           + grad[..., 2] * (fz - dz))
                    total += dot * wx * wy * wz
        return np.asarray(np.clip(total * F32(1.2), -1.0, 1.0), dtype=F32)

    def fbm(self, p: Array, octaves: int, gain: float = 0.5) -> Array:
        """Fractal Brownian motion, roughly in [-1, 1]."""
        total = np.zeros(p.shape[:-1], dtype=F32)
        amp, freq, norm = 1.0, 1.0, 0.0
        for octave in range(octaves):
            offset = F32(octave * 17.31 + self.seed * 0.137)
            total += F32(amp) * self.perlin(p * F32(freq) + offset)
            norm += amp
            amp *= gain
            freq *= 2.0
        return total / F32(norm)

    def worley(self, p: Array, scale: float) -> Tuple[Array, Array, Array]:
        """Cellular noise: (F1, F2, random value of the nearest cell)."""
        q = p * F32(scale)
        base = np.floor(q)
        ib = base.astype(np.int64)
        frac = q - base
        best1 = np.full(q.shape[:-1], 9.0, dtype=F32)
        best2 = np.full(q.shape[:-1], 9.0, dtype=F32)
        value = np.zeros(q.shape[:-1], dtype=F32)
        norm = F32(1.0 / 0x7FFFFFFF)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    cx = ib[..., 0] + dx
                    cy = ib[..., 1] + dy
                    cz = ib[..., 2] + dz
                    jx = self._hash(cx, cy, cz).astype(F32) * norm
                    jy = self._hash(cx + 7919, cy, cz).astype(F32) * norm
                    jz = self._hash(cx, cy + 6151, cz).astype(F32) * norm
                    ex = dx + jx - frac[..., 0]
                    ey = dy + jy - frac[..., 1]
                    ez = dz + jz - frac[..., 2]
                    dist = np.sqrt(ex * ex + ey * ey + ez * ez)
                    nearer = dist < best1
                    rnd = self._hash(cx, cy, cz + 4663).astype(F32) * norm
                    value = np.where(nearer, rnd, value)
                    best2 = np.where(nearer, best1, np.minimum(best2, dist))
                    best1 = np.minimum(best1, dist)
        return best1, best2, value

    def ridged(self, p: Array, octaves: int) -> Array:
        """Sharp mountain-chain noise in [0, 1]."""
        total = np.zeros(p.shape[:-1], dtype=F32)
        amp, freq, norm = 1.0, 1.0, 0.0
        for octave in range(octaves):
            offset = F32(octave * 29.7 + self.seed * 0.211)
            ridge = 1.0 - np.abs(self.perlin(p * F32(freq) + offset))
            total += F32(amp) * ridge * ridge
            norm += amp
            amp *= 0.5
            freq *= 2.0
        return total / F32(norm)


# ------------------------------------------------------------ helpers
def smoothstep(edge0: float, edge1: float, x: Array) -> Array:
    """GLSL-like smoothstep (works when edge0 > edge1 too)."""
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(F32)


def lerp(a: Array, b: Array, t: Array) -> Array:
    """Linear interpolation; ``t`` is broadcast over the colour axis."""
    return np.asarray(a + (b - a) * t, dtype=F32)


def color(*rgb: float) -> Array:
    """Colour constant as a float32 vector."""
    return np.array(rgb, dtype=F32)


def ramp(t: Array, stops: Sequence[Tuple[float, Tuple[float, ...]]]) -> Array:
    """Piecewise-linear colour ramp over an array of values."""
    pos = [s[0] for s in stops]
    cols = np.array([s[1] for s in stops], dtype=F32)
    t = np.clip(t, pos[0], pos[-1])
    return np.stack([np.interp(t, pos, cols[:, c]) for c in range(3)],
                    axis=-1).astype(F32)


def blur(a: Array, radius: int, passes: int = 2) -> Array:
    """Box blur (wraps horizontally, clamps at the poles)."""
    size = 2 * radius + 1
    for _ in range(passes):
        pad = np.pad(a, ((0, 0), (radius, radius)), mode="wrap")
        cs = np.cumsum(pad, axis=1, dtype=np.float64)
        cs = np.concatenate([np.zeros((a.shape[0], 1)), cs], axis=1)
        a = ((cs[:, size:] - cs[:, :-size]) / size).astype(F32)
        pad = np.pad(a, ((radius, radius), (0, 0)), mode="edge")
        cs = np.cumsum(pad, axis=0, dtype=np.float64)
        cs = np.concatenate([np.zeros((1, a.shape[1])), cs], axis=0)
        a = ((cs[size:] - cs[:-size]) / size).astype(F32)
    return a


def normalize(a: Array, low: float = 1.0, high: float = 99.0) -> Array:
    """Rescale to [-1, 1] using percentiles (robust to outliers)."""
    lo, hi = np.percentile(a, [low, high])
    scaled = np.clip((a - lo) / (hi - lo) * 2.0 - 1.0, -1.0, 1.0)
    return np.asarray(scaled, dtype=F32)


def sphere_directions(width: int, height: int) -> Array:
    """Unit vector of every texel of an equirectangular map."""
    lon = (np.arange(width, dtype=F32) + 0.5) / width * 2 * math.pi - math.pi
    lat = math.pi / 2 - (np.arange(height, dtype=F32) + 0.5) / height * math.pi
    lon_g, lat_g = np.meshgrid(lon, lat)
    return np.stack([np.cos(lat_g) * np.cos(lon_g), np.sin(lat_g),
                     -np.cos(lat_g) * np.sin(lon_g)], axis=-1).astype(F32)


def add_craters(dirs: Array, height: Array, rng: np.random.Generator,
                count: int, max_radius: float, depth: float
                ) -> List[Tuple[Array, float]]:
    """Carve impact craters into ``height`` (in place).

    Returns the big ones (centre, angular radius) for later decoration.
    """
    flat = dirs.reshape(-1, 3)
    out: List[Tuple[Array, float]] = []
    for _ in range(count):
        vec = rng.normal(size=3).astype(F32)
        centre = vec / np.linalg.norm(vec)
        radius = float(max_radius * rng.random() ** 2.6 + 0.012)
        cos_d = flat @ centre
        mask = cos_d > math.cos(min(radius * 2.2, 3.0))
        if not mask.any():
            continue
        d = np.arccos(np.clip(cos_d[mask], -1, 1)) / radius
        bowl = -np.clip(1.0 - d * d, 0.0, None) ** 0.8
        rim = 0.35 * np.exp(-((d - 1.05) / 0.22) ** 2)
        profile = (bowl + rim) * depth * (0.4 + 0.6 * min(radius / 0.05, 1.0))
        view = height.reshape(-1)
        view[mask] += profile.astype(F32)
        if radius > 0.06:
            out.append((centre, radius))
    return out


# ---------------------------------------------------------------- worlds
class World:
    """Result of a style: textures plus the height field for the mesh."""

    def __init__(self, albedo: Array, emission: Array, height: Array,
                 flat_level: float, displace: float) -> None:
        """Store the maps (albedo/emission in [0,1], height in [-1,1])."""
        self.albedo = albedo
        self.emission = emission
        self.height = height
        self.flat_level = flat_level
        self.displace = displace


def lava_world(dirs: Array, seed: int) -> World:
    """Volcanic world: cracked basalt plates, glowing seams, magma seas."""
    noise = Noise(seed)
    rng = np.random.default_rng(seed)
    p = dirs
    scale = max(dirs.shape[1] / 2048.0, 0.25)
    warp = np.stack([noise.fbm(p * F32(1.4) + F32(o), 3)
                     for o in (3.1, 8.7, 14.3)], axis=-1) * F32(0.10)
    q = p + warp
    continents = noise.fbm(q * F32(1.5), 6)
    chains = noise.ridged(q * F32(3.4), 5)
    mountain_zone = smoothstep(0.0, 0.5, noise.fbm(q * F32(0.9) + 7, 3))
    h = continents * 0.7 + (chains - 0.5) * mountain_zone * 0.9
    craters = add_craters(dirs, h, rng, int(150 * scale + 40), 0.16, 0.22)
    h = normalize(h)
    level = float(np.percentile(h, 29))
    low = smoothstep(level + 0.5, level - 0.1, h)
    high = smoothstep(0.1, 0.9, h)

    # --- crust plates (cellular noise) and the cracks between them
    jag = noise.fbm(q * F32(38.0) + 5, 3) * 0.045
    f1a, f2a, plate_a = noise.worley(q, 6.0)
    f1b, f2b, plate_b = noise.worley(q, 15.0)
    edge_a = np.maximum(f2a - f1a + jag, 0)
    edge_b = np.maximum(f2b - f1b + jag * 0.7, 0)
    zone = 0.5 + 0.5 * noise.fbm(q * F32(1.3) + 19, 3)
    vigor = smoothstep(0.30, 0.75, 0.5 + 0.5 * noise.fbm(q * F32(3.2) + 77, 4))
    width_a = (0.032 + 0.15 * zone * zone * (0.4 + 0.6 * vigor)).astype(F32)
    width_b = (0.026 + 0.09 * zone * (0.4 + 0.6 * vigor)).astype(F32)
    seam_a = 1 - smoothstep(0.0, 1.0, edge_a / width_a)
    seam_b = (1 - smoothstep(0.0, 1.0, edge_b / width_b)) * smoothstep(
        0.45, 0.62, zone)
    cracks = np.maximum(seam_a * (0.45 + 0.55 * vigor), 0.85 * seam_b) * (
        0.45 + 0.55 * low)

    # --- magma seas with broken crust floating on them
    sea = smoothstep(level + 0.02, level - 0.05, h)
    floe = smoothstep(0.34, 0.40, plate_b) * (1 - seam_b)
    open_lava = np.clip(np.maximum(sea * (1 - 0.97 * floe),
                                   cracks * 0.97), 0, 1)
    pulse = 0.5 + 0.5 * noise.fbm(q * F32(9.0) + 31, 4)
    heat = np.clip((0.35 + 0.65 * pulse)
                   * (0.55 + 0.45 * np.maximum(seam_a, sea)), 0, 1) * open_lava
    halo = blur(open_lava, max(2, int(5 * scale + 1)))

    glow = ramp(heat, [(0.0, (0.40, 0.02, 0.0)), (0.35, (0.95, 0.20, 0.02)),
                       (0.70, (1.0, 0.56, 0.10)), (1.0, (1.0, 0.90, 0.45))])
    ember = ramp(np.clip(halo * 1.7, 0, 1),
                 [(0.0, (0, 0, 0)), (0.5, (0.32, 0.045, 0.01)),
                  (1.0, (0.75, 0.15, 0.02))])
    emission = np.clip(glow * open_lava[..., None]
                       + ember * (1 - open_lava[..., None]) * 0.8, 0, 1)

    # --- rock colours: plate tints, ash, sulfur, scorched edges, relief
    grain = 0.5 + 0.5 * noise.fbm(q * F32(11.0) + 41, 6)
    plate_tint = (0.62 + 0.85 * plate_a)[..., None]
    rock = lerp(color(0.050, 0.043, 0.045), color(0.27, 0.205, 0.17),
                grain[..., None]) * plate_tint
    rock = lerp(rock, color(0.30, 0.27, 0.25), (0.40 * high)[..., None])
    soot = smoothstep(0.55, 0.8, 0.5 + 0.5 * noise.fbm(q * F32(2.3) + 61, 5))
    rock = rock * (1.0 - 0.5 * soot[..., None])
    sulfur = smoothstep(0.66, 0.78, 0.5 + 0.5 * noise.fbm(
        q * F32(3.9) + 51, 4)) * (1 - high) * 0.7
    rock = lerp(rock, color(0.60, 0.48, 0.12), sulfur[..., None])
    scorched = np.clip(halo * 2.2, 0, 1) * (1 - open_lava)
    rock = lerp(rock, color(0.36, 0.08, 0.03), (0.85 * scorched)[..., None])
    rim = smoothstep(0.0, 0.22, edge_a)
    rock = rock * (0.55 + 0.45 * rim[..., None])
    fine = 0.5 + 0.5 * noise.fbm(p * F32(46.0) + 71, 4)
    cavity = np.clip(0.5 + 7.0 * (h - blur(h, max(3, int(9 * scale)))), 0, 1)
    rock = rock * (0.60 + 0.60 * cavity[..., None]) * (
        0.70 + 0.60 * fine[..., None])
    for centre, radius in craters:
        cos_d = np.clip(dirs.reshape(-1, 3) @ centre, -1, 1)
        d = (np.arccos(cos_d) / radius).reshape(dirs.shape[:2])
        rock = rock * (1.0 - 0.35 * smoothstep(1.3, 0.2, d)[..., None])
    albedo = np.clip(lerp(rock, glow * 0.75, open_lava[..., None]), 0, 1)
    return World(albedo, emission, h, level, 0.020)


def terran_world(dirs: Array, seed: int) -> World:
    """Earth-like world: oceans, biomes, ice caps, clouds, city lights."""
    noise = Noise(seed)
    p = dirs
    lat = np.abs(dirs[..., 1])
    warp = np.stack([noise.fbm(p * F32(1.2) + F32(o), 3)
                     for o in (2.0, 6.5, 11.0)], axis=-1) * F32(0.3)
    q = p + warp
    h = normalize(noise.fbm(q * F32(1.6), 6) * 0.8
                  + (noise.ridged(q * F32(4.0), 4) - 0.5)
                  * smoothstep(0.1, 0.6, noise.fbm(q + 5, 3)) * 0.7)
    level = float(np.percentile(h, 58))
    land = smoothstep(level, level + 0.02, h)
    depth = smoothstep(level, level - 0.6, h)
    ocean = lerp(color(0.05, 0.30, 0.45), color(0.01, 0.045, 0.19),
                 depth[..., None])
    temp = np.clip(1.0 - lat * 1.25 + 0.15 * noise.fbm(q * 2.0 + 9, 3), 0, 1)
    moist = 0.5 + 0.5 * noise.fbm(q * F32(2.4) + 13, 4)
    biome = ramp(moist, [(0.0, (0.62, 0.52, 0.32)), (0.35, (0.45, 0.45, 0.22)),
                         (0.6, (0.18, 0.38, 0.14)), (1.0, (0.08, 0.24, 0.10))])
    biome = lerp(biome, color(0.55, 0.52, 0.45), smoothstep(0.35, 0.1, temp)[
        ..., None] * 0.8)
    rocky = smoothstep(0.35, 0.8, h)
    land_col = lerp(biome, color(0.34, 0.31, 0.28), rocky[..., None])
    detail = 0.5 + 0.5 * noise.fbm(p * F32(30.0) + 3, 4)
    land_col = land_col * (0.8 + 0.4 * detail[..., None])
    surface = lerp(ocean, land_col, land[..., None])
    ice = np.maximum(smoothstep(0.80, 0.9, lat + 0.06 * noise.fbm(q * 3, 3)),
                     smoothstep(0.82, 0.95, h) * 0.9)
    surface = lerp(surface, color(0.93, 0.95, 0.98), ice[..., None])
    clouds = smoothstep(0.50, 0.78, 0.5 + 0.5 * noise.fbm(
        (q + warp) * F32(3.0) + 17, 6))
    albedo = np.clip(lerp(surface, color(0.96, 0.96, 0.97),
                          (0.88 * clouds)[..., None]), 0, 1)
    city_zone = smoothstep(0.5, 0.65, 0.5 + 0.5 * noise.fbm(
        q * F32(3.5) + 23, 4))
    dots = smoothstep(0.55, 0.72, 0.5 + 0.5 * noise.fbm(
        p * F32(60.0) + 5, 3))
    lit = land * (1 - ice) * city_zone * dots * (1 - clouds)
    emission = np.clip(lit[..., None] * color(1.0, 0.78, 0.40), 0, 1)
    return World(albedo, emission, h, level, 0.012)


def desert_world(dirs: Array, seed: int) -> World:
    """Rust-coloured world: plains, dark basalt, craters, polar caps."""
    noise = Noise(seed)
    rng = np.random.default_rng(seed)
    p = dirs
    lat = np.abs(dirs[..., 1])
    warp = np.stack([noise.fbm(p * F32(1.3) + F32(o), 3)
                     for o in (1.0, 5.5, 9.0)], axis=-1) * F32(0.3)
    q = p + warp
    h = noise.fbm(q * F32(1.8), 6) * 0.8 + (
        noise.ridged(q * F32(3.0), 4) - 0.5) * 0.5
    scale = max(dirs.shape[1] / 2048.0, 0.25)
    add_craters(dirs, h, rng, int(110 * scale + 30), 0.14, 0.25)
    h = normalize(h)
    tone = 0.5 + 0.5 * noise.fbm(q * F32(2.6) + 4, 5)
    base = ramp(tone, [(0.0, (0.36, 0.17, 0.09)), (0.5, (0.62, 0.34, 0.18)),
                       (1.0, (0.78, 0.52, 0.30))])
    basalt = smoothstep(0.58, 0.75, 0.5 + 0.5 * noise.fbm(
        q * F32(3.4) + 8, 4)) * smoothstep(0.1, -0.5, h)
    surface = lerp(base, color(0.13, 0.085, 0.075), (0.85 * basalt)[..., None])
    bands = 0.5 + 0.5 * noise.fbm(p * color(2.0, 9.0, 2.0) + 2, 4)
    surface = surface * (0.85 + 0.3 * bands[..., None])
    canyon = 1 - smoothstep(0.0, 0.035, np.abs(noise.fbm(
        q * color(1.6, 3.5, 1.6) + 14, 3))) * smoothstep(0.45, 0.1, lat)
    canyon = (1 - canyon) * smoothstep(0.45, 0.05, lat)
    surface = surface * (1 - 0.55 * canyon[..., None])
    cavity = np.clip(0.5 + 7.0 * (h - blur(h, max(3, int(9 * scale)))), 0, 1)
    surface = surface * (0.65 + 0.5 * cavity[..., None])
    detail = 0.5 + 0.5 * noise.fbm(p * F32(36.0) + 6, 4)
    surface = surface * (0.82 + 0.36 * detail[..., None])
    caps = smoothstep(0.86, 0.94, lat + 0.05 * noise.fbm(q * 3, 3))
    albedo = np.clip(lerp(surface, color(0.92, 0.9, 0.9), caps[..., None]),
                     0, 1)
    emission = np.zeros_like(albedo)
    return World(albedo, emission, h, -1.0, 0.020)


STYLES = {"lava": lava_world, "terran": terran_world, "desert": desert_world}


# ----------------------------------------------------------------- mesh
def sample_map(grid: Array, rings: int, segments: int) -> Array:
    """Bilinear samples of an equirectangular map at the mesh vertices.

    Wraps horizontally, so the first and last column (the texture seam)
    get exactly the same value, and every pole vertex gets the same value.
    """
    rows, cols = grid.shape
    xs = np.arange(segments + 1) / segments * cols - 0.5
    ys = np.arange(rings + 1) / rings * rows - 0.5
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    fx = (xs - x0).astype(F32)
    fy = (ys - y0).astype(F32)
    xa, xb = x0 % cols, (x0 + 1) % cols
    ya = np.clip(y0, 0, rows - 1)
    yb = np.clip(y0 + 1, 0, rows - 1)
    top = grid[ya][:, xa] * (1 - fx) + grid[ya][:, xb] * fx
    bottom = grid[yb][:, xa] * (1 - fx) + grid[yb][:, xb] * fx
    out = top * (1 - fy)[:, None] + bottom * fy[:, None]
    out[0, :] = out[0].mean()
    out[-1, :] = out[-1].mean()
    return np.asarray(out, dtype=F32)


def build_mesh(world: World, radius: float, rings: int, segments: int
               ) -> Tuple[Array, Array, Array, Array]:
    """Displaced UV sphere: positions, normals, uvs, triangle indices."""
    sampled = sample_map(world.height, rings, segments)
    sampled = np.maximum(sampled, F32(world.flat_level))
    lat = math.pi / 2 - np.arange(rings + 1, dtype=F32) / rings * math.pi
    lon = np.arange(segments + 1, dtype=F32) / segments * 2 * math.pi - math.pi
    lon_g, lat_g = np.meshgrid(lon, lat)
    dirs = np.stack([np.cos(lat_g) * np.cos(lon_g), np.sin(lat_g),
                     -np.cos(lat_g) * np.sin(lon_g)], axis=-1)
    amount = world.displace * (sampled - max(world.flat_level, -0.2))
    pos = dirs * (radius * (1.0 + amount))[..., None]
    uv = np.stack([(lon_g + math.pi) / (2 * math.pi),
                   (math.pi / 2 - lat_g) / math.pi], axis=-1)
    ids = np.arange((rings + 1) * (segments + 1)).reshape(rings + 1,
                                                          segments + 1)
    a = ids[:-1, :-1].ravel()
    b = ids[1:, :-1].ravel()
    c = ids[:-1, 1:].ravel()
    d = ids[1:, 1:].ravel()
    tris = np.concatenate([np.stack([a, b, c], 1), np.stack([c, b, d], 1)])
    flat_pos = pos.reshape(-1, 3).astype(F32)
    v0, v1, v2 = (flat_pos[tris[:, i]] for i in range(3))
    face_n = np.cross(v1 - v0, v2 - v0)
    centre = (v0 + v1 + v2) / 3
    if (np.einsum("ij,ij->i", face_n, centre) < 0).mean() > 0.5:
        tris = tris[:, [0, 2, 1]]
        face_n = -face_n
    normals = np.zeros_like(flat_pos)
    for i in range(3):
        np.add.at(normals, tris[:, i], face_n)
    # merge normals on the texture seam and at the poles
    normals = normals.reshape(rings + 1, segments + 1, 3)
    seam = normals[:, 0] + normals[:, -1]
    normals[:, 0] = seam
    normals[:, -1] = seam
    normals[0] = normals[0].sum(axis=0)
    normals[-1] = normals[-1].sum(axis=0)
    normals = normals.reshape(-1, 3)
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = (normals / np.maximum(length, 1e-9)).astype(F32)
    return (flat_pos, normals, uv.reshape(-1, 2).astype(F32),
            tris.astype(np.uint32))


# ------------------------------------------------------------------ GLB
def jpeg_bytes(img: Array, quality: int) -> bytes:
    """Encode a float [0,1] RGB image as JPEG."""
    pixels = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(buf, format="JPEG", quality=quality,
                                        subsampling=0)
    return buf.getvalue()


def write_glb(path: str, mesh: Tuple[Array, Array, Array, Array],
              albedo_jpg: bytes, emission_jpg: bytes) -> None:
    """Write the planet as a binary glTF with embedded textures."""
    pos, nor, uv, idx = mesh
    blob = bytearray()
    views: List[Dict[str, int]] = []
    accessors: List[Dict[str, object]] = []

    def add_view(data: bytes, target: int = 0) -> int:
        while len(blob) % 4:
            blob.append(0)
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            view["target"] = target
        blob.extend(data)
        views.append(view)
        return len(views) - 1

    def add_accessor(data: Array, comp: int, kind: str, target: int,
                     lo: object = None, hi: object = None) -> int:
        acc: Dict[str, object] = {
            "bufferView": add_view(data.tobytes(), target),
            "componentType": comp, "count": int(data.shape[0]), "type": kind}
        if lo is not None:
            acc["min"], acc["max"] = lo, hi
        accessors.append(acc)
        return len(accessors) - 1

    use_u16 = pos.shape[0] <= 65535
    index_data = idx.ravel().astype(np.uint16 if use_u16 else np.uint32)
    a_pos = add_accessor(pos, 5126, "VEC3", 34962,
                         pos.min(axis=0).tolist(), pos.max(axis=0).tolist())
    a_nor = add_accessor(nor, 5126, "VEC3", 34962)
    a_uv = add_accessor(uv, 5126, "VEC2", 34962)
    a_idx = add_accessor(index_data, 5123 if use_u16 else 5125, "SCALAR",
                         34963)
    accessors[a_idx]["count"] = int(index_data.shape[0])
    img_albedo = add_view(albedo_jpg)
    img_emission = add_view(emission_jpg)
    while len(blob) % 4:
        blob.append(0)
    doc = {
        "asset": {"version": "2.0", "generator": "make_planet_glb.py"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Planet", "mesh": 0}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": a_pos, "NORMAL": a_nor,
                           "TEXCOORD_0": a_uv},
            "indices": a_idx, "material": 0}]}],
        "materials": [{
            "name": "PlanetSurface",
            "pbrMetallicRoughness": {"baseColorTexture": {"index": 0},
                                     "metallicFactor": 0.0,
                                     "roughnessFactor": 1.0},
            "emissiveTexture": {"index": 1},
            "emissiveFactor": [1.0, 1.0, 1.0]}],
        "textures": [{"sampler": 0, "source": 0}, {"sampler": 0, "source": 1}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 10497, "wrapT": 33071}],
        "images": [{"bufferView": img_albedo, "mimeType": "image/jpeg"},
                   {"bufferView": img_emission, "mimeType": "image/jpeg"}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views, "accessors": accessors,
    }
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as out:
        out.write(struct.pack("<III", 0x46546C67, 2, total))
        out.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        out.write(struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


# ----------------------------------------------------------------- main
def generate(style: str, seed: int, width: int, mesh_segments: int,
             quality: int, out: str, preview: str = "") -> None:
    """Generate one planet and write it to ``out``."""
    started = time.time()
    height = width // 2
    dirs = sphere_directions(width, height)
    world = STYLES[style](dirs, seed)
    print(f"[{style}] maps in {time.time() - started:.1f}s")
    mesh = build_mesh(world, 2.0, mesh_segments // 2, mesh_segments)
    write_glb(out, mesh, jpeg_bytes(world.albedo, quality),
              jpeg_bytes(world.emission, quality))
    if preview:
        Image.fromarray((np.clip(world.albedo, 0, 1) * 255).astype(
            np.uint8)).save(f"{preview}_albedo.png")
        Image.fromarray((np.clip(world.emission, 0, 1) * 255).astype(
            np.uint8)).save(f"{preview}_emission.png")
    print(f"[{style}] wrote {out} ({mesh[0].shape[0]} vertices, "
          f"{time.time() - started:.1f}s total)")


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--style", choices=sorted(STYLES), default="lava")
    parser.add_argument("--seed", type=int, default=12)
    parser.add_argument("--size", type=int, default=2048,
                        help="texture width (height is half)")
    parser.add_argument("--mesh", type=int, default=256,
                        help="mesh segments around the equator (<= 360)")
    parser.add_argument("--quality", type=int, default=92,
                        help="JPEG quality of the embedded textures")
    parser.add_argument("--out", default="planet.glb")
    parser.add_argument("--preview", default="",
                        help="also save PNG previews with this prefix")
    args = parser.parse_args()
    generate(args.style, args.seed, args.size, args.mesh, args.quality,
             args.out, args.preview)


if __name__ == "__main__":
    main()
