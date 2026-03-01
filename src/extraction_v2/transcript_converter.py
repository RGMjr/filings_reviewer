"""
Transcript Converter — Convert plain-text earnings call transcripts to semantic HTML.

Produces HTML suitable for V2 pipeline ingestion with:
- Sentence-level <p> elements (critical for value binding proximity)
- Section detection (Prepared Remarks, Q&A, Operator)
- Speaker role inference (CEO, CFO, etc.)
- Document metadata extraction from transcript headers

Design principles:
- Deterministic (no LLM calls)
- Sentence splitting for paragraphs >300 chars (prevents single-speaker-turn bottleneck)
- Speaker role inference from title patterns
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

# Sentence boundary: period/exclamation/question followed by space and uppercase letter
# Avoids splitting on abbreviations like "Mr.", "Inc.", "U.S."
_SENTENCE_BOUNDARY = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z])'
)

# Common abbreviations that should NOT trigger sentence splits
_ABBREV_PATTERN = re.compile(
    r'\b(?:Mr|Mrs|Ms|Dr|Inc|Corp|Ltd|vs|etc|approx|est)\.\s+[A-Z]'
)

# Speaker attribution: "Speaker Name: content" or "Speaker Name, Title: content"
_SPEAKER_PATTERN = re.compile(r"^([A-Z][a-zA-Z\s\-'\.,]+?):\s*(.+)", re.DOTALL)

# Section boundary patterns
# Keys map directly to SectionType enum values (and data-section-type attributes).
_SECTION_PATTERNS = {
    "qa": re.compile(r"question[- ]and[- ]answer|q\s*&\s*a", re.IGNORECASE),
    "prepared_remarks": re.compile(r"prepared\s+remarks", re.IGNORECASE),
    "operator": re.compile(r"operator\s+instructions?", re.IGNORECASE),
    # Disclaimer: only match standalone header lines, not incidental mentions.
    # Pattern anchored to start/end (no trailing sentence content) to avoid
    # triggering on "CEO: This call contains forward-looking statements..." etc.
    "disclaimer": re.compile(r"^\s*(?:safe\s+harbor|disclaimer)\s*$", re.IGNORECASE),
}

# Speaker role patterns (title keywords)
_ROLE_PATTERNS = {
    "ceo": re.compile(r"\b(?:CEO|Chief\s+Executive\s+Officer|President\s+and\s+CEO)\b", re.IGNORECASE),
    "cfo": re.compile(r"\b(?:CFO|Chief\s+Financial\s+Officer)\b", re.IGNORECASE),
    "coo": re.compile(r"\b(?:COO|Chief\s+Operating\s+Officer)\b", re.IGNORECASE),
    "cto": re.compile(r"\b(?:CTO|Chief\s+Technology\s+Officer)\b", re.IGNORECASE),
    "investor_relations": re.compile(r"\b(?:Investor\s+Relations|IR\s+(?:Director|VP|Head))\b", re.IGNORECASE),
    "analyst": re.compile(r"\b(?:Analyst|Research\s+Analyst)\b", re.IGNORECASE),
}

# Metadata extraction patterns
_TICKER_PATTERN = re.compile(r"\b(?:NASDAQ|NYSE|AMEX):\s*([A-Z]{1,5})\b")
_DATE_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})\b"
)
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Max paragraph length before sentence splitting kicks in.
# 300 chars (not 500) — transcript speaker turns often contain keywords and
# values in different sentences.  Splitting creates smaller segments where
# the same-sentence proximity bonus is more effective.
_MAX_PARAGRAPH_CHARS = 300


@dataclass
class DocumentMetadata:
    """Metadata extracted from transcript header."""

    company_name: str | None = None
    ticker: str | None = None
    document_date: date | None = None
    title: str | None = None


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentences, respecting common abbreviations.

    Only splits on sentence boundaries (period/exclamation/question followed
    by space and uppercase letter), skipping common abbreviations.

    Args:
        text: Text to split

    Returns:
        List of sentence strings
    """
    if len(text) <= _MAX_PARAGRAPH_CHARS:
        return [text]

    # Split on sentence boundaries
    parts = _SENTENCE_BOUNDARY.split(text)

    # Merge short fragments back together (min 50 chars per sentence)
    sentences: list[str] = []
    current = ""
    for part in parts:
        if not part.strip():
            continue
        if current and len(current) + len(part) < 100:
            current = current + " " + part
        else:
            if current:
                sentences.append(current.strip())
            current = part
    if current:
        sentences.append(current.strip())

    return sentences if sentences else [text]


def _detect_section(text: str) -> str:
    """Detect if a line indicates a section boundary."""
    for section_type, pattern in _SECTION_PATTERNS.items():
        if pattern.search(text):
            return section_type
    return ""


def _infer_speaker_role(speaker: str, content: str) -> str | None:
    """
    Infer speaker role from name/title patterns.

    Checks both the speaker name and the first line of content for role keywords.

    Args:
        speaker: Speaker name (e.g., "John Smith, CEO")
        content: First line of speaker's content

    Returns:
        Role string (e.g., "ceo", "cfo") or None
    """
    combined = f"{speaker} {content[:200]}"
    for role, pattern in _ROLE_PATTERNS.items():
        if pattern.search(combined):
            return role
    return None


