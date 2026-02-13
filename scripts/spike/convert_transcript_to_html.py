#!/usr/bin/env python3
"""
Convert earnings call transcript text files to HTML for V2 pipeline processing.

Wraps plain-text transcripts in semantic HTML:
- Speaker names → <h3> headings
- Paragraphs → <p> tags
- Sections (Prepared Remarks, Q&A) → <section> with class
- Operator lines → <div class="operator">

This is a spike script — not production code.
"""

import re
from pathlib import Path


def detect_section(text: str) -> str:
    """Detect if a line indicates a section boundary."""
    text_lower = text.lower().strip()
    if "question-and-answer" in text_lower or "q&a" in text_lower:
        return "qa"
    if "prepared remarks" in text_lower:
        return "prepared_remarks"
    if "operator instructions" in text_lower:
        return "operator_instructions"
    return ""


def convert_transcript_to_html(text: str, title: str = "Earnings Call Transcript") -> str:
    """
    Convert a plain-text earnings call transcript to semantic HTML.

    Args:
        text: Raw transcript text with "Speaker Name: content" format
        title: Document title

    Returns:
        HTML string
    """
    lines = text.split("\n")
    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        f"  <title>{title}</title>",
        '  <meta charset="utf-8">',
        "</head>",
        "<body>",
        f"  <h1>{title}</h1>",
    ]

    current_section = "prepared_remarks"
    in_section = False
    speaker_pattern = re.compile(r"^([A-Z][a-zA-Z\s\-'\.]+?):\s*(.+)", re.DOTALL)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for section boundaries
        section = detect_section(line)
        if section:
            if in_section:
                html_parts.append("  </section>")
            current_section = section
            section_label = section.replace("_", " ").title()
            html_parts.append(f'  <section class="{section}">')
            html_parts.append(f"    <h2>{section_label}</h2>")
            in_section = True
            continue

        # Check for speaker attribution
        match = speaker_pattern.match(line)
        if match:
            speaker = match.group(1).strip()
            content = match.group(2).strip()

            if not in_section:
                html_parts.append(f'  <section class="{current_section}">')
                in_section = True

            # Operator gets special treatment
            if speaker.lower() == "operator":
                html_parts.append(f'    <div class="operator">')
                html_parts.append(f"      <h3>{speaker}</h3>")
                html_parts.append(f"      <p>{_escape_html(content)}</p>")
                html_parts.append(f"    </div>")
            else:
                html_parts.append(f'    <div class="speaker-turn">')
                html_parts.append(f"      <h3>{_escape_html(speaker)}</h3>")
                html_parts.append(f"      <p>{_escape_html(content)}</p>")
                html_parts.append(f"    </div>")
        else:
            # Continuation paragraph (no speaker prefix)
            html_parts.append(f"    <p>{_escape_html(line)}</p>")

    if in_section:
        html_parts.append("  </section>")

    html_parts.extend(["</body>", "</html>"])
    return "\n".join(html_parts)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def convert_file(input_path: Path, output_dir: Path) -> Path:
    """Convert a single transcript file to HTML."""
    text = input_path.read_text(encoding="utf-8")
    stem = input_path.stem
    title = stem.replace("_", " ")
    html = convert_transcript_to_html(text, title=title)
    output_path = output_dir / f"{stem}.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main():
    """Convert all transcript text files to HTML."""
    root = Path(__file__).resolve().parent.parent.parent
    transcripts_dir = root / "data" / "spike_samples" / "transcripts"
    html_dir = root / "data" / "spike_samples" / "transcripts_html"
    html_dir.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(transcripts_dir.glob("*.txt"))
    print(f"Converting {len(txt_files)} transcript files to HTML...")

    for txt_file in txt_files:
        html_path = convert_file(txt_file, html_dir)
        html_size = html_path.stat().st_size
        print(f"  {txt_file.name} -> {html_path.name} ({html_size:,} bytes)")

    print(f"\nAll files written to: {html_dir}")


if __name__ == "__main__":
    main()
