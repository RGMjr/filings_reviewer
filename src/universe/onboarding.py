"""
Onboarding library for SEC filing batch ingestion.

Pure functions that encapsulate discovery, gap detection, volume classification,
and the onboard execution loop.  The CLI (scripts/onboard_tickers.py) and the
future web blueprint both call this module — neither duplicates logic here.

Public API
----------
resolve_criteria(criteria)           -> ResolvedQuery
discover(db, query)                  -> DiscoveryResult
detect_universe_gaps(db, query)      -> list[Gap]
count_reviewer_work(db, filing_ids)  -> dict[int, tuple[int, int]]
classify_volume(count)               -> VolumeBand
onboard(db, candidates, reextract_decisions, progress_cb) -> RunSummary
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Volume classification
# ---------------------------------------------------------------------------

THRESHOLD_SOFT_WARN = 50
THRESHOLD_HARD_WARN = 200
THRESHOLD_REFINE = 500
THRESHOLD_BLOCK = 1000


class VolumeBand(str, Enum):
    """Volume classification for a candidate set."""

    OK = "ok"  # < 50
    SOFT_WARN = "soft_warn"  # 50 – 199
    HARD_WARN = "hard_warn"  # 200 – 499
    REFINE = "refine"  # 500 – 999
    BLOCK = "block"  # >= 1000


def classify_volume(count: int) -> VolumeBand:
    """Return the VolumeBand for *count* total candidates.

    Thresholds (inclusive lower bound):
        OK        : 0 – 49
        SOFT_WARN : 50 – 199
        HARD_WARN : 200 – 499
        REFINE    : 500 – 999
        BLOCK     : 1000+
    """
    if count < THRESHOLD_SOFT_WARN:
        return VolumeBand.OK
    if count < THRESHOLD_HARD_WARN:
        return VolumeBand.SOFT_WARN
    if count < THRESHOLD_REFINE:
        return VolumeBand.HARD_WARN
    if count < THRESHOLD_BLOCK:
        return VolumeBand.REFINE
    return VolumeBand.BLOCK


# ---------------------------------------------------------------------------
# Shared constants — business logic owned here, re-exported by CLI
# ---------------------------------------------------------------------------

FORM_TYPE_BUNDLES: dict[str, list[str]] = {
    "s1f1": ["S-1", "S-1/A", "F-1", "F-1/A"],
    "10k": ["10-K", "10-K/A"],
    "8k": ["8-K", "8-K/A"],
    "S-1": ["S-1"],
    "S-1/A": ["S-1/A"],
    "F-1": ["F-1"],
    "F-1/A": ["F-1/A"],
    "10-K": ["10-K"],
    "10-K/A": ["10-K/A"],
    "8-K": ["8-K"],
    "8-K/A": ["8-K/A"],
}

# Form types where is_in_scope_phase1 is meaningful as a filter. For other
# form types (10-K, etc.) the Phase 1 gate is not applied — see runbook
# "10-K onboarding semantics".
S1F1_FORMS = {"S-1", "S-1/A", "F-1", "F-1/A"}


# ---------------------------------------------------------------------------
# Candidate dataclass
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    filing_id: int
    cik: str
    ticker: str | None
    company_name: str
    form_type: str
    filing_date: str
    industry_code: str | None
    accession_number: str
    primary_doc_url: str
    txt_url: str | None
    already_extracted: bool
    extracted_at: str | None


# ---------------------------------------------------------------------------
# Industry map
# ---------------------------------------------------------------------------

_DEFAULT_YAML_PATH = Path(__file__).parent.parent.parent / "config" / "industry_sic_codes.yaml"


def load_industry_map(yaml_path: Path = _DEFAULT_YAML_PATH) -> dict[str, Any]:
    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}
    industries = data.get("industries") or {}
    aliases = data.get("aliases") or {}
    for name, entry in industries.items():
        codes = entry.get("sic_codes") or []
        for code in codes:
            if not (isinstance(code, str) and len(code) == 4 and code.isdigit()):
                raise ValueError(
                    f"Invalid SIC code {code!r} under industry {name!r} in {yaml_path}: "
                    "must be a 4-digit numeric string"
                )
    return {"industries": industries, "aliases": aliases}


def resolve_industry(name: str, industry_map: dict[str, Any]) -> tuple[str, list[str]]:
    """Resolve an industry name (including aliases) to (canonical, sic_codes)."""
    key = name.lower().strip()
    aliases: dict[str, str] = industry_map["aliases"]
    industries: dict[str, Any] = industry_map["industries"]
    canonical = aliases.get(key, key)
    if canonical not in industries:
        known = sorted(list(industries.keys()) + list(aliases.keys()))
        raise ValueError(
            f"Unknown industry {name!r}. Known: {', '.join(known)}. "
            f"Add mappings in {_DEFAULT_YAML_PATH}."
        )
    return canonical, list(industries[canonical]["sic_codes"])


# ---------------------------------------------------------------------------
# Arg parsing helpers
# ---------------------------------------------------------------------------


def parse_year_arg(raw: str) -> tuple[int, int]:
    """Accept 'YYYY' or 'YYYY-YYYY'. Returns (min, max) inclusive."""
    if "-" in raw:
        lo, hi = raw.split("-", 1)
        y_lo, y_hi = int(lo), int(hi)
        if y_lo > y_hi:
            raise argparse.ArgumentTypeError(f"Year range {raw}: min > max")
        return y_lo, y_hi
    y = int(raw)
    return y, y


def resolve_form_types(raw: str) -> list[str]:
    if raw not in FORM_TYPE_BUNDLES:
        raise argparse.ArgumentTypeError(
            f"Unknown form type {raw!r}. Known: {', '.join(FORM_TYPE_BUNDLES)}"
        )
    return FORM_TYPE_BUNDLES[raw]


# ---------------------------------------------------------------------------
# Discovery SQL helpers
# ---------------------------------------------------------------------------

_DISCOVERY_SQL_BASE = """
SELECT
    f.filing_id,
    c.cik,
    c.ticker,
    c.company_name,
    f.form_type,
    f.filing_date,
    c.industry_code,
    f.accession_number,
    f.sec_html_url AS primary_doc_url,
    f.sec_txt_url AS txt_url,
    (v.doc_id IS NOT NULL) AS already_extracted,
    v.created_at AS extracted_at
