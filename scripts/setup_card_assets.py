"""Prepare card assets: crop logo, download Cyrillic fonts, paper texture."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from github_radar.http_ssl import ssl_verify

ASSETS = ROOT / "templates" / "assets"
FONTS = ASSETS / "fonts"

NUGGET_CANDIDATES = [
    Path(
        r"C:\Users\zobni\.cursor\projects\d-treasure\assets"
        r"\c__Users_zobni_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_"
        r"ChatGPT_Image_16____._2026__.__12_32_14-a0903b22-f85b-4318-9c25-0cc38a052270.png"
    ),
    ROOT / "assets" / "nuggets-source.png",
]

FONT_URLS = {
    "Manrope-Bold.woff": "https://cdn.jsdelivr.net/npm/@fontsource/manrope@5.2.5/files/manrope-cyrillic-700-normal.woff",
    "Inter-Regular.woff": "https://cdn.jsdelivr.net/npm/@fontsource/inter@5.2.5/files/inter-cyrillic-400-normal.woff",
    "Inter-Bold.woff": "https://cdn.jsdelivr.net/npm/@fontsource/inter@5.2.5/files/inter-cyrillic-700-normal.woff",
    "JetBrainsMono-Regular.woff": "https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5.2.5/files/jetbrains-mono-cyrillic-400-normal.woff",
}


def _find_nugget_source() -> Path:
    for path in NUGGET_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("Nugget reference image not found in assets/")


def crop_logo() -> Path:
    from PIL import Image

    src = _find_nugget_source()
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    badge_w = w // 3
    cropped = img.crop((0, 0, badge_w, h))
    out = ASSETS / "logo.png"
    cropped.save(out, "PNG", optimize=True)
    print(f"  logo.png  ({cropped.size[0]}x{cropped.size[1]}) from {src.name}")
    return out


def download_fonts() -> None:
    FONTS.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=60.0, follow_redirects=True, verify=ssl_verify())
    for filename, url in FONT_URLS.items():
        dest = FONTS / filename
        if dest.exists():
            print(f"  {filename} (exists)")
            continue
        print(f"  downloading {filename}...")
        response = client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)
        print(f"  {filename}")
    client.close()


def make_paper_texture() -> Path:
    from PIL import Image, ImageDraw

    size = 512
    img = Image.new("RGB", (size, size), "#F2EDE2")
    draw = ImageDraw.Draw(img)
    for y in range(0, size, 4):
        shade = 242 - (y % 8)
        draw.line([(0, y), (size, y)], fill=(shade, shade - 2, shade - 6), width=1)
    for x in range(0, size, 6):
        draw.line([(x, 0), (x, size)], fill=(238, 233, 224), width=1)
    out = ASSETS / "paper.png"
    img.save(out, "PNG", optimize=True)
    print("  paper.png")
    return out


def main() -> int:
    print("=== Card assets setup ===\n")
    ASSETS.mkdir(parents=True, exist_ok=True)
    try:
        crop_logo()
        download_fonts()
        make_paper_texture()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
