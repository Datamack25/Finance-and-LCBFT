"""Lecture des PDF : texte natif quand il existe, OCR (Tesseract) sinon.

Chaque page est restituée sous forme de lignes ; chaque ligne garde la
position des mots, ce qui permet ensuite de séparer les colonnes de
chiffres (un « 551 361 132 501 » n'est pas un seul nombre).
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from statistics import median

import pdfplumber

try:  # OCR optionnel
    import pytesseract
    from pytesseract import Output

    OCR_AVAILABLE = True
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # Tesseract multi-thread = plus lent ici
except Exception:  # pragma: no cover
    OCR_AVAILABLE = False


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    h: float  # hauteur du mot (sert d'échelle pour les écarts)
    top: float = 0.0


@dataclass
class Line:
    page: int  # numéro de page (1-based)
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Page:
    number: int
    width: float
    lines: list[Line] = field(default_factory=list)
    source: str = "texte"  # "texte" ou "ocr"

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


@dataclass
class Document:
    name: str
    pages: list[Page]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def ocr_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.source == "ocr"]


_GARBAGE = re.compile(r"\(cid:\d+\)")


def _native_ok(text: str) -> bool:
    """Le texte natif est-il exploitable ? (sinon : scan ou police mal encodée)"""
    if len(text.strip()) < 40:
        return False
    if len(_GARBAGE.findall(text)) > 20:
        return False
    letters = sum(c.isalpha() for c in text)
    weird = sum(1 for c in text if ord(c) < 32 and c not in "\n\t")
    return letters > 0.25 * len(text) and weird < 0.02 * len(text)


def _group_lines(words: list[Word], tops: list[float], page_no: int) -> list[Line]:
    """Regroupe des mots en lignes à partir de leur ordonnée."""
    if not words:
        return []
    order = sorted(range(len(words)), key=lambda i: (tops[i], words[i].x0))
    lines: list[list[int]] = []
    tol = max(2.0, 0.45 * median(w.h for w in words))
    for i in order:
        if lines and abs(tops[i] - tops[lines[-1][0]]) <= tol:
            lines[-1].append(i)
        else:
            lines.append([i])
    out = []
    for idx in lines:
        ws = sorted((words[i] for i in idx), key=lambda w: w.x0)
        out.append(Line(page=page_no, words=ws))
    return out


def _native_page(pg, page_no: int) -> Page:
    raw = pg.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
    words = [Word(w["text"], w["x0"], w["x1"], max(1.0, w["bottom"] - w["top"]), w["top"]) for w in raw]
    tops = [w["top"] for w in raw]
    return Page(page_no, float(pg.width), _group_lines(words, tops, page_no), "texte")


def _blank(img) -> bool:
    """Page quasi blanche (intercalaire) : inutile de l'OCRiser."""
    g = img.convert("L").resize((600, 840))
    dark = sum(1 for p in g.getdata() if p < 170)
    return dark < 0.0008 * 600 * 840


def _ocr_page(pg, page_no: int, dpi: int, lang: str) -> Page:
    img = pg.to_image(resolution=dpi).original
    if _blank(img):
        return Page(page_no, float(img.width), [], "ocr")
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 6", output_type=Output.DICT)
    words, tops = [], []
    for i, t in enumerate(data["text"]):
        if not t or not t.strip() or float(data["conf"][i]) < 0:
            continue
        h = max(1, data["height"][i])
        words.append(Word(t.strip(), data["left"][i], data["left"][i] + data["width"][i], h, data["top"][i]))
        tops.append(data["top"][i] + h / 2)  # centre vertical
    # Tesseract découpe souvent une ligne visuelle en plusieurs blocs
    # (libellé à gauche, chiffres à droite) : on regroupe par bande verticale.
    return Page(page_no, float(img.width), _group_lines(words, tops, page_no), "ocr")


def load_pdf(data: bytes, name: str, ocr: bool = True, dpi: int = 300, lang: str = "fra+eng",
             progress=None) -> Document:
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        n = len(pdf.pages)
        for i, pg in enumerate(pdf.pages, start=1):
            if progress:
                progress(i, n)
            text = pg.extract_text() or ""
            if _native_ok(text):
                pages.append(_native_page(pg, i))
            elif ocr and OCR_AVAILABLE:
                try:
                    pages.append(_ocr_page(pg, i, dpi, lang))
                except Exception:
                    pages.append(Page(i, float(pg.width), [], "ocr"))
            else:
                pages.append(Page(i, float(pg.width), [], "vide"))
    return Document(name, pages)