FROM filings f
JOIN companies c ON c.company_id = f.company_id
LEFT JOIN v2_documents v ON v.filing_id = f.filing_id
WHERE f.form_type = ANY(%(form_types)s)
  AND EXTRACT(YEAR FROM f.filing_date) BETWEEN %(year_min)s AND %(year_max)s
"""

_INDUSTRY_GATE = "  AND c.industry_code = ANY(%(sic_codes)s)\n"

_PHASE1_GATE = "  AND f.is_in_scope_phase1 = TRUE\n"

_DISCOVERY_ORDER = "ORDER BY f.filing_date DESC, c.company_name ASC\n"

_LIMIT_CLAUSE = "LIMIT %(limit)s\n"

# Exposed for tests and backward compatibility. Equivalent to the original
# S-1/F-1-gated query (Phase-1 filter included, industry filter present).
DISCOVERY_SQL = _DISCOVERY_SQL_BASE + _INDUSTRY_GATE + _PHASE1_GATE + _DISCOVERY_ORDER


def _build_discovery_sql(
    form_types: list[str],
    sic_codes: list[str],
    limit: int | None = None,
) -> str:
    """Include the Phase-1 gate only when at least one S-1/F-1 form is requested.

    For 10-K-only (or other non-S-1/F-1) queries, Phase-1 filter doesn't apply:
    those filings intentionally land with is_in_scope_phase1=FALSE.

    Include the industry (SIC-code) clause only when ``sic_codes`` is non-empty.
    Empty SIC list means the caller is filtering by company name alone; emitting
    ``= ANY(ARRAY[]::text[])`` would return zero rows.

    Append a LIMIT clause when ``limit`` is set; the bound parameter is named
    ``limit`` so the caller must include it in the query params dict.
    """
    include_phase1 = bool(S1F1_FORMS & set(form_types))
    return (
        _DISCOVERY_SQL_BASE
        + (_INDUSTRY_GATE if sic_codes else "")
        + (_PHASE1_GATE if include_phase1 else "")
        + _DISCOVERY_ORDER
        + (_LIMIT_CLAUSE if limit else "")
    )


def discover_candidates(
    db: DatabaseAdapter,
    form_types: list[str],
    year_min: int,
    year_max: int,
    sic_codes: list[str],
    limit: int | None = None,
) -> list[Candidate]:
    params: dict[str, Any] = {
        "form_types": form_types,
        "year_min": year_min,
        "year_max": year_max,
    }
    if sic_codes:
        params["sic_codes"] = sic_codes
    if limit:
        params["limit"] = limit
    rows = db.query(
        _build_discovery_sql(form_types, sic_codes, limit=limit),
        params,
    )
    return [
        Candidate(
            filing_id=r["filing_id"],
            cik=r["cik"],
            ticker=r.get("ticker"),
            company_name=r["company_name"],
            form_type=r["form_type"],
            filing_date=str(r["filing_date"]),
            industry_code=r.get("industry_code"),
            accession_number=r["accession_number"],
            primary_doc_url=r["primary_doc_url"],
            txt_url=r.get("txt_url"),
            already_extracted=bool(r["already_extracted"]),
            extracted_at=str(r["extracted_at"]) if r.get("extracted_at") else None,
        )
        for r in rows
    ]


REVIEW_DECISIONS_SQL = """
SELECT COUNT(rd.decision_id) AS decision_count,
       COUNT(DISTINCT rd.reviewer_id) AS reviewer_count
