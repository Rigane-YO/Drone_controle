"""Lighting shader for the planet models (sun light, glow map, rim light).

raylib's default shader is unlit, so a textured sphere looks flat. This
shader adds what makes a planet look like a planet:

* a sun with a soft day/night terminator (the light follows the camera,
  so the planets always show their relief),
* the emission texture (lava, city lights) which stays visible at night,
* a coloured glow on the edge of the globe (atmosphere).

The planet GLB files made by ``make_planet_glb.py`` carry the colour in
the base-colour texture and the glow in the emissive texture. Old GLB files
that store their colours in the vertices still work: the vertex colour is
multiplied with the texture (white when the file has none).
"""
import math
from typing import Any, List, Optional, Sequence, Tuple

import pyray as pr
from pyray import (MaterialMapIndex, ShaderLocationIndex,
                   ShaderUniformDataType, TextureFilter)

Vec3 = List[float]

VERTEX_SHADER = """#version 330
in vec3 vertexPosition;
in vec2 vertexTexCoord;
in vec3 vertexNormal;
in vec4 vertexColor;
uniform mat4 mvp;
uniform mat4 matModel;
uniform mat4 matNormal;
out vec3 fragPosition;
out vec2 fragTexCoord;
out vec3 fragNormal;
out vec4 fragColor;
void main()
{
    fragColor = vertexColor;
    fragPosition = vec3(matModel * vec4(vertexPosition, 1.0));
    fragTexCoord = vertexTexCoord;
    fragNormal = normalize(vec3(matNormal * vec4(vertexNormal, 1.0)));
    gl_Position = mvp * vec4(vertexPosition, 1.0);
}
"""

FRAGMENT_SHADER = """#version 330
in vec3 fragPosition;
in vec2 fragTexCoord;
in vec3 fragNormal;
in vec4 fragColor;
uniform sampler2D texture0;
uniform sampler2D emissionMap;
uniform vec4 colDiffuse;
uniform vec3 viewPos;
uniform vec3 lightDir;
uniform vec3 atmoColor;
uniform int hasEmission;
out vec4 finalColor;

vec3 toLinear(vec3 c) { return pow(c, vec3(2.2)); }

void main()
{
    vec3 albedo = toLinear(texture(texture0, fragTexCoord).rgb
                           * fragColor.rgb) * colDiffuse.rgb;
    vec3 n = normalize(fragNormal);
    vec3 v = normalize(viewPos - fragPosition);
    float ndl = dot(n, -lightDir);
    float day = smoothstep(-0.12, 0.40, ndl);
    float diffuse = max(ndl, 0.0);
    vec3 color = albedo * (vec3(0.030, 0.034, 0.050)
                           + 1.45 * diffuse * vec3(1.0, 0.97, 0.92));
    if (hasEmission == 1)
    {
        vec3 glow = toLinear(texture(emissionMap, fragTexCoord).rgb);
        color += glow * (2.9 - 1.5 * day);
    }
    float rim = pow(1.0 - max(dot(n, v), 0.0), 4.0);
    color += atmoColor * rim * (0.10 + 0.90 * day) * 0.40;
    color = 1.0 - exp(-color * 1.25);
    finalColor = vec4(pow(color, vec3(1.0 / 2.2)), 1.0);
}
"""

ATMOSPHERES: Tuple[Tuple[float, float, float], ...] = (
    (1.00, 0.36, 0.12),   # lava: hot orange haze
    (0.35, 0.62, 1.00),   # terran: blue sky
    (0.95, 0.60, 0.38),   # desert: dusty rose
)


def _normalize(vec: Sequence[float]) -> Vec3:
    norm = math.sqrt(sum(c * c for c in vec)) or 1.0
    return [c / norm for c in vec]


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


