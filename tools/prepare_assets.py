"""Convert a character sprite atlas into the firmware's RGB565/RLE header."""
import argparse
import json
from pathlib import Path

from PIL import Image

from rle_assets import write_runs

CELL_W, CELL_H = 192, 208
FRAME_W, FRAME_H = 144, 116
MAX_MOTIONS = 9
MIN_MOTIONS = 4
MAX_TOTAL_FRAMES = 255


def load_and_validate(source: Path):
    """Load a manifest and atlas, validating everything before output is opened."""
    manifest_path = source / "MOTION-MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    sprite_file = manifest.get("sprite_file")
    animations = manifest.get("animations")
    if not isinstance(sprite_file, str) or not sprite_file:
        raise ValueError("manifest sprite_file must be a non-empty string")
    if not isinstance(animations, list) or not MIN_MOTIONS <= len(animations) <= MAX_MOTIONS:
        raise ValueError(f"manifest animations must contain {MIN_MOTIONS}..{MAX_MOTIONS} motions")
    try:
        atlas = Image.open(source / sprite_file).convert("RGBA")
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot open sprite_file {sprite_file!r}: {exc}") from exc

    total_frames = 0
    normalized = []
    for index, motion in enumerate(animations):
        if not isinstance(motion, dict):
            raise ValueError(f"motion {index} must be an object")
        row = motion.get("row")
        columns = motion.get("columns")
        frames = motion.get("frames")
        if isinstance(row, bool) or not isinstance(row, int) or row < 0:
            raise ValueError(f"motion {index} row must be a non-negative integer")
        if not isinstance(columns, list) or not columns:
            raise ValueError(f"motion {index} columns must be a non-empty list")
        if any(isinstance(column, bool) or not isinstance(column, int) or column < 0 for column in columns):
            raise ValueError(f"motion {index} columns must contain non-negative integers")
        if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
            raise ValueError(f"motion {index} frames must be greater than zero")
        if frames != len(columns):
            raise ValueError(f"motion {index} frames ({frames}) must equal columns length ({len(columns)})")
        total_frames += frames
        if total_frames > MAX_TOTAL_FRAMES:
            raise ValueError(f"total frame count {total_frames} exceeds uint8 offset limit {MAX_TOTAL_FRAMES}")
        for column in columns:
            x0, y0 = column * CELL_W, row * CELL_H
            if x0 + CELL_W > atlas.width or y0 + CELL_H > atlas.height:
                raise ValueError(
                    f"motion {index} cell row={row} column={column} is outside "
                    f"{atlas.width}x{atlas.height} atlas"
                )
            if atlas.crop((x0, y0, x0 + CELL_W, y0 + CELL_H)).getchannel("A").getbbox() is None:
                raise ValueError(f"motion {index} cell row={row} column={column} has no non-transparent pixels")
        normalized.append((row, columns, frames))
    return atlas, normalized


def convert(source: Path, output: Path) -> tuple[int, int]:
    atlas, animations = load_and_validate(source)
    frames, counts, offsets = [], [], []
    for row, columns, frame_count in animations:
        offsets.append(len(frames))
        counts.append(frame_count)
        cells = [atlas.crop((column * CELL_W, row * CELL_H,
                             (column + 1) * CELL_W, (row + 1) * CELL_H)) for column in columns]
        bounds = [cell.getchannel("A").getbbox() for cell in cells]
        crop = (min(bound[0] for bound in bounds), min(bound[1] for bound in bounds),
                max(bound[2] for bound in bounds), max(bound[3] for bound in bounds))
        scale = min((FRAME_W - 4) / (crop[2] - crop[0]), (FRAME_H - 4) / (crop[3] - crop[1]))
        size = (round((crop[2] - crop[0]) * scale), round((crop[3] - crop[1]) * scale))
        for cell in cells:
            frame = cell.crop(crop).resize(size, Image.Resampling.LANCZOS)
            bg = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
            bg.alpha_composite(frame, ((FRAME_W - size[0]) // 2, FRAME_H - size[1] - 2))
            frames.append(bg)

    # All validation is complete before this directory is created or this file is opened.
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as handle:
        handle.write(f"#pragma once\n#include <Arduino.h>\n#define KAI_W {FRAME_W}\n#define KAI_H {FRAME_H}\n#define KAI_BACKGROUND 0xF77D\n")
        handle.write("const uint8_t kai_frame_counts[9] = {" + ",".join(map(str, counts)) + "};\n")
        handle.write("const uint8_t kai_frame_offsets[9] = {" + ",".join(map(str, offsets)) + "};\n")
        byte_count = write_runs(handle, "kai", frames)
    return byte_count, len(frames)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    byte_count, frame_count = convert(args.source, args.output)
    print(f"Prepared {frame_count} transparent frames, {FRAME_W}x{FRAME_H}, {byte_count} flash bytes; round trip verified")


if __name__ == "__main__":
    main()