FROM v2_review_decisions rd
JOIN v2_metric_facts f ON f.fact_id = rd.fact_id
WHERE f.filing_id = %(filing_id)s
"""


def count_review_decisions(db: DatabaseAdapter, filing_id: int) -> tuple[int, int]:
    """Return (decision_count, reviewer_count) for a single filing_id."""
    rows = db.query(REVIEW_DECISIONS_SQL, {"filing_id": filing_id})
    if not rows:
        return 0, 0
    r = rows[0]
    return int(r["decision_count"] or 0), int(r["reviewer_count"] or 0)


# ---------------------------------------------------------------------------
# ResolvedQuery — the expanded, normalised query object
# ---------------------------------------------------------------------------


@dataclass
class ResolvedQuery:
    """Fully expanded, DB-ready query parameters."""

    sic_codes: list[str]  # 4-digit numeric strings
    form_types: list[str]  # e.g. ["S-1", "S-1/A", "8-K"]
    year_min: int
    year_max: int
    include_amendments: bool = True
    company_name_ilike: str | None = None  # None = no filter
    limit: int | None = None  # None = no cap


def resolve_criteria(criteria: dict[str, Any]) -> ResolvedQuery:
    """Expand human-facing criteria into a normalised ResolvedQuery.

    Accepted *criteria* keys
    ------------------------
    industries : list[str]
        Industry names resolved via industry_sic_codes.yaml.  Each must be a
        known industry name or alias.  May be empty.
    sic_codes : str | list[str]
        Comma-separated 4-digit SIC codes (e.g. "5411,7389") or a list of
        4-digit strings.  When both *industries* and *sic_codes* are supplied
        the resulting SIC sets are unioned.
    year : str
        "YYYY" or "YYYY-YYYY" (inclusive range).  Required.
    form_types : list[str]
        Bundle keys or individual form-type strings (e.g. ["s1f1", "8k"]).
        Resolved via FORM_TYPE_BUNDLES.
    include_amendments : bool
        If False, strip any form type ending in "/A".  Default True.
    company_name_ilike : str | None
        Optional ILIKE pattern for company name filtering.  E.g. "% Inc." or
        "Acme%".
    limit : int | str | None
        Optional cap on the number of candidates returned by ``discover()``.
        Applied as SQL ``LIMIT`` against the discovery query (after ORDER BY,
        before the company-name post-filter). Must be 1–5000 if set; ``None``
        or empty string means no cap. Strings are coerced to int; non-numeric
        values raise ``ValueError``.

    Raises
    ------
    ValueError
        On unrecognised industry name, invalid SIC code, bad year string,
        empty resolved form-types list, or when no narrowing criterion is
        supplied (industry, SIC code, *and* company-name filter all empty).
    """

    # --- SIC codes from industry picker ---
    sic_set: set[str] = set()
    for ind_name in criteria.get("industries") or []:
        ind_map = load_industry_map(_DEFAULT_YAML_PATH)
        _, codes = resolve_industry(ind_name, ind_map)
        sic_set.update(codes)

    # --- Direct SIC code entry (comma-separated string or list) ---
    raw_sic = criteria.get("sic_codes") or []
    if isinstance(raw_sic, str):
        raw_sic = [s.strip() for s in raw_sic.split(",") if s.strip()]
    for code in raw_sic:
        if not (isinstance(code, str) and len(code) == 4 and code.isdigit()):
            raise ValueError(f"Invalid SIC code {code!r}: must be a 4-digit numeric string")
        sic_set.add(code)

    if not sic_set and not (criteria.get("company_name_ilike") or "").strip():
        raise ValueError("Provide at least one of: industry, SIC code, or company name filter")

    # --- Year range ---
    raw_year = criteria.get("year")
    if not raw_year:
        raise ValueError("'year' is required in criteria (YYYY or YYYY-YYYY)")
    year_min, year_max = parse_year_arg(str(raw_year))

    # --- Form types ---
    form_type_set: list[str] = []
    seen: set[str] = set()
    for ft_key in criteria.get("form_types") or ["s1f1"]:
        if ft_key in FORM_TYPE_BUNDLES:
            for ft in FORM_TYPE_BUNDLES[ft_key]:
                if ft not in seen:
                    form_type_set.append(ft)
                    seen.add(ft)
        else:
            # Treat as a literal form-type string
            if ft_key not in seen:
                form_type_set.append(ft_key)
                seen.add(ft_key)

    include_amendments = bool(criteria.get("include_amendments", True))
    if not include_amendments:
        form_type_set = [ft for ft in form_type_set if not ft.endswith("/A")]

    if not form_type_set:
        raise ValueError("Resolved form_types list is empty after filtering amendments")

    raw_limit = criteria.get("limit")
    limit: int | None = None
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid limit {raw_limit!r}: must be a positive integer") from exc
        if not (1 <= limit <= 5000):
            raise ValueError(f"Invalid limit {limit}: must be between 1 and 5000")

    return ResolvedQuery(
        sic_codes=sorted(sic_set),
        form_types=form_type_set,
        year_min=year_min,
        year_max=year_max,
        include_amendments=include_amendments,
        company_name_ilike=criteria.get("company_name_ilike") or None,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

_YEARS_IN_FILINGS_BASE = """
SELECT DISTINCT EXTRACT(YEAR FROM f.filing_date)::int AS yr,
                f.form_type
FROM filings f
JOIN companies c ON c.company_id = f.company_id
WHERE f.form_type = ANY(%(form_types)s)
  AND EXTRACT(YEAR FROM f.filing_date) BETWEEN %(year_min)s AND %(year_max)s
