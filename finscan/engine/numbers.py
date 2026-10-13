"""Découpage d'une ligne en libellé + nombres positionnés.

Les nombres « à la française » (1 276 969) sont recollés seulement si
l'écart entre les groupes de chiffres est petit par rapport à la taille
du texte : un grand écart signale un changement de colonne.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .ingest import Line

_OCR_FIX = str.maketrans({"S": "5", "O": "0", "o": "0", "l": "1", "I": "1", "|": "1"})
_DIGITISH = re.compile(r"^[\(\-–—]?[\$€£]?[\dSOolI|][\dSOolI|.,]*[\)%€]?$")
_NOTE_REF = re.compile(r"^\d{1,2}\.\d{1,2}$")
_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_SHORT_YEAR = re.compile(r"[-./](\d{2})$")
DASHES = {"-", "–", "—"}


@dataclass
class Num:
    value: float | None  # None = case vide signalée par un tiret
    x0: float
    x1: float
    raw: str
    note: bool = False  # ressemble à un renvoi de note (« 2.01 ») : écarté s'il ne tombe pas sous une colonne

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class ParsedLine:
    label: str
    norm: str
    nums: list[Num]
    line: Line

    @property
    def page(self) -> int:
        return self.line.page


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("’", "'").replace("œ", "oe")
    s = re.sub(r"[^a-z0-9' /+\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_token(t: str) -> str:
    t = t.strip("[]|{}:;*")
    return t


def _is_numeric(t: str) -> bool:
    t = _clean_token(t)
    if not t or not _DIGITISH.match(t):
        return False
    return sum(c.isdigit() for c in t) >= max(1, len(t.strip("()-–—$€%")) // 2)


def _to_float(s: str) -> float | None:
    s = _clean_token(s).translate(_OCR_FIX)
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()$€£%")
    if s.startswith(("-", "–", "—")):
        neg = True
        s = s[1:]
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):  # 1,234,567.89
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):  # 1.234.567,89
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_line(line: Line, gap_factor: float = 0.9) -> ParsedLine:
    words = line.words
    if not words:
        return ParsedLine("", "", [], line)
    hs = sorted(w.h for w in words)
    h = hs[len(hs) // 2]
    gap_max = gap_factor * h  # au-delà : changement de colonne

    label_parts: list[str] = []
    nums: list[Num] = []
    i = 0
    seen_number = False
    # renvoi de note en tête de ligne : « (1) Net sales by… »
    if len(words) > 1 and re.fullmatch(r"\(\d\)|\d\)", words[0].text):
        words = words[1:]
    while i < len(words):
        w = words[i]
        t = _clean_token(w.text)
        # tiret isolé : signe d'un nombre collé, ou case vide
        if t in DASHES:
            nxt = words[i + 1] if i + 1 < len(words) else None
            if nxt is not None and _is_numeric(nxt.text) and nxt.x0 - w.x1 <= gap_max:
                words_ = [w, nxt]
                i += 2
                # continuer à coller les groupes de 3 chiffres
                while i < len(words) and re.fullmatch(r"\d{3}\)?", _clean_token(words[i].text).translate(_OCR_FIX)) \
                        and words[i].x0 - words_[-1].x1 <= gap_max:
                    words_.append(words[i])
                    i += 1
                raw = "".join(_clean_token(x.text) for x in words_[1:])
                v = _to_float(raw)
                nums.append(Num(-abs(v) if v is not None else None, words_[0].x0, words_[-1].x1, "-" + raw))
                seen_number = True
                continue
            if seen_number or (label_parts and nxt is None) or (nxt is not None and nxt.x0 - w.x1 > gap_max):
                nums.append(Num(None, w.x0, w.x1, "-"))
                seen_number = True
                i += 1
                continue
            label_parts.append(t)
            i += 1
            continue
        if t in {"$", "€", "£"}:
            i += 1
            continue
        if _is_numeric(t):
            # référence de note (2.01, 5.1) juste après le libellé : on l'ignore
            prev = words[i - 1].text if i else ""
            is_note = bool(_NOTE_REF.match(t) and prev not in {"$", "€"} and not seen_number)
            group = [w]
            i += 1
            first = _clean_token(t).strip("()-–—$€").translate(_OCR_FIX)
            if re.fullmatch(r"\d{1,4}", first):
                while i < len(words):
                    nt = _clean_token(words[i].text).translate(_OCR_FIX)
                    if re.fullmatch(r"\d{3}\)?", nt) and words[i].x0 - group[-1].x1 <= gap_max:
                        group.append(words[i])
                        i += 1
                    else:
                        break
            raw = "".join(_clean_token(g.text) for g in group)
            v = _to_float(raw)
            if v is not None:
                nums.append(Num(v, group[0].x0, group[-1].x1, raw, note=is_note and len(group) == 1))
                seen_number = not (is_note and len(group) == 1)
            else:
                label_parts.append(raw)
            continue
        if not seen_number:
            label_parts.append(w.text)
        i += 1
    label = " ".join(label_parts)
    return ParsedLine(label, normalize(label), nums, line)


def year_of(token: str) -> int | None:
    m = _YEAR.search(token)
    if m:
        return int(m.group(0))
    m = _SHORT_YEAR.search(token.strip())
    if m and re.search(r"[a-zA-Zéû]", token):
        return 2000 + int(m.group(1))
    return None
