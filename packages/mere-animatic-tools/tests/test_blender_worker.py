from __future__ import annotations

import importlib
import json
import pathlib
import sys
import tempfile
import types
import unittest
from collections.abc import Callable
from unittest import mock


class FakeMaterialList(list[object]):
    pass


class FakeMesh:
    def __init__(self, name: str) -> None:
        self.name = name
        self.materials = FakeMaterialList()
        self.points: list[tuple[float, float, float]] = []
        self.faces: list[list[int]] = []

    def from_pydata(
        self,
        points: list[tuple[float, float, float]],
        _edges: list[object],
        faces: list[list[int]],
    ) -> None:
        self.points = points
        self.faces = faces

    def update(self) -> None:
        return None


class FakeObject:
    def __init__(self, name: str, data: object | None = None) -> None:
        self.name = name
        self.data = data if data is not None else FakeMesh(name)
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.properties: dict[str, object] = {}

    def __setitem__(self, key: str, value: object) -> None:
        self.properties[key] = value


class FakeNamedCollection:
    def __init__(self, factory: Callable[..., object]) -> None:
        self.factory = factory
        self.values: list[object] = []

    def new(self, name: str, *args: object, **kwargs: object) -> object:
        value = self.factory(name, *args, **kwargs)
        self.values.append(value)
        return value

    def __len__(self) -> int:
        return len(self.values)


class FakeLinkedObjects:
    def __init__(self) -> None:
        self.values: list[object] = []

    def link(self, value: object) -> None:
        self.values.append(value)


def namespace(**values: object) -> types.SimpleNamespace:
    return types.SimpleNamespace(**values)


def fake_bpy() -> types.ModuleType:
    module = types.ModuleType("bpy")
    linked = FakeLinkedObjects()
    render = namespace(
        engine="",
        resolution_x=0,
        resolution_y=0,
        resolution_percentage=0,
        filepath="",
        image_settings=namespace(file_format=""),
    )
    scene = namespace(world=None, render=render, camera=None)
    context = namespace(scene=scene, object=None, collection=namespace(objects=linked))

    def material_factory(name: str) -> types.SimpleNamespace:
        return namespace(name=name, diffuse_color=())

    def camera_factory(name: str) -> types.SimpleNamespace:
        return namespace(name=name, lens=0.0)

    def light_factory(name: str, **values: object) -> types.SimpleNamespace:
        return namespace(name=name, energy=0.0, color=(), **values)

    meshes = FakeNamedCollection(FakeMesh)
    objects = FakeNamedCollection(FakeObject)
    materials = FakeNamedCollection(material_factory)
    cameras = FakeNamedCollection(camera_factory)
    lights = FakeNamedCollection(light_factory)
    worlds = FakeNamedCollection(lambda name: namespace(name=name, color=()))
    data = namespace(
        meshes=meshes,
        objects=objects,
        materials=materials,
        cameras=cameras,
        lights=lights,
        worlds=worlds,
    )

    def primitive_cube_add(*, location: tuple[float, float, float]) -> None:
        context.object = FakeObject("Cube")
        context.object.location = location

    def save_as_mainfile(*, filepath: str) -> None:
        pathlib.Path(filepath).write_bytes(b"fake blend")

    def render_still(*, write_still: bool) -> None:
        if write_still:
            pathlib.Path(render.filepath).write_bytes(b"fake png")

    module.context = context
    module.data = data
    module.ops = namespace(
        mesh=namespace(primitive_cube_add=primitive_cube_add),
        wm=namespace(read_factory_settings=lambda **_values: None, save_as_mainfile=save_as_mainfile),
        render=namespace(render=render_still),
    )
    return module


class BlenderWorkerTests(unittest.TestCase):
    def load_worker(self) -> types.ModuleType:
        sys.modules.pop("mere_animatic_tools.blender_worker", None)
        with mock.patch.dict(sys.modules, {"bpy": fake_bpy()}):
            return importlib.import_module("mere_animatic_tools.blender_worker")

    def test_helpers_reject_malformed_values(self) -> None:
        worker = self.load_worker()
        self.assertEqual(worker.mapping([]), {})
        self.assertEqual(worker.items({}), [])
        self.assertEqual(worker.vector("bad", (1.0, 2.0, 3.0)), (1.0, 2.0, 3.0))
        self.assertEqual(worker.vector([4]), (4.0, 0.0, 0.0))
        self.assertEqual(worker.safe_name("A bad/name", "fallback"), "A-bad-name")
        with self.assertRaises(ValueError):
            worker.float_value(object())
        with self.assertRaises(ValueError):
            worker.int_value(object())
        with self.assertRaisesRegex(ValueError, "no valid geometry"):
            worker.add_mesh({"name": "empty"}, 0)

    def test_main_builds_scene_and_lighting_receipt(self) -> None:
        worker = self.load_worker()
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            spec = root / "spec.json"
            spec.write_text(
                json.dumps(
                    {
                        "meshes": [
                            {
                                "name": "Floor Mesh",
                                "role": "floor",
                                "points": [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                                "faceVertexCounts": [4],
                                "faceVertexIndices": [0, 1, 2, 3],
                            }
                        ],
                        "boxes": [{"name": "Wall", "center": [0, 1, 1], "size": [4, 0.2, 2]}],
                        "stagingZones": [{"label": "Blocking"}],
                        "maskRegions": [{"label": "Holdout"}],
                        "cameraAnchors": [{"name": "Master", "focalLength": "50"}],
                        "lightingRigs": [{"name": "Key", "type": "area", "intensity": 400}],
                        "renderSettings": {"width": 640, "height": 360},
                    }
                )
            )
            with mock.patch.object(sys, "argv", ["blender", "--", str(spec), str(root), "solve-lighting"]):
                worker.main()
            self.assertTrue((root / "proxy.blend").is_file())
            receipt = json.loads((root / "lighting-solve.json").read_text())
            self.assertEqual(receipt["camera_count"], 1)
            self.assertEqual(receipt["light_count"], 1)

    def test_main_renders_default_camera_plate(self) -> None:
        worker = self.load_worker()
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            spec = root / "spec.json"
            spec.write_text("{}")
            with mock.patch.object(sys, "argv", ["blender", "--", str(spec), str(root), "render-plates"]):
                worker.main()
            self.assertTrue((root / "proxy.blend").is_file())
            self.assertEqual(len(list((root / "plates").glob("*.png"))), 1)


if __name__ == "__main__":
    unittest.main()