"""

_YEARS_IN_FILINGS_INDUSTRY_GATE = "  AND c.industry_code = ANY(%(sic_codes)s)\n"

# Backwards-compatible alias preserving the SIC-gated form for callers that
# import the constant directly.
_YEARS_IN_FILINGS_SQL = _YEARS_IN_FILINGS_BASE + _YEARS_IN_FILINGS_INDUSTRY_GATE


@dataclass
class Gap:
    """A (year, form_type) combination that has zero rows in the filings table."""

    year: int
    form_type: str


def detect_universe_gaps(db: DatabaseAdapter, query: ResolvedQuery) -> list[Gap]:
    """Return (year, form_type) pairs that have no rows in ``filings``.

    This tells the caller which (year, form_type) combos need a
    ``populate`` run before discovery will find anything.

    When ``query.sic_codes`` is empty (company-name-only criteria), the SIC
    clause is omitted entirely. Otherwise an empty SIC list would short-circuit
    the query to zero rows and the gap banner would never appear for
    name-filtered searches.
    """
    sql = _YEARS_IN_FILINGS_BASE + (_YEARS_IN_FILINGS_INDUSTRY_GATE if query.sic_codes else "")
    params: dict[str, Any] = {
        "form_types": query.form_types,
        "year_min": query.year_min,
        "year_max": query.year_max,
    }
    if query.sic_codes:
        params["sic_codes"] = query.sic_codes
    rows = db.query(sql, params)
    present: set[tuple[int, str]] = {(r["yr"], r["form_type"]) for r in rows}

    gaps: list[Gap] = []
    for year in range(query.year_min, query.year_max + 1):
        for form_type in query.form_types:
            if (year, form_type) not in present:
                gaps.append(Gap(year=year, form_type=form_type))
    return gaps


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_BATCH_REVIEW_DECISIONS_SQL = """
SELECT f.filing_id,
       COUNT(rd.decision_id)          AS decision_count,
       COUNT(DISTINCT rd.reviewer_id) AS reviewer_count
FROM v2_metric_facts f
LEFT JOIN v2_review_decisions rd ON rd.fact_id = f.fact_id
WHERE f.filing_id = ANY(%(filing_ids)s)
GROUP BY f.filing_id
"""


def count_reviewer_work(
    db: DatabaseAdapter,
    filing_ids: Sequence[int],
) -> dict[int, tuple[int, int]]:
    """Return ``{filing_id: (decision_count, reviewer_count)}`` for each id.

    Filing IDs with no facts / no decisions are included with (0, 0).
    Uses a single batched query instead of N per-filing round-trips.
    """
    if not filing_ids:
        return {}

    rows = db.query(
        _BATCH_REVIEW_DECISIONS_SQL,
        {"filing_ids": list(filing_ids)},
    )
    result: dict[int, tuple[int, int]] = {fid: (0, 0) for fid in filing_ids}
    for r in rows:
        fid = int(r["filing_id"])
        result[fid] = (
            int(r["decision_count"] or 0),
            int(r["reviewer_count"] or 0),
        )
    return result


@dataclass
class DiscoveryResult:
    """Output of ``discover()``: candidate lists plus gap information."""

    new: list[Any]  # list[Candidate]
    already_extracted: list[Any]  # list[Candidate]
    gaps: list[Gap]

    @property
    def total(self) -> int:
        return len(self.new) + len(self.already_extracted)


def discover(db: DatabaseAdapter, query: ResolvedQuery) -> DiscoveryResult:
    """Run discovery against DB and detect universe gaps.

    Wraps ``discover_candidates`` and adds gap detection so callers can
    present a one-click populate prompt.

    The SQL ``LIMIT`` is applied *before* the company-name post-filter, so a
    user combining limit + company_name_ilike may see fewer rows than the
    limit. This matches the behaviour the volume banner expects: the limit
    is a cap on the result set the reviewer sees, not a quota to fill.
    """
    candidates = discover_candidates(
        db,
        form_types=query.form_types,
        year_min=query.year_min,
        year_max=query.year_max,
        sic_codes=query.sic_codes,
        limit=query.limit,
    )

    # Apply optional company-name filter (ILIKE equivalent — Python side for
    # simplicity; discovery query is the expensive DB op, not this filter).
    if query.company_name_ilike:
        pattern = query.company_name_ilike.lower().replace("%", "")
        candidates = [c for c in candidates if pattern in c.company_name.lower()]

    new = [c for c in candidates if not c.already_extracted]
    already = [c for c in candidates if c.already_extracted]
    gaps = detect_universe_gaps(db, query)

    return DiscoveryResult(new=new, already_extracted=already, gaps=gaps)


# ---------------------------------------------------------------------------
# Onboard execution loop
# ---------------------------------------------------------------------------


@dataclass
class FilingEvent:
    """Progress event emitted during onboard execution."""

    filing_id: int
    status: str  # "started" | "succeeded" | "failed" | "skipped_reviewed"
    message: str = ""


@dataclass
class RunSummary:
    """Summary returned by ``onboard()``."""

    succeeded: int = 0
    failed: int = 0
    skipped_reviewed: int = 0
    events: list[FilingEvent] = field(default_factory=list)


def load_candidates_by_filing_ids(
    db: DatabaseAdapter,
    filing_ids: Sequence[int],
) -> list[Candidate]:
    """Load Candidate objects for the given filing IDs.

    Used by the batch runner to reconstruct Candidate objects from the
    filing_id list stored in v2_ingest_batch_filings.  Returns an empty
    list when *filing_ids* is empty.
    """
    if not filing_ids:
        return []

    sql = """
