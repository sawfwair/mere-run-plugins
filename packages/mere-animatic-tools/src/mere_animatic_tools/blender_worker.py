from __future__ import annotations

import json
import math
import pathlib
import re
import sys

import bpy

JsonMap = dict[str, object]
Vector3 = tuple[float, float, float]


def mapping(value: object) -> JsonMap:
    return value if isinstance(value, dict) else {}


def items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def vector(value: object, fallback: Vector3 = (0.0, 0.0, 0.0)) -> Vector3:
    if not isinstance(value, list):
        return fallback
    return tuple(
        float(value[index]) if index < len(value) else fallback[index]
        for index in range(3)
    )


def safe_name(value: object, fallback: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(value or fallback)).strip("-")[:80] or fallback


def add_material(obj: object, color: object) -> None:
    rgb = vector(color, (0.5, 0.5, 0.5))
    material = bpy.data.materials.new(name=f"{obj.name}_Material")
    material.diffuse_color = (*rgb, 1.0)
    obj.data.materials.append(material)


def add_box(item: JsonMap, index: int) -> None:
    center = vector(item.get("center"))
    size = vector(item.get("size"), (1.0, 1.0, 1.0))
    bpy.ops.mesh.primitive_cube_add(location=center)
    obj = bpy.context.object
    obj.name = safe_name(item.get("name"), f"Box_{index + 1}")
    obj.scale = tuple(component / 2.0 for component in size)
    obj["animatic_role"] = str(item.get("role") or "set_piece")
    add_material(obj, item.get("displayColor") or [0.5, 0.5, 0.5])


def add_mesh(item: JsonMap, index: int) -> None:
    points = [vector(value) for value in items(item.get("points"))]
    counts = [max(3, int(value)) for value in items(item.get("faceVertexCounts"))]
    indices = [max(0, int(value)) for value in items(item.get("faceVertexIndices"))]
    faces: list[list[int]] = []
    offset = 0
    for count in counts:
        face = indices[offset:offset + count]
        offset += count
        if len(face) == count and all(vertex < len(points) for vertex in face):
            faces.append(face)
    if not points or not faces:
        raise ValueError(f"Mesh {item.get('name') or index + 1} has no valid geometry")
    name = safe_name(item.get("name"), f"Mesh_{index + 1}")
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(points, [], faces)
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    bpy.context.collection.objects.link(obj)
    obj["animatic_role"] = str(item.get("role") or "set_piece")
    add_material(obj, item.get("displayColor") or [0.5, 0.5, 0.5])


def add_camera(item: JsonMap, index: int) -> object:
    camera_data = bpy.data.cameras.new(safe_name(item.get("name"), f"Camera_{index + 1}"))
    camera_data.lens = float(item.get("focalLength") or 35.0)
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    bpy.context.collection.objects.link(camera)
    transform = mapping(item.get("transform"))
    camera.location = vector(transform.get("translate"), (0.0, -8.0, 3.0))
    pitch = math.radians(float(transform.get("rotate_x_degrees") or 68.0))
    yaw = math.radians(float(transform.get("rotate_y_degrees") or 0.0))
    roll = math.radians(float(transform.get("rotate_z_degrees") or 0.0))
    camera.rotation_euler = (pitch, roll, yaw)
    camera["animatic_label"] = str(item.get("label") or camera.name)
    return camera


def add_light(item: JsonMap, index: int) -> None:
    kind = "SUN" if str(item.get("type") or "sun").lower() in {"sun", "distant"} else "AREA"
    light_data = bpy.data.lights.new(safe_name(item.get("name"), f"Light_{index + 1}"), type=kind)
    light_data.energy = float(item.get("intensity") or (3.0 if kind == "SUN" else 800.0))
    light_data.color = vector(item.get("color"), (1.0, 0.96, 0.88))
    light = bpy.data.objects.new(light_data.name, light_data)
    bpy.context.collection.objects.link(light)
    transform = mapping(item.get("transform"))
    light.location = vector(transform.get("translate") or item.get("position"), (4.0, -4.0, 6.0))
    light.rotation_euler = (math.radians(35.0), 0.0, math.radians(float(transform.get("rotate_y_degrees") or -35.0)))


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    spec_path, output_value, action = args
    output_dir = pathlib.Path(output_value)
    spec = json.loads(pathlib.Path(spec_path).read_text())
    geometry = mapping(spec.get("geometry"))
    boxes = items(spec.get("boxes") or geometry.get("boxes"))
    meshes = items(spec.get("meshes") or geometry.get("meshes"))
    staging_zones = items(spec.get("stagingZones"))
    mask_regions = items(spec.get("maskRegions") or geometry.get("maskRegions") or geometry.get("mask_regions"))
    cameras = items(spec.get("cameraAnchors"))
    lights = items(spec.get("lightingRigs"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Animatic World")
    scene.world.color = (0.035, 0.04, 0.05)
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    settings = mapping(spec.get("renderSettings"))
    scene.render.resolution_x = int(settings.get("width") or 1280)
    scene.render.resolution_y = int(settings.get("height") or 720)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    for index, item in enumerate(meshes):
        add_mesh(mapping(item), index)
    for index, item in enumerate(boxes):
        add_box(mapping(item), index)
    for index, item in enumerate(staging_zones):
        zone = mapping(item)
        add_box({
            **zone,
            "name": zone.get("name") or zone.get("label") or f"StagingZone_{index + 1}",
            "role": "staging_zone",
            "center": zone.get("center") or [0, 0.05, 0],
            "size": zone.get("size") or [1, 0.05, 1],
            "displayColor": zone.get("displayColor") or [0.25, 0.48, 0.82],
        }, len(boxes) + index)
    for index, item in enumerate(mask_regions):
        region = mapping(item)
        add_box({
            **region,
            "name": region.get("name") or region.get("label") or f"MaskRegion_{index + 1}",
            "role": "mask_region",
            "center": region.get("center") or [0, 0.05, 0],
            "size": region.get("size") or [1, 0.05, 1],
            "displayColor": region.get("displayColor") or [0.7, 0.38, 0.2],
        }, len(boxes) + len(staging_zones) + index)
    if not meshes and not boxes:
        add_box({"name": "Floor", "role": "floor", "center": [0, 0, -0.05], "size": [10, 10, 0.1]}, 0)

    camera_objects = [add_camera(mapping(item), index) for index, item in enumerate(cameras)]
    if not camera_objects:
        camera_objects.append(add_camera({"name": "Master", "transform": {"translate": [0, -8, 3]}}, 0))
    if lights:
        for index, item in enumerate(lights):
            add_light(mapping(item), index)
    else:
        add_light({"name": "Key", "type": "sun", "intensity": 3.0}, 0)

    scene.camera = camera_objects[0]
    blend_path = output_dir / "proxy.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    if action == "solve-lighting":
        (output_dir / "lighting-solve.json").write_text(json.dumps({
            "schema": "animatic.set_proxy.lighting.v1",
            "camera_count": len(camera_objects),
            "light_count": len(bpy.data.lights),
            "scene": blend_path.name,
        }, indent=2, sort_keys=True) + "\n")
    elif action == "render-plates":
        plates = output_dir / "plates"
        plates.mkdir(parents=True, exist_ok=True)
        for index, camera in enumerate(camera_objects):
            scene.camera = camera
            scene.render.filepath = str(plates / f"{index + 1:02d}-{safe_name(camera.name, 'camera')}.png")
            bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
