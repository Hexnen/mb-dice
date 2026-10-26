#!/usr/bin/env python3
"""Build the Mythic Bastionland illuminated dice set.

Thin wrapper over the foundry-vtt-module skill pipeline (dice_common + build_set + fit_face_to_uv):
ONE image2 call per die, art baked from the exact DSN face template, AnglicanText numerals baked into
the mockup, the attached "Contents" illuminated page passed to image2 as the style reference, and an
illuminated-manuscript prompt (parchment + gold/green foliate border) replacing the stone wording.

    python build_mb_dice.py --dice d6 --prep            # free: montage preview only
    python build_mb_dice.py --dice d6                    # one die
    python build_mb_dice.py --dice d4,d8,d10,d12,d20     # the rest (reuses the Contents page anchor)
"""
import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image

SKILL = Path("C:/Users/santa/.claude/skills/foundry-vtt-module/scripts")
sys.path.insert(0, str(SKILL))

import dice_common as dc          # noqa: E402
import fit_face_to_uv as fit      # noqa: E402
import build_set as bs            # noqa: E402

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
FONT = "C:/Users/santa/AppData/Local/FoundryVTT/Data/systems/mythicbastionland/fonts/anglicantext.regular.ttf"
STYLE = HERE / "inspiration_contents.png"
OUT = MODULE / "textures"
ENV = MODULE / "image2api.env"

# Illuminated-manuscript prompt (replaces build_set's stone FULL_PROMPT). The mockup already carries the
# parchment fill + the AnglicanText numeral; image2 only illuminates the border and paints the numeral.
MB_PROMPT = (
    "This is a grid of die faces, each an aged PARCHMENT tile (with a dark blackletter NUMERAL already "
    "drawn on it) inside its outline, on a pure green background. Illuminate every tile EXACTLY ALIKE in "
    "the style of a medieval ILLUMINATED MANUSCRIPT page: (1) warm cream vellum/parchment surface with "
    "subtle age and fibre; (2) an ornate border frame just inside the edge made of GOLD-LEAF and deep "
    "EMERALD/TEAL foliate acanthus vine-work with small red and blue accents — gilded and richly painted, "
    "like an illuminated manuscript margin. IDENTICAL FRAME: use ONE single border design repeated "
    "EXACTLY the same on EVERY face (same motifs, thickness, spacing, placement) — faces differ ONLY by "
    "their numeral. Paint the numeral shown on each tile in lustrous gold/dark ink in the SAME blackletter "
    "style; keep its EXACT digits, shape and position — do NOT change, replace or re-letter it. Keep each "
    "tile's shape and position. All space around and between tiles must stay one pure uniform saturated "
    "chroma-green (RGB 0,255,0): clean green screen, no gradient, no shadow. CRITICAL: nothing — numeral, "
    "border or gilding — may cross or touch the outline; everything stays strictly inside it. Same grid, "
    "same positions. No extra text, no watermark."
)
STYLE_CLAUSE = (
    " STYLE MATCH (critical for set consistency): an ADDITIONAL reference image is a real illuminated "
    "manuscript 'Contents' page — match its exact palette and treatment: the gold-and-green foliate "
    "border ornament, the aged parchment tone, and the blackletter lettering. Reproduce that look EXACTLY "
    "so every die belongs to the same set; only the face shape and numeral differ between faces."
)