SELECT
    f.filing_id,
    c.cik,
    c.ticker,
    c.company_name,
    f.form_type,
    f.filing_date,
    c.industry_code,
    f.accession_number,
    f.sec_html_url  AS primary_doc_url,
    f.sec_txt_url   AS txt_url,
    (v.doc_id IS NOT NULL) AS already_extracted,
    v.created_at    AS extracted_at
FROM filings f
JOIN companies c ON c.company_id = f.company_id
LEFT JOIN v2_documents v ON v.filing_id = f.filing_id
WHERE f.filing_id = ANY(%(filing_ids)s)
ORDER BY f.filing_date DESC, c.company_name ASC
"""
    rows = db.query(sql, {"filing_ids": list(filing_ids)})
    return [
        Candidate(
            filing_id=r["filing_id"],
            cik=r["cik"],
            ticker=r.get("ticker"),
            company_name=r["company_name"],
            form_type=r["form_type"],
            filing_date=str(r["filing_date"]),
            industry_code=r.get("industry_code"),
            accession_number=r["accession_number"],
            primary_doc_url=r["primary_doc_url"],
            txt_url=r.get("txt_url"),
            already_extracted=bool(r["already_extracted"]),
            extracted_at=str(r["extracted_at"]) if r.get("extracted_at") else None,
        )
        for r in rows
    ]


def onboard(
    db: DatabaseAdapter,
    candidates: list[Any],  # list[Candidate]
    reextract_decisions: dict[int, bool],
    progress_cb: Callable[[FilingEvent], None] | None = None,
    *,
    abort_check: Callable[[], bool] | None = None,
    storage_root: str = "data/filings",
    user_agent: str = "CMASB Filings Analyzer rgmarkey@gmail.com",
    skip_txt: bool = False,
) -> RunSummary:
    """Execute the onboard pipeline for a resolved candidate list.

    Parameters
    ----------
    db:
        Live DatabaseAdapter.
    candidates:
        List of ``Candidate`` objects (from ``discover_candidates`` or
        ``DiscoveryResult.new`` / ``DiscoveryResult.already_extracted``).
    reextract_decisions:
        ``{filing_id: True}`` — caller provides decisions that were previously
        gathered via interactive prompts (CLI) or checkbox UI (web).
        Filing IDs absent from this map that are already_extracted are skipped.
        A ``True`` value for a filing that has reviewer work is allowed — the
        caller is responsible for confirming that separately before passing it
        in.
    progress_cb:
        Optional callback invoked with a ``FilingEvent`` for every status
        change.  Callers may use this to update SSE streams, DB batch-filing
        rows, or log output.
    abort_check:
        Optional callable that returns ``True`` when the caller wants the
        loop to stop early (e.g. batch cancellation).  Checked **between**
        candidate iterations — the in-flight filing always completes.  When
        the check fires the function returns immediately without emitting any
        additional events; the caller is responsible for marking remaining
        queued items as cancelled.
    storage_root:
        Directory root for FilingFetcher cached downloads.
    user_agent:
        HTTP User-Agent for SEC API requests.
    skip_txt:
        If True, skip TXT file download (faster; uses HTML only).

    Returns
    -------
    RunSummary
        Final counts.  Events list mirrors every ``progress_cb`` emission.
    """
    from src.extraction_v2.exceptions import ReviewedFilingError
    from src.extraction_v2.persistence import V2PersistenceAdapter
    from src.extraction_v2.pipeline import process_filing
    from src.filing_fetcher.filing_fetcher import FilingFetcher
    from src.infra.sec_client import FilingMetadata, SECClient

    sec_client = SECClient(user_agent=user_agent)
    fetcher = FilingFetcher(
        storage_root=storage_root,
        user_agent=user_agent,
        db=db,
        sec_client=sec_client,
    )
    persistence = V2PersistenceAdapter(db)

    # Build execution list: all NEW + caller-approved re-extracts.
    #
    # The processing gate is c.already_extracted (presence of a v2_documents
    # row), NOT v2_ingest_batch_filings.current_status. To force re-extraction
    # of an already-persisted filing the caller must pass
    # reextract_decisions[filing_id]=True — flipping current_status='queued'
    # alone is silently a no-op here. _run_onboard
    # (src/universe/onboarding_runner.py) builds reextract_decisions from each
    # row's initial_bucket ('reextract' / 'reextract_reviewed').
    to_process: list[tuple[Any, bool]] = []
    for c in candidates:
        if not c.already_extracted:
            to_process.append((c, False))
        elif reextract_decisions.get(c.filing_id):
            to_process.append((c, True))

    summary = RunSummary()

    def _emit(event: FilingEvent) -> None:
        summary.events.append(event)
        if progress_cb is not None:
            progress_cb(event)

    for c, force in to_process:
        _emit(FilingEvent(filing_id=c.filing_id, status="started"))

        md = FilingMetadata(
            cik=c.cik,
            company_name=c.company_name,
            form_type=c.form_type,
            filing_date=c.filing_date,
            accession_number=c.accession_number,
            primary_doc_url=c.primary_doc_url,
            txt_url=c.txt_url,
            ticker=c.ticker,
        )
        logger.info(
            "Fetching filing_id=%d cik=%s accession=%s …",
            c.filing_id,
            c.cik,
            c.accession_number,
        )
        content = fetcher.fetch_filing(md, fetch_txt=not skip_txt)
        if content is None or content.html_path is None:
            msg = f"Fetch failed for filing_id={c.filing_id}"
            logger.error(msg)
            _emit(FilingEvent(filing_id=c.filing_id, status="failed", message=msg))
            summary.failed += 1
            continue

        try:
            doc_date = date.fromisoformat(c.filing_date) if c.filing_date else None
            result = process_filing(
                html_path=content.html_path,
                filing_id=c.filing_id,
                cik=c.cik,
                accession_number=c.accession_number,
                document_date=doc_date,
            )
            persistence.persist_pipeline_result(
                result,
                c.filing_id,
                ticker=c.ticker,
                document_date=doc_date,
                force=force,
            )
            summary.succeeded += 1
            _emit(
                FilingEvent(
                    filing_id=c.filing_id,
                    status="succeeded",
                    message=f"{result.fact_count} facts persisted (force={force})",
                )
            )
            logger.info(
                "filing_id=%d: %d facts persisted (force=%s)",
                c.filing_id,
                result.fact_count,
                force,
            )
        except ReviewedFilingError as e:
            msg = (
                f"filing_id={c.filing_id} blocked by ReviewedFilingError: {e} "
                "(see .claude/rules/v2-pipeline.md)"
            )
            logger.error(msg)
            _emit(FilingEvent(filing_id=c.filing_id, status="failed", message=str(e)))
            summary.failed += 1
        except Exception as e:  # noqa: BLE001
            msg = f"filing_id={c.filing_id} failed: {e}"
            logger.error(msg, exc_info=True)
            _emit(FilingEvent(filing_id=c.filing_id, status="failed", message=str(e)))
            summary.failed += 1

        # Check between filings — in-flight filing always completes first.
        if abort_check is not None and abort_check():
            logger.info("onboard: abort_check fired — stopping early")
            break

    return summary


# ---------------------------------------------------------------------------
# Universe-state aggregations — power the /ingest/ form facet cascade.
# Year ↔ industry counts so the operator only sees slices that actually have
# rows in the universe. See docs/operations/TICKER_ONBOARDING.md.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YearCount:
    """A year present in `filings`, with the universe total and the count of
    those rows still pending extraction (no row in v2_documents).
    """

    year: int
    total: int  # total filings in the universe slice (was `count` pre-Phase-2d)
    pending: int = 0  # subset with no v2_documents row → un-extracted


@dataclass(frozen=True)
class IndustryCount:
    """A YAML industry entry with the universe total and pending-extraction
    count of filings whose company SIC code is in that industry's sic_codes
    list."""

    key: str  # canonical industry name from YAML (e.g. "biotech")
    label: str  # humanised (e.g. "Biotech") — same shape as `_industry_options()`
    total: int  # total filings in the universe slice
    pending: int = 0  # subset un-extracted (no v2_documents row)


def _industry_label(key: str) -> str:
    """Match the legacy `_industry_options()` label format."""
    return key.replace("_", " ").title()


_YEAR_COUNTS_SQL = """
SELECT EXTRACT(YEAR FROM f.filing_date)::int AS yr,
       COUNT(*)::int AS total,
       COUNT(*) FILTER (WHERE v.doc_id IS NULL)::int AS pending
