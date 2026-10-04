import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prepare_assets import convert
from prepare_demo_character import generate


class PrepareAssetsTest(unittest.TestCase):
    def test_demo_generation_and_conversion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            output = root / "generated.h"
            generate(source)
            byte_count, frame_count = convert(source, output)
            self.assertGreater(byte_count, 0)
            self.assertEqual(frame_count, 16)
            self.assertTrue(output.exists())

    def test_malformed_manifest_fails_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            Image.new("RGBA", (192, 208), (255, 0, 0, 255)).save(source / "atlas.png")
            (source / "MOTION-MANIFEST.json").write_text(json.dumps({
                "sprite_file": "atlas.png",
                "animations": [{"row": 0, "columns": [0], "frames": 2}] * 4,
            }))
            output = root / "missing" / "generated.h"
            with self.assertRaisesRegex(ValueError, "frames"):
                convert(source, output)
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())


if __name__ == "__main__":
    unittest.main()
