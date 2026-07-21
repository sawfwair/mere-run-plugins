from __future__ import annotations

import json
import math
import os
import pathlib
import re
import shutil
import subprocess
from typing import cast

JsonMap = dict[str, object]


class SetProxyError(RuntimeError):
    pass


def _mapping(value: object) -> JsonMap:
    return cast(JsonMap, value) if isinstance(value, dict) else {}


def _items(value: object) -> list[JsonMap]:
    return [cast(JsonMap, item) for item in value] if isinstance(value, list) else []


def _values(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _number(value: object, fallback: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return fallback


def _vector(value: object, size: int = 3, fallback: float = 0.0) -> list[float]:
    raw = value if isinstance(value, list) else []
    return [_number(raw[index], fallback) if index < len(raw) else fallback for index in range(size)]


def _usd_string(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _usd_tuple(value: object, size: int = 3) -> str:
    return "(" + ", ".join(f"{item:.6g}" for item in _vector(value, size)) + ")"


def _safe_name(value: object, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(value or fallback)).strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned[:96]


def _matrix(transform_value: object) -> str:
    transform = _mapping(transform_value)
    translate = _vector(transform.get("translate"))
    yaw = math.radians(_number(transform.get("rotate_y_degrees")))
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    rows = [
        (cosine, 0.0, -sine, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (sine, 0.0, cosine, 0.0),
        (translate[0], translate[1], translate[2], 1.0),
    ]
    return "(" + ", ".join("(" + ", ".join(f"{item:.6g}" for item in row) + ")" for row in rows) + ")"


def _mesh_prim(item: JsonMap, fallback: str) -> str:
    name = _safe_name(item.get("name"), fallback)
    points = ", ".join(_usd_tuple(point) for point in _values(item.get("points")))
    counts = ", ".join(
        str(max(3, int(_number(value, 4))))
        for value in _values(item.get("faceVertexCounts"))
    )
    indices = ", ".join(
        str(max(0, int(_number(value))))
        for value in _values(item.get("faceVertexIndices"))
    )
    color = _usd_tuple(item.get("displayColor") or [0.5, 0.5, 0.5])
    role = _usd_string(item.get("role") or "set_piece")
    return f'''        def Mesh "{name}" (
            customData = {{ string animatic_role = "{role}" }}
        )
        {{
            uniform token subdivisionScheme = "none"
            point3f[] points = [{points}]
            int[] faceVertexCounts = [{counts}]
            int[] faceVertexIndices = [{indices}]
            color3f[] primvars:displayColor = [{color}]
            uniform token primvars:displayColor:interpolation = "constant"
        }}'''


def _box_prim(item: JsonMap, index: int) -> str:
    center = _vector(item.get("center"))
    size = _vector(item.get("size"), fallback=1.0)
    half = [component / 2.0 for component in size]
    cx, cy, cz = center
    sx, sy, sz = half
    points = [
        [cx - sx, cy - sy, cz - sz], [cx + sx, cy - sy, cz - sz],
        [cx + sx, cy - sy, cz + sz], [cx - sx, cy - sy, cz + sz],
        [cx - sx, cy + sy, cz - sz], [cx + sx, cy + sy, cz - sz],
        [cx + sx, cy + sy, cz + sz], [cx - sx, cy + sy, cz + sz],
    ]
    return _mesh_prim({
        "name": item.get("name") or f"Box_{index + 1}",
        "role": item.get("role") or "set_piece",
        "points": points,
        "faceVertexCounts": [4, 4, 4, 4, 4, 4],
        "faceVertexIndices": [0, 1, 2, 3, 4, 7, 6, 5, 0, 4, 5, 1, 1, 5, 6, 2, 2, 6, 7, 3, 3, 7, 4, 0],
        "displayColor": item.get("displayColor") or [0.5, 0.5, 0.5],
    }, f"Box_{index + 1}")


def _camera_prim(item: JsonMap, index: int) -> str:
    name = _safe_name(item.get("name") or item.get("label"), f"Camera_{index + 1}")
    return f'''        def Camera "{name}" (
            customData = {{
                string animatic_label = "{_usd_string(item.get('label') or name)}"
                string animatic_notes = "{_usd_string(item.get('notes'))}"
            }}
        )
        {{
            float focalLength = {_number(item.get('focalLength'), 35):.6g}
            float horizontalAperture = {_number(item.get('horizontalAperture'), 20.955):.6g}
            matrix4d xformOp:transform = {_matrix(item.get('transform'))}
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }}'''


def _marker_prim(item: JsonMap, index: int, role: str, color: list[float]) -> str:
    return _box_prim({
        "name": item.get("name") or item.get("label") or f"{role}_{index + 1}",
        "role": role,
        "center": item.get("center") or [0, 0.05, 0],
        "size": item.get("size") or [1, 0.05, 1],
        "displayColor": item.get("displayColor") or color,
    }, index)


def _light_prim(item: JsonMap, index: int) -> str:
    name = _safe_name(item.get("name") or item.get("label"), f"LightingRig_{index + 1}")
    transform = item.get("transform") or {"translate": item.get("position") or [0, 4, 0]}
    return f'''        def DistantLight "{name}" (
            customData = {{
                string animatic_label = "{_usd_string(item.get('label') or name)}"
                string animatic_notes = "{_usd_string(item.get('notes'))}"
            }}
        )
        {{
            color3f inputs:color = {_usd_tuple(item.get('color') or [1, 0.96, 0.88])}
            float inputs:intensity = {_number(item.get('intensity'), 600):.6g}
            float inputs:angle = {_number(item.get('angle'), 5):.6g}
            matrix4d xformOp:transform = {_matrix(transform)}
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }}'''


def build_usda(spec: JsonMap) -> str:
    geometry = _mapping(spec.get("geometry"))
    boxes = _items(spec.get("boxes") or geometry.get("boxes"))
    meshes = _items(spec.get("meshes") or geometry.get("meshes"))
    cameras = _items(spec.get("cameraAnchors"))
    zones = _items(spec.get("stagingZones"))
    masks = _items(spec.get("maskRegions") or geometry.get("maskRegions") or geometry.get("mask_regions"))
    lights = _items(spec.get("lightingRigs"))
    sections = [
        ('Geometry', [_mesh_prim(item, f"Mesh_{index + 1}") for index, item in enumerate(meshes)] + [_box_prim(item, index) for index, item in enumerate(boxes)]),
        ('Cameras', [_camera_prim(item, index) for index, item in enumerate(cameras)]),
        ('StagingZones', [_marker_prim(item, index, "staging_zone", [0.25, 0.48, 0.82]) for index, item in enumerate(zones)]),
        ('MaskRegions', [_marker_prim(item, index, "mask_region", [0.7, 0.38, 0.2]) for index, item in enumerate(masks)]),
        ('LightingRigs', [_light_prim(item, index) for index, item in enumerate(lights)]),
    ]
    prims = "\n\n".join(f'    def Xform "{name}"\n    {{\n' + "\n\n".join(items) + "\n    }" for name, items in sections)
    return f'''#usda 1.0
(
    defaultPrim = "SetProxy"
    metersPerUnit = 1
    upAxis = "Y"
)

def Xform "SetProxy" (
    customData = {{
        string animatic_id = "{_usd_string(spec.get('id'))}"
        string animatic_name = "{_usd_string(spec.get('name') or 'Set Proxy')}"
        string animatic_location_id = "{_usd_string(spec.get('locationId'))}"
        string animatic_proxy_type = "{_usd_string(spec.get('proxyType') or 'spatial')}"
        string animatic_summary = "{_usd_string(spec.get('summary'))}"
    }}
)
{{
{prims}
}}
'''


def blender_binary() -> pathlib.Path | None:
    configured = os.environ.get("BLENDER_BIN", "").strip()
    discovered = shutil.which("blender")
    candidates = [
        pathlib.Path(configured) if configured else None,
        pathlib.Path(discovered) if discovered else None,
        pathlib.Path("/Applications/Blender.app/Contents/MacOS/Blender"),
    ]
    return next((candidate for candidate in candidates if candidate and candidate.is_file()), None)


def create_bundle(spec: JsonMap, output_dir: pathlib.Path, blender_action: str | None = None) -> list[pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = output_dir / "proxy.usda"
    bundle_path = output_dir / "set-proxy-manifest.json"
    readme_path = output_dir / "SET-PROXY.md"
    proxy_path.write_text(build_usda(spec))
    bundle = {
        "schema": "animatic.set_proxy.bundle",
        "version": 2,
        "id": str(spec.get("id") or ""),
        "name": str(spec.get("name") or ""),
        "location_id": str(spec.get("locationId") or ""),
        "proxy_type": str(spec.get("proxyType") or "spatial"),
        "summary": str(spec.get("summary") or ""),
        "camera_anchors": _items(spec.get("cameraAnchors")),
        "staging_zones": _items(spec.get("stagingZones")),
        "lighting_rigs": _items(spec.get("lightingRigs")),
        "mask_regions": _items(spec.get("maskRegions")),
        "files": ["proxy.usda", "set-proxy-manifest.json", "SET-PROXY.md"],
    }
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    readme_path.write_text(
        f"# {spec.get('name') or 'Set Proxy'}\n\n{spec.get('summary') or ''}\n\n"
        "This is a USD-first Animatic set-proxy bundle. proxy.usda is the canonical "
        "geometry, camera, staging, mask, and lighting interchange artifact.\n"
    )
    artifacts = [proxy_path, bundle_path, readme_path]

    if blender_action:
        blender = blender_binary()
        if not blender:
            raise SetProxyError("Blender is required for this action but was not found; set BLENDER_BIN or install Blender.app")
        spec_path = output_dir / "set-proxy-spec.json"
        spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
        worker = pathlib.Path(__file__).with_name("blender_worker.py")
        process = subprocess.run(
            [str(blender), "--background", "--python", str(worker), "--", str(spec_path), str(output_dir), blender_action],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            detail = process.stderr.strip().splitlines()[-1:] or process.stdout.strip().splitlines()[-1:]
            raise SetProxyError("Blender set-proxy action failed: " + (detail[0] if detail else f"exit {process.returncode}"))
        blend_path = output_dir / "proxy.blend"
        if not blend_path.is_file():
            detail = process.stderr.strip().splitlines()[-1:] or process.stdout.strip().splitlines()[-3:]
            raise SetProxyError("Blender completed without proxy.blend: " + " | ".join(detail))
        artifacts.append(blend_path)
        if blender_action == "solve-lighting":
            solve_path = output_dir / "lighting-solve.json"
            if not solve_path.is_file():
                raise SetProxyError("Blender completed without lighting-solve.json")
            artifacts.append(solve_path)
        if blender_action == "render-plates":
            plate_paths = sorted((output_dir / "plates").glob("*.png"))
            if not plate_paths:
                raise SetProxyError("Blender completed without camera plates")
            artifacts.extend(plate_paths)
    return artifacts