FROM filings f
JOIN companies c ON c.company_id = f.company_id
LEFT JOIN v2_documents v ON v.filing_id = f.filing_id
WHERE 1=1
"""

_YEAR_COUNTS_INDUSTRY_GATE = "  AND c.industry_code = ANY(%(sic_codes)s)\n"

_YEAR_COUNTS_FORM_TYPE_GATE = "  AND f.form_type = ANY(%(form_types)s)\n"

_YEAR_COUNTS_PHASE1_GATE = "  AND f.is_in_scope_phase1 = TRUE\n"

_YEAR_COUNTS_TAIL = """GROUP BY yr
ORDER BY yr DESC
"""


def query_universe_year_counts(
    db: DatabaseAdapter,
    *,
    sic_codes: list[str] | None = None,
    form_types: list[str] | None = None,
) -> list[YearCount]:
    """Return distinct years in `filings` with universe total + pending counts.

    Each row carries:
        total   — filings in the slice (was the only count pre-Phase-2d).
        pending — subset with no `v2_documents` row (i.e. un-extracted).

    Optional ``sic_codes`` restricts to filings whose
    ``companies.industry_code`` IS IN the list. ``form_types`` is a list of
    canonical form-type strings (e.g. ["S-1", "F-1/A", "10-K"]); the caller
    is responsible for resolving bundle keys via ``FORM_TYPE_BUNDLES``.
    None or empty for either means no filter on that axis.

    The Phase-1 in-scope gate (``is_in_scope_phase1 = TRUE``) is applied
    when ``form_types`` intersects ``S1F1_FORMS`` — same rule as
    ``_build_discovery_sql`` — so facet counts agree with what Preview
    would actually surface for that slice.

    Years with no rows are not returned.
    """
    include_phase1 = bool(form_types and (S1F1_FORMS & set(form_types)))
    sql = _YEAR_COUNTS_SQL
    params: dict[str, Any] = {}
    if sic_codes:
        sql += _YEAR_COUNTS_INDUSTRY_GATE
        params["sic_codes"] = list(sic_codes)
    if form_types:
        sql += _YEAR_COUNTS_FORM_TYPE_GATE
        params["form_types"] = list(form_types)
    if include_phase1:
        sql += _YEAR_COUNTS_PHASE1_GATE
    sql += _YEAR_COUNTS_TAIL
    rows = db.query(sql, params)
    return [
        YearCount(year=int(r["yr"]), total=int(r["total"]), pending=int(r["pending"])) for r in rows
    ]


_INDUSTRY_COUNTS_SQL_TEMPLATE = """
SELECT industry_sic.industry_key,
       industry_sic.industry_label,
       COUNT(f.filing_id)::int AS total,
       COUNT(f.filing_id) FILTER (WHERE f.filing_id IS NOT NULL AND v.doc_id IS NULL)::int AS pending
