# Replaceable character assets

The character artwork is a local build input. KAI's original pet-v1 manifest, sprite sheet, previews, and metadata belong in `.local/characters/kai/source`; generated KAI data belongs in `.local/characters/kai/generated/kai_assets.h`. The ignored `firmware/kai_companion/kai_assets.h` path is only the internal build alias used by the existing include and generator flow. A clean checkout contains none of these files. This guide describes the asset format that the current generator accepts. A procedural MIT demo pack can be generated independently of private artwork.

## What works today

`tools/prepare_assets.py` reads `MOTION-MANIFEST.json` from the atlas directory, opens the manifest's `sprite_file` as RGBA, and walks its `animations` entries. Each entry supplies a `row`, a `columns` list, and a `frames` count. The script treats each selected cell as 192 x 208 pixels, finds the union of non-transparent bounds across that motion's cells, scales the cropped artwork into a fixed 144 x 116 transparent frame (leaving a four-pixel maximum margin and a two-pixel bottom offset), and writes `kai_assets.h`.

The generated frames are quantized to RGB565 with 8-bit alpha and encoded as lossless runs by `tools/rle_assets.py` (lossless after that RGB565 quantization, not lossless relative to the original 24-bit source). The encoder round-trips every encoded pixel before the header is written. The header defines `KAI_W`, `KAI_H`, the frame counts and offsets, and the RLE data used by `drawKaiFrame` in `firmware/kai_companion/themed_assets.h`.

The current renderer uses four motion slots from `drawKai` in `firmware/kai_companion/kai_companion.ino`: slot 0 is idle, slot 1 is moving right, slot 2 is moving left, and slot 3 is waving. The generated tables reserve nine slots because their declarations are `kai_frame_counts[9]` and `kai_frame_offsets[9]`; slots 4 through 8 have no established runtime meaning yet. C++ zero-initializes omitted elements, so a current header may contain four through nine animation entries; keep at least the first four positions stable and do not add artwork solely to fill unused slots. The name “KAI” is the current sample/code vocabulary, not a requirement that a replacement character be named or owned by KAI.

## Atlas and manifest requirements

- Use an image format Pillow can open and convert to RGBA, preferably a PNG with real transparency around the character.
- Lay out motion frames in rows of 192 x 208 cells. A manifest `row` selects one row and `columns` selects the cells in frame order; the source atlas must be large enough for every selected row and column.
- Keep each motion's selected cells non-empty in alpha. The converter rejects empty alpha cells before writing output.
- Make `frames` agree with the number of selected columns. The converter rejects inconsistent frame counts before writing output.
- Provide at least four and no more than nine animation entries in the established slot order when producing the current nine-slot header. C++ zero-initializes omitted table elements, but only slots 0 through 3 currently have runtime consumers; the converter checks this range before writing the nine-slot tables.
- Keep the visible subject within each cell and use transparency for the surrounding area. The generator computes one shared crop per motion, scales it to the fixed 144 x 116 output, and composites it against the runtime theme background later.

The converter validates manifest shape, integer coordinates, frame-count agreement, four-to-nine motion slots, atlas bounds, and nonempty alpha cells before opening the output. The total frame count must be at most 255 because current motion offsets use uint8_t. Source cells are fixed at 192 x 208 and output at 144 x 116; changing the output ABI requires coordinated firmware changes.

## Replace a local character

1. Make `.local/characters/YOUR_CHARACTER/source` containing your RGBA atlas and `MOTION-MANIFEST.json`. Keep private inputs ignored by default. A sample pack or your own artwork may be tracked only when its explicit ownership and redistribution terms permit that choice; never add credentials or personal identifiers.
2. Arrange the first four manifest entries as idle, right, left, and wave. Supply four to nine entries for the current generated table; reserve unused slots rather than creating filler art when no consumer is defined.
3. Check that every selected cell is 192 x 208, has visible pixels, and appears in the intended order. Confirm that each `frames` value equals its `columns` length.
4. From the project root, run:

   ```sh
   python3 tools/prepare_assets.py .local/characters/YOUR_CHARACTER/source .local/characters/YOUR_CHARACTER/generated/kai_assets.h
   ```

   The command creates the generated header's parent directory when needed and prints the frame count, fixed output size, encoded byte count, and round-trip result.
5. Keep the generated output at `.local/characters/YOUR_CHARACTER/generated/kai_assets.h`. Select that pack by pointing the ignored `firmware/kai_companion/kai_assets.h` alias at it, then build the firmware using the normal local build flow. This keeps each private generated pack separate and avoids writing through the alias into another pack. Whether a source atlas or generated pack is published is an artwork rights decision, separate from this generator guide.

For a complete four-motion manifest and a redistributable atlas, run `tools/prepare_demo_character.py --output-dir .local/characters/demo/source`. It creates original geometric artwork under the project MIT license, independent of KAI.

The sample filename and character name are placeholders. This guide grants no ownership or license; use only assets for which you have the necessary rights and follow the terms that apply to any pack you choose to distribute.

## Size limits

The converter validates metadata but does not guarantee the pack fits flash. Confirm the Arduino compile size report before upload. The current owner-local KAI pack uses about 94% of the application partition; the public procedural demo is smaller. Generated packs retain each input artwork's rights; MIT for the project code does not grant rights to unrelated artwork.
