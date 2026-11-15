"""Stitch docs/images/demo/*.png (from the Playwright demo capture) into docs/images/demo.gif (~30 s)."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
frames = sorted((ROOT / "docs" / "images" / "demo").glob("*.png"))
imgs = [Image.open(f).convert("RGB").resize((960, 570)) for f in frames]
pal = [i.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for i in imgs]
per = max(2500, 30000 // max(1, len(pal)))
pal[0].save(ROOT / "docs" / "images" / "demo.gif", save_all=True, append_images=pal[1:], duration=per, loop=0, optimize=True)
print(len(pal), "frames,", per, "ms each ->", (ROOT / "docs" / "images" / "demo.gif").stat().st_size // 1024, "KB")