FROM unnest(
    %(keys)s::text[],
    %(labels)s::text[],
    %(sics)s::text[]
) AS industry_sic(industry_key, industry_label, sic)
LEFT JOIN companies c ON c.industry_code = industry_sic.sic
LEFT JOIN filings  f ON f.company_id = c.company_id
    {filing_join_extra}
LEFT JOIN v2_documents v ON v.filing_id = f.filing_id
GROUP BY industry_sic.industry_key, industry_sic.industry_label
ORDER BY industry_sic.industry_label
"""


def query_universe_industry_counts(
    db: DatabaseAdapter,
    industry_map: dict[str, Any],
    *,
    years: list[int] | None = None,
    form_types: list[str] | None = None,
) -> list[IndustryCount]:
    """For every industry in *industry_map*, return its filing total + pending.

    Each row carries:
        total   — filings in the slice (was `count` pre-Phase-2d).
        pending — subset with no `v2_documents` row (i.e. un-extracted).

    Implementation: a single SQL query joins filings → companies → an inline
    relation built from ``unnest()`` of three parallel arrays
    ``(industry_key, industry_label, sic)`` derived from the YAML, with a
    LEFT JOIN to ``v2_documents`` so the COUNT FILTER can compute pending.

    SIC-code overlap across industries is handled cleanly: a filing whose
    ``companies.industry_code`` matches multiple industries contributes one
    row toward each (the unnest gives one tuple per (industry, sic) pair).

    Optional ``years`` and ``form_types`` restrict to filings matching those
    criteria. ``form_types`` is a list of canonical form-type strings (the
    caller resolves bundle keys via ``FORM_TYPE_BUNDLES``). Filters apply
    on the LEFT JOIN to filings, not in WHERE, so industries with zero
    matching filings are still returned (total=0, pending=0). The endpoint
    / template decides whether to display zero-total entries.

    The Phase-1 in-scope gate (``is_in_scope_phase1 = TRUE``) is applied
    when ``form_types`` intersects ``S1F1_FORMS`` — same rule as
    ``_build_discovery_sql`` — so facet counts agree with what Preview
    would actually surface.

    Sorted alphabetically by ``label``.
    """
    industries: dict[str, Any] = industry_map.get("industries") or {}
    if not industries:
        return []

    keys: list[str] = []
    labels: list[str] = []
    sics: list[str] = []
    for industry_key, entry in industries.items():
        label = _industry_label(industry_key)
        for sic in entry.get("sic_codes") or []:
            keys.append(industry_key)
            labels.append(label)
            sics.append(sic)

    if not keys:
        return []

    include_phase1 = bool(form_types and (S1F1_FORMS & set(form_types)))

    extra_clauses = []
    if years:
        extra_clauses.append("AND EXTRACT(YEAR FROM f.filing_date) = ANY(%(years)s)")
    if form_types:
        extra_clauses.append("AND f.form_type = ANY(%(form_types)s)")
    if include_phase1:
        extra_clauses.append("AND f.is_in_scope_phase1 = TRUE")
    filing_join_extra = "\n    ".join(extra_clauses)

    sql = _INDUSTRY_COUNTS_SQL_TEMPLATE.format(filing_join_extra=filing_join_extra)
    params: dict[str, Any] = {"keys": keys, "labels": labels, "sics": sics}
    if years:
        params["years"] = [int(y) for y in years]
    if form_types:
        params["form_types"] = list(form_types)

    rows = db.query(sql, params)
    return [
        IndustryCount(
            key=str(r["industry_key"]),
            label=str(r["industry_label"]),
            total=int(r["total"]),
            pending=int(r["pending"]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Form-type counts — third axis of the /ingest/ form facet cascade.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormTypeCount:
    """A FORM_TYPE_BUNDLES entry with the universe total and pending-extraction
    count of filings whose form_type is in the bundle's list of canonical
    form types."""

    key: str  # bundle key from FORM_TYPE_BUNDLES (e.g. "s1f1", "10k", "8k")
    label: str  # human label (e.g. "S-1 / F-1 (IPO filings)")
    total: int
    pending: int = 0


_FORM_TYPE_COUNTS_SQL_TEMPLATE = """
SELECT bundle.bundle_key,
       bundle.bundle_label,
       COUNT(f.filing_id) FILTER (
           WHERE f.filing_id IS NOT NULL
             {company_filter_clause}
             AND (NOT bundle.requires_phase1 OR f.is_in_scope_phase1 = TRUE)
       )::int AS total,
       COUNT(f.filing_id) FILTER (
           WHERE f.filing_id IS NOT NULL
             AND v.doc_id IS NULL
             {company_filter_clause}
             AND (NOT bundle.requires_phase1 OR f.is_in_scope_phase1 = TRUE)
       )::int AS pending
