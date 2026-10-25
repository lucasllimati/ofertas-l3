"""Arte do post (1080x1350) com Pillow. Determinística: mesmo input -> mesma imagem."""

from __future__ import annotations

import io
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.common.util import brl
from src.content.caption import discount_pct

WIDTH, HEIGHT = 1080, 1350
MARGIN = 72
IMAGE_BOX = (MARGIN, 150, WIDTH - MARGIN, 900)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Foto vem do vendedor: limita pixels para evitar "bomba" de descompressão (Pillow levanta erro acima disso).
Image.MAX_IMAGE_PIXELS = 40_000_000

FONT_CANDIDATES = {
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
}


@lru_cache(maxsize=64)
def font(size: int, bold: bool = False, custom: str | None = None) -> ImageFont.FreeTypeFont:
    for path in ([custom] if custom else []) + FONT_CANDIDATES[bold]:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def fetch_image(url: str | None) -> bytes | None:
    """Baixa a foto do produto. Falhou? A arte sai sem foto, o post não trava."""
    if not url or not url.startswith("https://"):
        return None
    try:
        with httpx.stream("GET", url, timeout=15, follow_redirects=True) as resp:
            if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
                return None
            if resp.url.scheme != "https":  # redirecionamento para http não é aceito
                return None
            data = b""
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_IMAGE_BYTES:
                    return None
            return data
    except httpx.HTTPError:
        return None


def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int, max_lines: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=fnt) > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def render_post(
    product: dict[str, Any],
    brand: dict[str, Any],
    price_date: date,
    image_bytes: bytes | None,
    badge: str | None = None,
) -> bytes:
    """`badge`: selo do evento sazonal ativo (agente Calendário), desenhado no canto da foto."""
    colors = brand.get("colors", {})
    bg = colors.get("background", "#FFFFFF")
    text_color = colors.get("text", "#111111")
    muted = colors.get("muted", "#666666")
    accent = colors.get("accent", "#E4572E")
    badge_text = colors.get("badge_text", "#FFFFFF")
    f_bold, f_regular = brand.get("font_bold_path"), brand.get("font_path")

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    draw.text((MARGIN, 60), brand.get("name", "Garimpo").upper(), font=font(40, True, f_bold), fill=accent)
    tagline = brand.get("tagline", "")
    if tagline:
        draw.text((MARGIN, 108), tagline, font=font(26, False, f_regular), fill=muted)

    x0, y0, x1, y1 = IMAGE_BOX
    draw.rounded_rectangle(IMAGE_BOX, radius=36, fill="#FFFFFF")
    photo = None
    if image_bytes:
        try:
            photo = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            photo = None
    if photo:
        fitted = ImageOps.contain(photo, (x1 - x0 - 60, y1 - y0 - 60))
        img.paste(fitted, (x0 + (x1 - x0 - fitted.width) // 2, y0 + (y1 - y0 - fitted.height) // 2))
    else:
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.ellipse((cx - 160, cy - 160, cx + 160, cy + 160), fill=accent)
        label = brand.get("name", "Garimpo").split()[0]
        fnt = font(56, True, f_bold)
        w = draw.textlength(label, font=fnt)
        draw.text((cx - w / 2, cy - 34), label, font=fnt, fill=badge_text)

    pct = discount_pct(product["price"], product.get("price_original"))
    if pct:
        bx, by = x1 - 190, y0 - 30
        draw.ellipse((bx, by, bx + 200, by + 200), fill=accent)
        label = f"-{pct}%"
        fnt = font(60, True, f_bold)
        w = draw.textlength(label, font=fnt)
        draw.text((bx + 100 - w / 2, by + 64), label, font=fnt, fill=badge_text)

    if badge:
        fnt = font(34, True, f_bold)
        w = draw.textlength(badge, font=fnt)
        draw.rounded_rectangle((x0 + 24, y0 + 24, x0 + 56 + w, y0 + 84), radius=18, fill=text_color)
        draw.text((x0 + 40, y0 + 34), badge, font=fnt, fill=bg)

    y = y1 + 40
    title_font = font(46, True, f_bold)
    for line in _wrap(draw, product["title"], title_font, WIDTH - 2 * MARGIN, 2):
        draw.text((MARGIN, y), line, font=title_font, fill=text_color)
        y += 58

    y += 24
    price_font = font(104, True, f_bold)
    price_text = brl(product["price"])
    draw.text((MARGIN, y), price_text, font=price_font, fill=accent)
    if pct:
        old = brl(product["price_original"])
        old_font = font(44, False, f_regular)
        ox = MARGIN + draw.textlength(price_text, font=price_font) + 32
        oy = y + 46
        draw.text((ox, oy), old, font=old_font, fill=muted)
        ow = draw.textlength(old, font=old_font)
        draw.line((ox, oy + 28, ox + ow, oy + 28), fill=muted, width=4)

    footer = f"Preço em {price_date.strftime('%d/%m/%Y')} · sujeito a alteração · #publi"
    draw.text((MARGIN, HEIGHT - 80), footer, font=font(28, False, f_regular), fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
