#!/usr/bin/env python3
"""Validate plan document structure and dependencies.

This script checks plan documents for:
- Required sections (Task Breakdown, Success Criteria)
- Valid task references (no dangling dependencies)
- Circular dependencies
- Required fields in each task
- Task size consistency with time estimates

Usage:
    python scripts/validate_plan.py docs/EXTRACTION_IMPROVEMENT_PLAN.md
    python scripts/validate_plan.py docs/*.md  # Check all plans
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationIssue:
    """Represents a validation issue found in a plan."""

    severity: str  # "error" or "warning"
    message: str
    line: Optional[int] = None

    def __str__(self) -> str:
        loc = f" (line {self.line})" if self.line else ""
        icon = "❌" if self.severity == "error" else "⚠️"
        return f"{icon} {self.severity.upper()}{loc}: {self.message}"


def extract_task_ids(content: str) -> set[str]:
    """Extract all task IDs defined in the plan."""
    # Match patterns like **ID**: EI-1 or **Task ID**: GR-5
    patterns = [
        r"\*\*(?:Task\s+)?ID\*\*:\s*([A-Z]+-\d+)",
        r"####\s+([A-Z]+-\d+)",  # Also match ### EI-1 style headers
        r"\|\s*([A-Z]+-\d+)\s*\|",  # Match task IDs in tables
    ]

    task_ids: set[str] = set()
    for pattern in patterns:
        task_ids.update(re.findall(pattern, content, re.IGNORECASE))

    return {tid.upper() for tid in task_ids}


def extract_referenced_ids(content: str) -> set[str]:
    """Extract all task IDs referenced as dependencies."""
    # Match patterns like DEPENDS ON: EI-1, EI-2 or Prerequisites: EI-1
    dep_patterns = [
        r"(?:DEPENDS ON|Prerequisites|Blocked by|Requires):\s*([A-Z]+-\d+(?:\s*,\s*[A-Z]+-\d+)*)",
        r"blocked by ([A-Z]+-\d+)",
        r"after ([A-Z]+-\d+)",
    ]

    referenced: set[str] = set()
    for pattern in dep_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            # Split by comma to handle multiple IDs
            ids = re.findall(r"[A-Z]+-\d+", match.group(1), re.IGNORECASE)
            referenced.update(id.upper() for id in ids)

    return referenced


def check_required_sections(content: str) -> list[ValidationIssue]:
    """Check for required sections in the plan."""
    issues: list[ValidationIssue] = []

    required_sections = [
        ("Task Breakdown", "error"),
        ("Success Criteria", "warning"),
        ("Progress Tracker", "warning"),
    ]

    for section, severity in required_sections:
        # Check for section header (## or ###)
        pattern = rf"^#{2,3}\s+.*{re.escape(section)}"
        if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
            issues.append(
                ValidationIssue(
                    severity=severity,
                    message=f"Missing section: '{section}'",
                )
            )

    return issues


def check_task_fields(content: str, task_ids: set[str]) -> list[ValidationIssue]:
    """Check that tasks have required fields."""
    issues: list[ValidationIssue] = []

    required_fields = [
        ("Time Estimate", "warning"),
        ("Risk Level", "warning"),
        ("DEPENDS ON", "warning"),
    ]

    # Split content by task headers to check each task
    task_pattern = r"(#{3,4}\s+[A-Z]+-\d+.*?)(?=#{3,4}\s+[A-Z]+-\d+|$)"
    task_sections = re.findall(task_pattern, content, re.DOTALL | re.IGNORECASE)

    for task_section in task_sections:
        # Extract task ID from section
        id_match = re.search(r"([A-Z]+-\d+)", task_section, re.IGNORECASE)
        if not id_match:
            continue

        task_id = id_match.group(1).upper()

        for field, severity in required_fields:
            if field.lower() not in task_section.lower():
                issues.append(
                    ValidationIssue(
                        severity=severity,
                        message=f"Task {task_id} missing field: '{field}'",
                    )
                )

    return issues


def check_dangling_references(
    defined_ids: set[str], referenced_ids: set[str]
) -> list[ValidationIssue]:
    """Check for references to undefined tasks."""
    issues: list[ValidationIssue] = []

    dangling = referenced_ids - defined_ids
    for task_id in sorted(dangling):
        issues.append(
            ValidationIssue(
                severity="error",
                message=f"Task '{task_id}' referenced but not defined",
            )
        )

    return issues


def check_circular_dependencies(content: str) -> list[ValidationIssue]:
    """Check for circular dependencies between tasks."""
    issues: list[ValidationIssue] = []

    # Build dependency graph
    deps: dict[str, set[str]] = {}

    # Find all DEPENDS ON declarations
    pattern = r"([A-Z]+-\d+).*?(?:DEPENDS ON|Prerequisites):\s*([A-Z]+-\d+(?:\s*,\s*[A-Z]+-\d+)*)"
    for match in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
        task_id = match.group(1).upper()
        dep_ids = re.findall(r"[A-Z]+-\d+", match.group(2), re.IGNORECASE)
        deps[task_id] = {d.upper() for d in dep_ids}

    # Check for cycles using DFS
    def has_cycle(node: str, visited: set[str], path: set[str]) -> Optional[list[str]]:
        if node in path:
            return [node]
        if node in visited:
            return None

        visited.add(node)
        path.add(node)

        for dep in deps.get(node, set()):
            cycle = has_cycle(dep, visited, path)
            if cycle:
                cycle.append(node)
                return cycle

        path.remove(node)
        return None

    visited: set[str] = set()
    for task_id in deps:
        if task_id not in visited:
            cycle = has_cycle(task_id, visited, set())
            if cycle:
                cycle_str = " → ".join(reversed(cycle))
                issues.append(
                    ValidationIssue(
                        severity="error",
                        message=f"Circular dependency detected: {cycle_str}",
                    )
                )
                break  # Only report first cycle

    return issues


def check_size_estimate_consistency(content: str) -> list[ValidationIssue]:
    """Check that TASK SIZE matches TIME ESTIMATE."""
    issues: list[ValidationIssue] = []

    size_ranges = {
        "XS": (0, 0.5),
        "S": (0.5, 2),
        "M": (2, 4),
        "L": (4, 8),
        "XL": (8, float("inf")),
    }

    # Find tasks with both SIZE and TIME ESTIMATE
    pattern = r"([A-Z]+-\d+).*?(?:TASK SIZE|SIZE):\s*(XS|S|M|L|XL).*?TIME ESTIMATE:\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*hour"
    for match in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
        task_id = match.group(1).upper()
        size = match.group(2).upper()
        min_hours = float(match.group(3))
        max_hours = float(match.group(4)) if match.group(4) else min_hours

        expected_min, expected_max = size_ranges.get(size, (0, float("inf")))

        # Check if estimate falls outside expected range
        if max_hours < expected_min or min_hours > expected_max:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=f"Task {task_id}: SIZE={size} but estimate={min_hours}-{max_hours}h "
                    f"(expected {expected_min}-{expected_max}h)",
                )
            )

    return issues


def validate_plan(plan_path: Path) -> list[ValidationIssue]:
    """Validate a plan document and return list of issues."""
    if not plan_path.exists():
        return [ValidationIssue(severity="error", message=f"File not found: {plan_path}")]

    content = plan_path.read_text()
    issues: list[ValidationIssue] = []

    # Skip non-plan files
    if "Task Breakdown" not in content and "Progress Tracker" not in content:
        return []  # Not a plan document, skip

    # Run all checks
    issues.extend(check_required_sections(content))

    task_ids = extract_task_ids(content)
    referenced_ids = extract_referenced_ids(content)

    if task_ids:
        issues.extend(check_task_fields(content, task_ids))
        issues.extend(check_dangling_references(task_ids, referenced_ids))
        issues.extend(check_circular_dependencies(content))
        issues.extend(check_size_estimate_consistency(content))

    return issues


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_plan.py <plan_file.md> [plan_file2.md ...]")
        print("\nExample:")
        print("  python scripts/validate_plan.py docs/EXTRACTION_IMPROVEMENT_PLAN.md")
        print("  python scripts/validate_plan.py docs/*.md")
        return 1

    all_issues: dict[str, list[ValidationIssue]] = {}
    error_count = 0
    warning_count = 0

    for path_str in sys.argv[1:]:
        plan_path = Path(path_str)

        # Handle glob patterns
        if "*" in path_str:
            from glob import glob

            paths = [Path(p) for p in glob(path_str)]
        else:
            paths = [plan_path]

        for path in paths:
            issues = validate_plan(path)
            if issues:
                all_issues[str(path)] = issues
                for issue in issues:
                    if issue.severity == "error":
                        error_count += 1
                    else:
                        warning_count += 1

    # Print results
    if not all_issues:
        print("✅ All plan documents are valid!")
        return 0

    for file_path, issues in all_issues.items():
        print(f"\n📄 {file_path}")
        print("─" * 60)
        for issue in issues:
            print(f"  {issue}")

    print("\n" + "═" * 60)
    print(f"Summary: {error_count} error(s), {warning_count} warning(s)")

    if error_count > 0:
        print("\n❌ Validation failed - please fix errors before proceeding")
        return 1
    else:
        print("\n⚠️  Validation passed with warnings")
        return 0


if __name__ == "__main__":
    sys.exit(main())