FROM unnest(
    %(keys)s::text[],
    %(labels)s::text[],
    %(form_types)s::text[],
    %(requires_phase1)s::bool[]
) AS bundle(bundle_key, bundle_label, form_type, requires_phase1)
LEFT JOIN filings f ON f.form_type = bundle.form_type
    {year_clause}
LEFT JOIN companies c ON c.company_id = f.company_id
LEFT JOIN v2_documents v ON v.filing_id = f.filing_id
GROUP BY bundle.bundle_key, bundle.bundle_label
"""


def query_universe_form_type_counts(
    db: DatabaseAdapter,
    bundles: dict[str, tuple[str, list[str]]] | None = None,
    *,
    years: list[int] | None = None,
    sic_codes: list[str] | None = None,
) -> list[FormTypeCount]:
    """Return [{key, label, total, pending}] for every form-type bundle.

    *bundles* maps bundle_key → (label, [canonical_form_types]). When None,
    defaults to the visible-form-row bundles (s1f1, 10k, 8k) — the same
    set rendered in the discovery form's checkbox row. Each filing whose
    ``form_type`` matches any of the bundle's canonical types contributes
    +1 to that bundle's total; the pending count is the subset with no
    ``v2_documents`` row.

    The Phase-1 in-scope gate is applied **per bundle**: bundles whose
    canonical form types intersect ``S1F1_FORMS`` (i.e. s1f1) only count
    filings where ``is_in_scope_phase1 = TRUE``. 10-K / 8-K bundles bypass
    the gate. Mirrors ``_build_discovery_sql``'s ``include_phase1`` rule.

    Optional ``years`` restricts by filing year; optional ``sic_codes``
    restricts by company SIC. Filters apply on the LEFT JOIN so bundles
    with zero matches still appear (total=0, pending=0).

    Sorted by bundle key for stable output (s1f1 → 10k → 8k).
    """
    if bundles is None:
        bundles = {
            "s1f1": ("S-1 / F-1 (IPO filings)", FORM_TYPE_BUNDLES["s1f1"]),
            "10k": ("10-K (Annual reports)", FORM_TYPE_BUNDLES["10k"]),
            "8k": ("8-K (Current reports)", FORM_TYPE_BUNDLES["8k"]),
        }
    if not bundles:
        return []

    keys: list[str] = []
    labels: list[str] = []
    form_types_flat: list[str] = []
    requires_phase1: list[bool] = []
    label_by_key: dict[str, str] = {}
    bundle_order: list[str] = []
    for bundle_key, (label, form_types_list) in bundles.items():
        label_by_key[bundle_key] = label
        bundle_order.append(bundle_key)
        gate = bool(S1F1_FORMS & set(form_types_list))
        for ft in form_types_list:
            keys.append(bundle_key)
            labels.append(label)
            form_types_flat.append(ft)
            requires_phase1.append(gate)

    if not keys:
        return []

    year_clause = "AND EXTRACT(YEAR FROM f.filing_date) = ANY(%(years)s)" if years else ""
    company_filter_clause = "AND c.industry_code = ANY(%(sic_codes)s)" if sic_codes else ""

    sql = _FORM_TYPE_COUNTS_SQL_TEMPLATE.format(
        year_clause=year_clause,
        company_filter_clause=company_filter_clause,
    )
    params: dict[str, Any] = {
        "keys": keys,
        "labels": labels,
        "form_types": form_types_flat,
        "requires_phase1": requires_phase1,
    }
    if years:
        params["years"] = [int(y) for y in years]
    if sic_codes:
        params["sic_codes"] = list(sic_codes)

    rows = db.query(sql, params)
    by_key = {str(r["bundle_key"]): (int(r["total"]), int(r["pending"])) for r in rows}
    return [
        FormTypeCount(
            key=k,
            label=label_by_key[k],
            total=by_key.get(k, (0, 0))[0],
            pending=by_key.get(k, (0, 0))[1],
        )
        for k in bundle_order
    ]
