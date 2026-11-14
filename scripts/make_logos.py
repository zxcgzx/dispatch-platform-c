"""把合图 三家Logo.png 里的怀柔实验室、北京大学书法字标，按颜色分层描摹成 SVG（矢量，放大不糊）。

做法：放大 → 按颜色提取蒙版（红色层、深色层）→ 每层二值描摹成平滑轮廓 → 各自上色后叠成一个 SVG。
南方电网用官网矢量，北大校徽用官方矢量化的 SVG，这两个不经过描摹。
用法：python scripts/make_logos.py    依赖：pillow、numpy、vtracer
"""
import re
from pathlib import Path

import numpy as np
import vtracer
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "三家Logo.png"
OUT = ROOT / "frontend" / "src" / "assets"
TMP = ROOT / ".scratch"
TMP.mkdir(exist_ok=True)
SCALE = 6


def layers(box):
    im = Image.open(SRC).convert("RGB").crop(box)
    im = im.resize((im.width * SCALE, im.height * SCALE), Image.BICUBIC).filter(ImageFilter.GaussianBlur(SCALE * 0.35))
    a = np.asarray(im).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = a.mean(axis=2)
    redness = r - (g + b) / 2
    red = np.clip((redness - 40) / 50, 0, 1)                     # 红：R 明显高于 G、B
    dark = np.clip((170 - lum) / 60, 0, 1) * (1 - red)           # 深色（灰 / 黑）：亮度低且不是红
    return im.size, red, dark


def trace_mask(mask, name, speckle=24):
    img = Image.fromarray((255 - (mask > 0.5) * 255).astype("uint8"))       # 黑色 = 前景
    p = TMP / f"{name}.png"
    img.save(p)
    out = TMP / f"{name}.svg"
    vtracer.convert_image_to_svg_py(str(p), str(out), colormode="binary", mode="spline", filter_speckle=speckle,
                                    corner_threshold=70, length_threshold=5.0, max_iterations=10, splice_threshold=45, path_precision=1)
    return out.read_text(encoding="utf-8")


def paths_of(svg, fill):
    ps = re.findall(r"<path[^>]*?/>", svg, flags=re.S)
    return "".join(re.sub(r'fill="[^"]*"', f'fill="{fill}"', p) for p in ps)


def build(box, name, red_fill, dark_fill):
    (w, h), red, dark = layers(box)
    body = paths_of(trace_mask(dark, name + "_dark"), dark_fill) + paths_of(trace_mask(red, name + "_red"), red_fill)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w // SCALE}" height="{h // SCALE}">{body}</svg>'
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    return len(svg)


if __name__ == "__main__":
    n1 = build((525, 435, 975, 562), "logo_hrlab", "#c8161d", "#3a3a3a")
    n2 = build((355, 100, 975, 360), "logo_pku_wordmark", "#8c1515", "#231815")
    print(f"logo_hrlab.svg {n1 // 1024} KB, logo_pku_wordmark.svg {n2 // 1024} KB")