def _extract_metadata(lines: list[str]) -> DocumentMetadata:
    """
    Extract metadata from transcript header lines.

    Looks at the first 20 lines for company name, ticker, and date.

    Args:
        lines: All lines of the transcript

    Returns:
        DocumentMetadata with extracted fields
    """
    meta = DocumentMetadata()
    header = "\n".join(lines[:20])

    # Extract ticker
    ticker_match = _TICKER_PATTERN.search(header)
    if ticker_match:
        meta.ticker = ticker_match.group(1)

    # Extract date
    date_match = _DATE_PATTERN.search(header)
    if date_match:
        month = _MONTH_MAP.get(date_match.group(1).lower())
        if month:
            try:
                meta.document_date = date(
                    int(date_match.group(3)),
                    month,
                    int(date_match.group(2)),
                )
            except ValueError:
                pass

    # Company name: first non-empty line (heuristic)
    for line in lines[:5]:
        stripped = line.strip()
        if stripped and not _TICKER_PATTERN.search(stripped) and len(stripped) > 3:
            meta.company_name = stripped
            break

    # Title: first line containing "earnings" or "call"
    for line in lines[:10]:
        lower = line.lower().strip()
        if any(kw in lower for kw in ("earnings", "call", "conference", "results")):
            meta.title = line.strip()
            break

    return meta


def convert_transcript_to_html(
    text: str,
    title: str = "Earnings Call Transcript",
) -> tuple[str, DocumentMetadata]:
    """
    Convert a plain-text earnings call transcript to semantic HTML.

    Key improvements over spike version:
    - Sentence splitting for long paragraphs (>300 chars)
    - Section detection with data-section-type attributes
    - Speaker role inference with data-speaker-role attributes
    - Metadata extraction from header

    Args:
        text: Raw transcript text with "Speaker Name: content" format
        title: Document title (fallback if not extracted from header)

    Returns:
        Tuple of (html_string, document_metadata)
    """
    lines = text.split("\n")
    metadata = _extract_metadata(lines)

    effective_title = metadata.title or title

    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        f"  <title>{_escape_html(effective_title)}</title>",
        '  <meta charset="utf-8">',
    ]

    if metadata.ticker:
        html_parts.append(f'  <meta name="ticker" content="{_escape_html(metadata.ticker)}">')
    if metadata.document_date:
        html_parts.append(f'  <meta name="document-date" content="{metadata.document_date.isoformat()}">')
    if metadata.company_name:
        html_parts.append(f'  <meta name="company" content="{_escape_html(metadata.company_name)}">')

    html_parts.extend([
        "</head>",
        "<body>",
        f"  <h1>{_escape_html(effective_title)}</h1>",
    ])

    current_section = "prepared_remarks"
    in_section = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for speaker attribution first (before section detection).
        # This prevents incidental mentions of "question-and-answer" or
        # "prepared remarks" inside speaker turns from incorrectly triggering
        # section changes (e.g., Operator intro: "A question-and-answer session
        # will follow the formal presentation.").
        match = _SPEAKER_PATTERN.match(line)

        # Check for section boundaries only on non-speaker lines.
        # Speaker turns may mention section keywords incidentally (e.g., Operator
        # intro text, IR disclosure boilerplate). Standalone section headers are
        # short lines with no speaker prefix.
        if not match:
            section = _detect_section(line)
            if section:
                if in_section:
                    html_parts.append("  </section>")
                current_section = section
                section_label = section.replace("_", " ").title()
                html_parts.append(f'  <section data-section-type="{section}">')
                html_parts.append(f"    <h2>{_escape_html(section_label)}</h2>")
                in_section = True
                continue

        if match:
            speaker = match.group(1).strip()
            content = match.group(2).strip()

            if not in_section:
                html_parts.append(f'  <section data-section-type="{current_section}">')
                in_section = True

            # Infer speaker role
            role = _infer_speaker_role(speaker, content)

            # Build speaker div attributes
            div_cls = "operator" if speaker.lower() == "operator" else "speaker-turn"
            role_attr = f' data-speaker-role="{role}"' if role else ""

            html_parts.append(f'    <div class="{div_cls}"{role_attr}>')
            html_parts.append(f"      <h3>{_escape_html(speaker)}</h3>")

            # Apply sentence splitting for long content
            sentences = _split_sentences(content)
            for sentence in sentences:
                html_parts.append(f"      <p>{_escape_html(sentence)}</p>")

            html_parts.append("    </div>")
        else:
            # Continuation paragraph (no speaker prefix)
            sentences = _split_sentences(line)
            for sentence in sentences:
                html_parts.append(f"    <p>{_escape_html(sentence)}</p>")

    if in_section:
        html_parts.append("  </section>")

    html_parts.extend(["</body>", "</html>"])
    return "\n".join(html_parts), metadata


def convert_file(input_path: Path, output_dir: Path) -> tuple[Path, DocumentMetadata]:
    """
    Convert a single transcript file to HTML.

    Args:
        input_path: Path to .txt transcript file
        output_dir: Directory for HTML output

    Returns:
        Tuple of (output_path, document_metadata)
    """
    text = input_path.read_text(encoding="utf-8")
    stem = input_path.stem
    title = stem.replace("_", " ")
    html, metadata = convert_transcript_to_html(text, title=title)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}.html"
    output_path.write_text(html, encoding="utf-8")

    return output_path, metadata
