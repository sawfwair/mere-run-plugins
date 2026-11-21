from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from PIL import Image, PngImagePlugin

from mere_workflow_tools import cli, media_redaction


class MediaRedactionTests(unittest.TestCase):
    def test_approved_rectangles_export_oriented_opaque_png_without_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            image = Image.new("RGBA", (8, 5), (230, 75, 20, 255))
            image.putpixel((0, 0), (255, 0, 0, 0))
            exif = image.getexif()
            exif[274] = 6
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("Description", "sensitive description")
            image.save(source, exif=exif, pnginfo=metadata)
            original = source.read_bytes()
            review_dir = root / "review"
            with redirect_stdout(StringIO()):
                result = cli.main_for("media", [
                    "redaction-review", "--input", str(source), "--output-dir", str(review_dir),
                ])
            self.assertEqual(result, 0)
            self.assertTrue((review_dir / "review.html").is_file())
            with Image.open(review_dir / "previews/000001.png") as preview:
                self.assertEqual(preview.size, (5, 8))
                self.assertEqual(preview.getpixel((4, 0)), (255, 255, 255))

            _image, identity = media_redaction.read_frame(source)
            review = root / "approved.json"
            state = {**identity, "approved": True, "rectangles": [[1, 2, 4, 7]]}
            review.write_text(json.dumps({"schema": media_redaction.REVIEW_SCHEMA, "frames": [state]}))
            output = root / "export"
            with redirect_stdout(StringIO()):
                result = cli.main_for("media", [
                    "redact-export", "--input", str(source), "--review", str(review), "--output-dir", str(output),
                ])
            self.assertEqual(result, 0)
            receipt = json.loads((output / "export.json").read_text())
            self.assertEqual(receipt["frames"][0]["source"], identity)
            self.assertEqual(source.read_bytes(), original)
            with Image.open(output / "000001.png") as published:
                self.assertEqual(published.info, {})
                self.assertEqual(published.size, (5, 8))
                self.assertEqual(published.getpixel((1, 2)), (0, 0, 0))
                self.assertEqual(published.getpixel((3, 6)), (0, 0, 0))
                self.assertEqual(published.getpixel((4, 7)), (230, 75, 20))
                self.assertEqual(published.getpixel((4, 0)), (255, 255, 255))

    def test_export_refuses_incomplete_modified_or_invalid_review_as_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / "frames"
            sources.mkdir()
            frames = []
            for name in ("01.png", "02.png"):
                path = sources / name
                Image.new("RGB", (8, 5), "red").save(path)
                frames.append({**media_redaction.read_frame(path)[1], "approved": True, "rectangles": []})
            with self.assertRaisesRegex(ValueError, "outside the source folder"):
                media_redaction.create_review(list(sources.iterdir()), sources, sources / "review")
            review = root / "approved.json"
            output = root / "export"
            for change, diagnostic in (
                ({"approved": False}, "has not been approved"),
                ({"rectangles": [[0, 0, 9, 5]]}, "outside the image"),
                ({"sha256": "wrong"}, "Source image changed"),
            ):
                with self.subTest(change=change), redirect_stderr(StringIO()) as stderr:
                    review.write_text(json.dumps({
                        "schema": media_redaction.REVIEW_SCHEMA, "frames": [frames[0], {**frames[1], **change}],
                    }))
                    result = cli.main_for("media", [
                        "redact-export", "--input", str(sources), "--review", str(review), "--output-dir", str(output),
                    ])
                    self.assertEqual(result, 2)
                    self.assertIn(diagnostic, stderr.getvalue())
                    self.assertFalse(output.exists())
                    self.assertFalse(list(root.glob(".redaction-export-*")))

    def test_multi_frame_image_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi.png"
            frames = [Image.new("RGB", (12, 12), color) for color in ("red", "green")]
            frames[0].save(path, save_all=True, append_images=frames[1:])
            with self.assertRaisesRegex(ValueError, "single-frame images"):
                media_redaction.read_frame(path)
