"""Citation markers ``[n]`` of a draft: every number points to a source, every unit cites one.

A marker holds one or more source numbers: ``[2]``, ``[1, 3]``, ``[1-3]``. A Markdown link
(``[1](url)``) or a reference (``[1][a]``, ``[1]: url``) is not a marker.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

CITATION = re.compile(r"\[(\d{1,3}(?:\s*[,;\-\u2013]\s*\d{1,3})*)\](?![(\[:])")
_PART = re.compile(r"(\d{1,3})(?:\s*[\-\u2013]\s*(\d{1,3}))?")  # a range: hyphen or en dash
_LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d{1,2}[.)])\s+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_BLOCK_BREAK = re.compile(r"\n\s*\n")
MAX_RANGE = 50


def _numbers(marker: str) -> list[int]:
    found: list[int] = []
    for part in _PART.finditer(marker):
        first = int(part.group(1))
        last = int(part.group(2)) if part.group(2) else first
        if last < first or last - first > MAX_RANGE:
            found.append(first)  # a reversed or huge range is read as its first number only
            continue
        found.extend(range(first, last + 1))
    return found


def citation_numbers(text: str) -> list[int]:
    """The cited source numbers, in order of first appearance."""
    seen: list[int] = []
    for marker in CITATION.finditer(text):
        for number in _numbers(marker.group(1)):
            if number not in seen:
                seen.append(number)
    return seen


def dangling_citations(text: str, source_count: int) -> list[int]:
    """Cited numbers that point to no source of the numbered list ``1..source_count``."""
    return [n for n in citation_numbers(text) if not 1 <= n <= source_count]


def _unit_lines(text: str) -> Iterator[list[tuple[int, int]]]:
    """Each unit as the offsets of its stripped lines; headings and blank lines left out."""
    starts = [0, *(m.end() for m in _BLOCK_BREAK.finditer(text))]
    ends = [*(m.start() for m in _BLOCK_BREAK.finditer(text)), len(text)]
    for block_start, block_end in zip(starts, ends, strict=True):
        block = text[block_start:block_end]
        current: list[tuple[int, int]] = []
        offset = block_start
        for raw, line in zip(block.splitlines(keepends=True), block.splitlines(), strict=True):
            line_start, offset = offset, offset + len(raw)
            if not line.strip() or _HEADING.match(line):
                continue
            if _LIST_ITEM.match(line) and current:
                yield current
                current = []
            start = line_start + len(line) - len(line.lstrip())
            current.append((start, line_start + len(line.rstrip())))
        if current:
            yield current


def units(text: str) -> list[str]:
    """Paragraphs and list items, the units that must each cite a source when they state a fact.

    Headings are not units; a list item's continuation lines belong to the item.
    """
    return [" ".join(text[a:b] for a, b in lines) for lines in _unit_lines(text)]


def unit_spans(text: str) -> list[tuple[int, int]]:
    """Where each unit of ``units`` lies in ``text``: first line's start to last line's end."""
    return [(lines[0][0], lines[-1][1]) for lines in _unit_lines(text)]


def uncited_units(text: str) -> list[str]:
    """Units without any marker; whether such a unit states a fact is the judge's call."""
    return [unit for unit in units(text) if not CITATION.search(unit)]
