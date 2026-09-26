from __future__ import annotations

import pathlib
import tempfile
import unittest

from PIL import Image

from mere_workflow_tools import image_graph_provider
from mere_workflow_tools.graph_sdk import validate_catalog


class ImageGraphProviderTests(unittest.TestCase):
    def test_catalog_exposes_four_portable_image_edits(self) -> None:
        catalog = image_graph_provider.graph_catalog("mere-image-compose", "0.4.0")
        validate_catalog(catalog)
        self.assertEqual({node["kind"] for node in catalog["nodes"]}, image_graph_provider.KINDS)

    def test_crop_mask_composite_and_inpaint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            source = root / "source.png"
            overlay = root / "overlay.png"
            mask = root / "mask.png"
            source_image = Image.new("RGBA", (5, 5), (100, 120, 140, 190))
            source_image.putpixel((2, 2), (0, 0, 0, 255))
            source_image.save(source)
            Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(overlay)
            mask_image = Image.new("L", (5, 5), 0)
            mask_image.putpixel((2, 2), 255)
            mask_image.save(mask)
            cases = [
                ("image.crop", {"source": str(source), "left": 1, "top": 1, "width": 2, "height": 3}),
                ("image.mask", {"source": str(source), "mask": str(mask)}),
                ("image.composite", {"base": str(source), "overlay": str(overlay), "left": 1, "top": 1}),
                ("image.inpaint", {"source": str(source), "mask": str(mask)}),
            ]
            for kind, arguments in cases:
                with self.subTest(kind=kind):
                    run_dir = root / kind.replace(".", "-")
                    run_dir.mkdir()
                    invocation = {"kind": kind, "arguments": arguments,
                                  "outputs": {"image": {"type": "asset", "path": "artifacts/finished.png"}}}
                    self.assertEqual(image_graph_provider.graph_preflight(invocation, run_dir)["status"], "ok")
                    events = []
                    image_graph_provider.graph_execute(invocation, run_dir, events.append)
                    self.assertEqual([event["type"] for event in events], ["artifact_ready", "metric", "node_result"])
                    with Image.open(run_dir / "artifacts/finished.png") as result:
                        if kind == "image.crop":
                            self.assertEqual(result.size, (2, 3))
                        elif kind == "image.mask":
                            self.assertEqual(result.getpixel((2, 2))[3], 255)
                            self.assertEqual(result.getpixel((0, 0))[3], 0)
                        elif kind == "image.composite":
                            self.assertEqual(result.getpixel((1, 1))[:3], (255, 0, 0))
                        else:
                            self.assertEqual(result.getpixel((2, 2))[:3], (100, 120, 140))
                            self.assertEqual(result.getpixel((0, 0)), (100, 120, 140, 190))

    def test_rejects_out_of_bounds_crop_and_mismatched_mask(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            source = root / "source.png"
            mask = root / "mask.png"
            Image.new("RGB", (4, 4)).save(source)
            Image.new("L", (2, 2)).save(mask)
            output = {"image": {"type": "asset", "path": "output.png"}}
            crop = {"kind": "image.crop", "arguments": {"source": str(source), "left": 3, "top": 0,
                                                       "width": 2, "height": 2}, "outputs": output}
            with self.assertRaisesRegex(Exception, "crop rectangle exceeds"):
                image_graph_provider.graph_execute(crop, root, lambda _event: None)
            masked = {"kind": "image.mask", "arguments": {"source": str(source), "mask": str(mask)},
                      "outputs": output}
            with self.assertRaisesRegex(Exception, "mask dimensions"):
                image_graph_provider.graph_execute(masked, root, lambda _event: None)


if __name__ == "__main__":
    unittest.main()