class PlanetShader:
    """Owns the planet shader and applies it to loaded models."""

    def __init__(self) -> None:
        """Compile the shader; raises RuntimeError if it is unusable."""
        self.shader = pr.load_shader_from_memory(VERTEX_SHADER,
                                                 FRAGMENT_SHADER)
        if not pr.is_shader_valid(self.shader):
            raise RuntimeError("planet shader failed to compile")
        self.shader.locs[ShaderLocationIndex.SHADER_LOC_MAP_EMISSION] = (
            pr.get_shader_location(self.shader, "emissionMap"))
        self._loc = {name: pr.get_shader_location(self.shader, name)
                     for name in ("viewPos", "lightDir", "atmoColor",
                                  "hasEmission")}
        self._has_emission = True
        self._saved: List[Tuple[Any, Any]] = []
        self.set_atmosphere(ATMOSPHERES[0])

    @classmethod
    def create(cls) -> Optional["PlanetShader"]:
        """Build the shader, or None (with a message) if it cannot run."""
        try:
            return cls()
        except Exception as error:
            print(f"⚠ Shader de planète indisponible : {error}")
            return None

    def apply(self, model: Any) -> bool:
        """Use the shader on every material of ``model``.

        Also builds mipmaps (smooth when the planet is small). Returns
        True when the model has an emission texture.
        """
        has_emission = False
        has_albedo = False
        default_id = pr.rl_get_texture_id_default()
        for index in range(model.materialCount):
            material = model.materials[index]
            self._saved.append((material, pr.ffi.new("Shader *",
                                                     material.shader)))
            material.shader = self.shader
            for map_index in (MaterialMapIndex.MATERIAL_MAP_ALBEDO,
                              MaterialMapIndex.MATERIAL_MAP_EMISSION):
                tex_map = material.maps[map_index]
                if tex_map.texture.id in (0, default_id):
                    continue            # raylib's own default material
                pr.gen_texture_mipmaps(pr.ffi.addressof(tex_map, "texture"))
                pr.set_texture_filter(
                    tex_map.texture, TextureFilter.TEXTURE_FILTER_TRILINEAR)
            albedo = material.maps[MaterialMapIndex.MATERIAL_MAP_ALBEDO]
            has_albedo = has_albedo or (
                albedo.texture.id not in (0, default_id))
            emission = material.maps[MaterialMapIndex.MATERIAL_MAP_EMISSION]
            has_emission = has_emission or (
                emission.texture.id not in (0, default_id))
        if not has_albedo:
            print("ℹ Planète sans texture de couleur (ancien planet.glb ?) : "
                  "couleurs de sommets utilisées. Régénérez-la avec "
                  "make_planet_glb.py pour le nouveau rendu.")
        self._has_emission = has_emission
        self._set_int("hasEmission", 1 if has_emission else 0)
        return has_emission

    def set_atmosphere(self, rgb: Sequence[float]) -> None:
        """Colour of the glow around the globe."""
        self._set_vec3("atmoColor", rgb)

    def update(self, eye: Sequence[float], target: Sequence[float]) -> None:
        """Per frame: camera position and a light that follows the view."""
        forward = _normalize([target[i] - eye[i] for i in range(3)])
        right = _normalize(_cross(forward, [0.0, 1.0, 0.0]))
        up = _cross(right, forward)
        light = _normalize([0.80 * forward[i] + 0.55 * right[i]
                            - 0.45 * up[i] for i in range(3)])
        self._set_vec3("viewPos", eye)
        self._set_vec3("lightDir", light)

    def unload(self) -> None:
        """Give the models their old shader back, then free ours.

        Call this BEFORE unloading the models, so raylib does not free
        the shared shader a second time.
        """
        for material, original in self._saved:
            material.shader = original[0]
        self._saved = []
        pr.unload_shader(self.shader)

    def _set_vec3(self, name: str, value: Sequence[float]) -> None:
        pr.set_shader_value(self.shader, self._loc[name],
                            pr.ffi.new("float[3]", [float(c) for c in value]),
                            ShaderUniformDataType.SHADER_UNIFORM_VEC3)

    def _set_int(self, name: str, value: int) -> None:
        pr.set_shader_value(self.shader, self._loc[name],
                            pr.ffi.new("int *", value),
                            ShaderUniformDataType.SHADER_UNIFORM_INT)