def process(die, prep, anchor):
    shapes = dc.load_shapes()
    work = OUT / "_work"
    work.mkdir(parents=True, exist_ok=True)
    # Clean cream parchment base — NOT a crop of the page (its centre holds the "Contents" title text,
    # which would bake unwanted lettering onto every face). image2 paints the real parchment from the ref.
    patch = Image.new("RGBA", (bs.CELL, bs.CELL), (236, 229, 212, 255))
    montage = bs.build_input(die, "full", shapes, FONT, patch)
    montage.save(work / f"{die}_input.webp", "WEBP", lossless=True)
    if prep:
        print(f"[{die}] PREP -> {work / (die + '_input.webp')} (no API)")
        return None, 0.0
    cols, rows = dc.grid_dims(die)
    prompt = MB_PROMPT + STYLE_CLAUSE
    key = dc.load_key(str(ENV))
    refs = [anchor]
    # Lock the set to the realised d6 look (the concrete target) once it exists.
    d6_out = OUT / "_work" / "d6_out.webp"
    if die != "d6" and d6_out.exists():
        refs.append(Image.open(d6_out).convert("RGB"))
    print(f"[{die}] illuminated full: one image2 call ({cols}x{rows}) [+{len(refs)} refs] ...")
    png, usage = dc.image2_edit(montage, prompt, key, bs.request_size(cols, rows),
                                "gpt-image-2", "medium", extra_refs=refs)
    cost = dc.usage_cost("gpt-image-2", usage)
    out_img = work / f"{die}_out.webp"
    Image.open(io.BytesIO(png)).convert("RGB").save(out_img, "WEBP", quality=95)
    slice_faces(die, out_img)
    print(f"  cost ${cost:.4f}")
    return die, cost


# d6 face polygon (cell-local) from dsn-face-uv.json — the inset rect the cube samples.
D6_RECT = (0.013, 0.012, 0.990, 0.989)
SIZE = 512


def slice_faces(die, atlas_path):
    """d6: fit each face into the inset RECT with NO rotation (the generic kite-corner warp
    rotates a square 45deg — see stonetop build_d6_aligned). Other dice: warp to the UV polygon."""
    if die != "d6":
        fit.warp_atlas(die, atlas_path, OUT, size=512, bumps=True)
        return
    keyed = dc.chroma_key(Image.open(atlas_path).convert("RGB"))
    cols, rows = dc.grid_dims(die)
    cw, ch = keyed.width // cols, keyed.height // rows
    x0, y0, x1, y1 = D6_RECT
    tx0, ty0 = round(x0 * SIZE), round(y0 * SIZE)
    tw, th = round((x1 - x0) * SIZE), round((y1 - y0) * SIZE)
    for i in range(dc.DICE[die]["faces"]):
        c, r = i % cols, i // cols
        cell = keyed.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
        bb = cell.split()[-1].getbbox()
        art = (cell.crop(bb) if bb else cell).resize((tw, th), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        canvas.paste(art, (tx0, ty0))
        canvas.save(OUT / f"{die}f{i + 1}.webp", "WEBP", quality=92, method=6)
        bump = Image.new("RGBA", (SIZE, SIZE), (128, 128, 128, 255))
        bump.alpha_composite(canvas)
        bump.convert("L").save(OUT / f"{die}f{i + 1}-bump.webp", "WEBP", quality=90, method=6)
    print(f"  {die}: rect-fit {dc.DICE[die]['faces']} faces (no rotation)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dice", default="d4,d6,d8,d10,d12,d20")
    ap.add_argument("--prep", action="store_true")
    a = ap.parse_args()
    dice = [d.strip() for d in a.dice.split(",") if d.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    anchor = Image.open(STYLE).convert("RGB")
    made, total = [], 0.0
    for d in dice:
        die, cost = process(d, a.prep, anchor)
        if die:
            made.append(die)
            total += cost
    if a.prep:
        prev = bs.build_preview(OUT, dice, "input")
        print(f"\nPREP done (no API). Preview -> {prev}")
        return
    if made:
        prev = bs.build_preview(OUT, made, "faces")
        cost_path = OUT / "_cost.json"
        prev_total = 0.0
        if cost_path.exists():
            try:
                prev_total = json.loads(cost_path.read_text()).get("usd", 0.0)
            except Exception:
                prev_total = 0.0
        cost_path.write_text(json.dumps(
            {"usd": round(prev_total + total, 4), "this_run": round(total, 4),
             "model": "gpt-image-2", "dice": made}, indent=2))
        print(f"\nDone: {', '.join(made)} -> {OUT}")
        print(f"COST this run: ${total:.4f}   CUMULATIVE (mb-dice): ${prev_total + total:.4f}")
        print(f"PREVIEW: {prev}")


if __name__ == "__main__":
    main()
