"""
Presentation Converter — Convert PDF investor presentations to semantic HTML.

Produces HTML suitable for V2 pipeline ingestion with:
- Page-level <section data-section-type="presentation_slide"> elements
- Tables extracted via pdfplumber
- Text blocks wrapped in <p> tags
- Title slide detection via heuristics
- Optional image extraction (requires fitz/pymupdf or pypdfium2)

Design principles:
- Deterministic (no LLM calls)
- Fails fast on unreadable PDFs, logs warnings on per-page failures
- Image extraction is best-effort: silently skipped if library unavailable

Note on approximate number patterns (e.g., ~$20M, ~1,000):
The pipeline handles these naturally via the value binding stage.
No special pre-processing is needed here — pdfplumber text output
preserves the tilde prefix, and the number parser will capture the
numeric portion. If stricter approximate-value detection is needed in
the future, it should be added in the number parsing / value binding stage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# Metadata
# ============================================================================


class DocumentType:
    """Document source type constants for metadata."""

    PRESENTATION = "presentation"
    TRANSCRIPT = "transcript"
    SEC_FILING = "sec_filing"


@dataclass
class PresentationMetadata:
    """
    Metadata for a converted PDF presentation.

    Mirrors the DocumentMetadata pattern from transcript_converter but
    includes presentation-specific fields (source_type, source_id, page_count).
    """

    title: str | None = None
    source_type: str = DocumentType.PRESENTATION
    source_id: str = ""  # Absolute path to source PDF
    page_count: int = 0
    # Optional enrichment fields
    company_name: str | None = None
    additional_meta: dict[str, str] = field(default_factory=dict)


# ============================================================================
# HTML helpers
# ============================================================================


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _is_title_slide(lines: list[str]) -> bool:
    """
    Heuristic: decide whether a page looks like a title slide.

    Returns True if ANY of the following are met:
    - Fewer than 5 non-empty text lines (sparse = likely title page)
    - First non-empty line is ALL CAPS and contains at least one letter
      (e.g. "COMPANY NAME" or "Q3 FY26" — common on cover slides)

    Args:
        lines: Non-empty text lines extracted from the first page.

    Returns:
        True if the page looks like a title slide, False otherwise.
    """
    non_empty = [ln.strip() for ln in lines if ln.strip()]

    if not non_empty:
        return False  # Blank page — not a title slide, just empty

    # Heuristic 1: very few lines (title pages are sparse)
    if len(non_empty) < 5:
        return True

    first = non_empty[0]

    # Heuristic 2: first line is ALL CAPS with at least one letter
    # (covers "COMPANY NAME", "Q3 FY26 EARNINGS", etc.)
    if first == first.upper() and any(c.isalpha() for c in first):
        return True

    return False


def _table_to_html(rows: list[list[str | None]]) -> str:
    """
    Convert a list-of-rows (from pdfplumber) to an HTML table string.

    Args:
        rows: 2-D list where each inner list is a row of cell values.
              Cell values may be None (empty cells).

    Returns:
        HTML string for the table.
    """
    if not rows:
        return ""

    parts = ["<table>"]
    for row in rows:
        parts.append("<tr>")
        for cell in row:
            text = _escape_html(str(cell) if cell is not None else "")
            parts.append(f"<td>{text}</td>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def _extract_page_images(page: object, page_num: int, output_dir: Path) -> list[str]:
    """
    Extract images from a pdfplumber page and save them to output_dir.

    Uses fitz (PyMuPDF) as the first-choice extraction backend, falling back
    to pypdfium2 if fitz is unavailable. Silently skips if neither library
    is installed.

    Args:
        page: A pdfplumber Page object.
        page_num: 1-based page number for filename generation.
        output_dir: Directory where image files will be saved.

    Returns:
        List of saved image file paths (relative names for HTML embedding).
    """
    images_dir = output_dir / "images"
    image_refs: list[str] = []

    try:
        raw_images = getattr(page, "images", [])
        if not raw_images:
            return []
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not enumerate images on page %d: %s", page_num, exc)
        return []

    # Try fitz (PyMuPDF) first
    try:
        import fitz  # type: ignore[import-untyped]

        pdf_obj = getattr(page, "pdf", None)
        if pdf_obj is None:
            return []

        # pdfplumber wraps pdfminer; access the underlying file path via .stream
        # Fallback: open from page.pdf.filename if available
        pdf_path_attr = getattr(pdf_obj, "stream", None)
        pdf_filename = getattr(pdf_obj, "filename", None) or (
            pdf_path_attr.name if pdf_path_attr and hasattr(pdf_path_attr, "name") else None
        )
        if pdf_filename is None:
            return []

        fitz_doc = fitz.open(pdf_filename)
        try:
            fitz_page = fitz_doc[page_num - 1]

            images_dir.mkdir(parents=True, exist_ok=True)
            for img_idx, img_info in enumerate(fitz_page.get_images(full=True), start=1):
                xref = img_info[0]
                base_image = fitz_doc.extract_image(xref)
                img_bytes = base_image.get("image")
                img_ext = base_image.get("ext", "png")
                if not img_bytes:
                    continue
                fname = f"page_{page_num}_img_{img_idx}.{img_ext}"
                img_path = images_dir / fname
                img_path.write_bytes(img_bytes)
                image_refs.append(str(img_path))
        finally:
            fitz_doc.close()

        return image_refs

    except ImportError:
        pass  # fitz not available — try pypdfium2
    except Exception as exc:  # noqa: BLE001
        logger.warning("fitz image extraction failed on page %d: %s", page_num, exc)

    # Fallback: pypdfium2
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        pdf_obj = getattr(page, "pdf", None)
        pdf_path_attr = getattr(pdf_obj, "stream", None)
        pdf_filename = getattr(pdf_obj, "filename", None) or (
            pdf_path_attr.name if pdf_path_attr and hasattr(pdf_path_attr, "name") else None
        )
        if pdf_filename is None:
            return []

        pdfium_doc = pdfium.PdfDocument(pdf_filename)
        pdfium_page = pdfium_doc[page_num - 1]

        images_dir.mkdir(parents=True, exist_ok=True)
        for img_idx, obj in enumerate(pdfium_page.get_objects(), start=1):
            if obj.type != pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                continue
            bitmap = obj.get_bitmap()
            img_bytes = bitmap.to_bytes()
            fname = f"page_{page_num}_img_{img_idx}.png"
            img_path = images_dir / fname
            img_path.write_bytes(img_bytes)
            image_refs.append(str(img_path))

        return image_refs

    except ImportError:
        pass  # Neither fitz nor pypdfium2 available — skip silently
    except Exception as exc:  # noqa: BLE001
        logger.warning("pypdfium2 image extraction failed on page %d: %s", page_num, exc)

    return []


# ============================================================================
# Public API
# ============================================================================


def convert_presentation_to_html(
    pdf_path: Path,
    output_dir: Path | None = None,
) -> tuple[str, PresentationMetadata]:
    """
    Convert a PDF investor presentation to semantic HTML.

    Each page becomes a ``<section data-section-type="presentation_slide">``
    element. Tables are reconstructed as ``<table>`` elements; text blocks
    are split on newlines into ``<p>`` tags. Empty pages include an HTML
    comment to preserve page count fidelity.

    Image extraction is attempted using fitz (PyMuPDF) or pypdfium2. If
    neither library is available the step is silently skipped.

    Args:
        pdf_path: Absolute path to the source PDF file.
        output_dir: Optional directory for image output. Images are saved to
            ``output_dir/images/page_N_img_I.<ext>``. If None, image
            extraction is still attempted but paths will reference a
            temporary location (images are not saved).

    Returns:
        Tuple of (html_string, PresentationMetadata).

    Raises:
        ValueError: If pdfplumber cannot open the PDF.
    """
    try:
        import pdfplumber  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ValueError(
            f"pdfplumber is required to convert PDF presentations. "
            f"Install it with: pip install pdfplumber. Original error: {exc}"
        ) from exc

    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception as exc:
        raise ValueError(f"Failed to open PDF at '{pdf_path}': {exc}") from exc

    with pdf:
        pages = pdf.pages
        total_pages = len(pages)

        # --- Determine title from first page ---
        first_page_title: str | None = None
        if total_pages > 0:
            try:
                first_text = pages[0].extract_text() or ""
                first_lines = [ln for ln in first_text.splitlines() if ln.strip()]
                first_page_title = first_lines[0].strip() if first_lines else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not extract text from first page for title: %s", exc)

        title = first_page_title or pdf_path.stem
        metadata = PresentationMetadata(
            title=title,
            source_type=DocumentType.PRESENTATION,
            source_id=str(pdf_path),
            page_count=total_pages,
        )

        # --- Build HTML ---
        html_parts: list[str] = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            f"  <title>{_escape_html(title)}</title>",
            '  <meta charset="utf-8">',
            '  <meta name="source-type" content="presentation">',
            f'  <meta name="page-count" content="{total_pages}">',
            "</head>",
            "<body>",
        ]

        for page_num, page in enumerate(pages, start=1):
            is_first = page_num == 1
            page_text: str = ""
            page_tables: list[list[list[str | None]]] = []

            # --- Extract text and tables ---
            try:
                page_text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to extract text from page %d: %s", page_num, exc)

            try:
                page_tables = page.extract_tables() or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to extract tables from page %d: %s", page_num, exc)

            # --- Title slide detection (first page only) ---
            section_type = "presentation_slide"
            if is_first:
                first_lines = [ln for ln in page_text.splitlines() if ln.strip()]
                if _is_title_slide(first_lines):
                    section_type = "title_slide"

            # --- Open section element ---
            html_parts.append(
                f'  <section data-section-type="{section_type}"'
                f' data-page="{page_num}"'
                f' data-page-count="{total_pages}">'
            )

            # --- Empty page ---
            text_stripped = page_text.strip()
            if not text_stripped and not page_tables:
                html_parts.append("    <!-- empty page -->")
                html_parts.append("  </section>")
                continue

            # --- Tables first (structural content) ---
            for table_rows in page_tables:
                if table_rows:
                    html_parts.append("    " + _table_to_html(table_rows))

            # --- Text blocks ---
            if text_stripped:
                for line in page_text.splitlines():
                    line = line.strip()
                    if line:
                        html_parts.append(f"    <p>{_escape_html(line)}</p>")

            # --- Images (best-effort) ---
            if output_dir is not None:
                img_paths = _extract_page_images(page, page_num, output_dir)
                for img_path in img_paths:
                    rel = Path(img_path).name
                    html_parts.append(
                        f'    <img src="images/{_escape_html(rel)}" alt="Slide {page_num} image">'
                    )

            html_parts.append("  </section>")

        html_parts.extend(["</body>", "</html>"])

    return "\n".join(html_parts), metadata
