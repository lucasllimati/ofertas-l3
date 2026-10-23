"""Monta a legenda final (HTML do Telegram) e valida conformidade antes de publicar."""

from __future__ import annotations

import html
import re
from datetime import date

from src.common.util import brl
from src.content.copy import HANDLE_RE, PHONE_RE, URL_RE, CopyResult

TELEGRAM_CAPTION_LIMIT = 1024
DISCLOSURE = "#publi · link de afiliado"
PRICE_NOTICE = "Preço consultado em {date}, sujeito a alteração."
FORBIDDEN = [
    r"\bcura\b",
    r"\bemagre",
    r"\bmilagr",
    r"\bgarantid",
    r"100% original",
    r"\boriginal\b",
    r"melhor do brasil",
]


def discount_pct(price: float, original: float | None) -> int | None:
    if not original or original <= price:
        return None
    pct = round((1 - price / original) * 100)
    return pct if pct >= 5 else None


def build_caption(
    copy: CopyResult,
    price: float,
    price_original: float | None,
    link: str,
    price_date: date,
    brand_hashtags: list[str],
) -> str:
    esc = html.escape
    # Identificação publicitária na primeira linha: clara e vista antes do link (CONAR).
    lines = [f"<i>{DISCLOSURE}</i>", f"<b>{esc(copy.headline)}</b>", ""]
    lines += [f"• {esc(b)}" for b in copy.bullets]
    lines.append("")
    pct = discount_pct(price, price_original)
    if pct:
        # "De/por" só chega aqui depois de verificado no histórico (verified_original em pipeline/content.py).
        lines.append(f"💰 <b>{brl(price)}</b> <s>{brl(price_original)}</s> (-{pct}%)")
    else:
        lines.append(f"💰 <b>{brl(price)}</b>")
    lines.append(f'👉 <a href="{esc(link, quote=True)}">Ver oferta</a>')
    lines.append("")
    lines.append(f"<i>{PRICE_NOTICE.format(date=price_date.strftime('%d/%m/%Y'))}</i>")
    tags = list(dict.fromkeys([*copy.hashtags, *brand_hashtags]))[:5]
    if tags:
        lines.append(" ".join(tags))
    caption = "\n".join(lines)
    while len(_visible(caption)) > TELEGRAM_CAPTION_LIMIT and len(copy.bullets) > 1:
        copy = copy.model_copy(update={"bullets": copy.bullets[:-1]})
        return build_caption(copy, price, price_original, link, price_date, brand_hashtags)
    return caption


def _visible(caption: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", caption))


def compliance_issues(caption: str, link_allowed: bool) -> list[str]:
    """Regras determinísticas (Revisor - parte de regras). Lista vazia = pode publicar."""
    text = _visible(caption)
    lower = text.lower()
    issues = []
    first_line = lower.strip().split("\n", 1)[0]
    if "#publi" not in first_line and "link de afiliado" not in first_line:
        issues.append("identificação de publicidade (#publi / link de afiliado) precisa estar na primeira linha")
    if "sujeito a alteração" not in lower or not re.search(r"\d{2}/\d{2}/\d{4}", text):
        issues.append("sem data do preço e aviso 'sujeito a alteração'")
    if len(text) > TELEGRAM_CAPTION_LIMIT:
        issues.append(f"legenda com {len(text)} caracteres (limite {TELEGRAM_CAPTION_LIMIT})")
    if not link_allowed:
        issues.append("link fora dos destinos permitidos")
    for pattern in FORBIDDEN:
        if re.search(pattern, lower):
            issues.append(f"termo proibido: {pattern}")
    # O único link permitido é o href de "Ver oferta" (montado pelo código, invisível no texto).
    for name, pattern in (("link no texto", URL_RE), ("@perfil no texto", HANDLE_RE), ("telefone", PHONE_RE)):
        if pattern.search(text):
            issues.append(f"{name}: possível desvio de tráfego ou golpe")
    if len(re.findall(r"<a\s", caption)) != 1:
        issues.append("a legenda deve ter exatamente um link (Ver oferta)")
    return issues
