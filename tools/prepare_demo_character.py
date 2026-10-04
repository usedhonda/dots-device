"""Generate a small original geometric demo character and motion manifest."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

CELL_W, CELL_H = 192, 208


def draw_frame(motion: int, frame: int, total: int) -> Image.Image:
    image = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    phase = frame / max(1, total - 1)
    bob = 2 if motion == 0 and frame % 2 else 0
    x = 96 + ({1: int((phase - 0.5) * 10), 2: int((0.5 - phase) * 10)}.get(motion, 0))
    y = 104 + bob
    body = (x - 48, y - 48, x + 48, y + 48)
    draw.rounded_rectangle(body, radius=24, fill=(72, 134, 196, 255), outline=(24, 48, 80, 255), width=5)
    draw.ellipse((x - 27, y - 16, x - 11, y), fill=(245, 250, 255, 255))
    draw.ellipse((x + 11, y - 16, x + 27, y), fill=(245, 250, 255, 255))
    draw.ellipse((x - 22, y - 12, x - 16, y - 6), fill=(24, 48, 80, 255))
    draw.ellipse((x + 16, y - 12, x + 22, y - 6), fill=(24, 48, 80, 255))
    draw.arc((x - 24, y - 2, x + 24, y + 27), 10, 170, fill=(24, 48, 80, 255), width=4)
    draw.line((x, y - 48, x, y - 62), fill=(24, 48, 80, 255), width=4)
    draw.ellipse((x - 7, y - 69, x + 7, y - 55), fill=(247, 190, 70, 255), outline=(24, 48, 80, 255), width=3)
    if motion == 3:
        hand_x = x + (63 if frame % 2 else 57)
        draw.line((x + 40, y + 20, hand_x, y - 6), fill=(24, 48, 80, 255), width=7)
        draw.ellipse((hand_x - 8, y - 17, hand_x + 8, y - 1), fill=(247, 190, 70, 255), outline=(24, 48, 80, 255), width=3)
    else:
        draw.line((x + 38, y + 31, x + 55, y + 45), fill=(24, 48, 80, 255), width=7)
    draw.line((x - 38, y + 31, x - 55, y + 45), fill=(24, 48, 80, 255), width=7)
    return image


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    motions = [("idle", 4), ("right", 4), ("left", 4), ("wave", 4)]
    atlas = Image.new("RGBA", (CELL_W * 4, CELL_H * 4), (0, 0, 0, 0))
    animations = []
    for row, (name, frame_count) in enumerate(motions):
        for frame in range(frame_count):
            atlas.alpha_composite(draw_frame(row, frame, frame_count), (frame * CELL_W, row * CELL_H))
        animations.append({"name": name, "row": row, "columns": list(range(frame_count)), "frames": frame_count})
    atlas.save(output_dir / "character-atlas.png")
    (output_dir / "MOTION-MANIFEST.json").write_text(json.dumps({
        "character": "demo-blob", "license": "MIT", "sprite_file": "character-atlas.png",
        "cell_width": CELL_W, "cell_height": CELL_H, "animations": animations,
    }, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True, help="directory to receive the demo atlas and manifest")
    args = parser.parse_args()
    generate(args.output_dir)
    print(f"Generated demo character in {args.output_dir}")


if __name__ == "__main__":
    main()
