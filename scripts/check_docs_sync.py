#!/usr/bin/env python3
"""
Documentation Sync Checker

Validates that documentation stays in sync with code:
- requirements.txt matches actual imports
- CLAUDE.md references existing src/ modules
- README.md component list matches src/ structure
- Test coverage numbers are current

Run: python scripts/check_docs_sync.py [--fix] [--quiet]
"""

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"


class DocsChecker:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.warnings = []
        self.errors = []

    def log(self, msg: str):
        if not self.quiet:
            print(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)
        if not self.quiet:
            print(f"⚠️  {msg}")

    def error(self, msg: str):
        self.errors.append(msg)
        if not self.quiet:
            print(f"❌ {msg}")

    def ok(self, msg: str):
        if not self.quiet:
            print(f"✅ {msg}")

    # -------------------------------------------------------------------------
    # Check 1: Requirements vs actual imports
    # -------------------------------------------------------------------------
    def check_requirements(self) -> bool:
        """Check if requirements.txt includes all third-party imports."""
        self.log("\n📦 Checking requirements.txt...")

        # Get declared dependencies
        req_file = ROOT / "requirements.txt"
        if not req_file.exists():
            self.error("requirements.txt not found")
            return False

        declared = set()
        for line in req_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # Extract package name (before any version specifier)
                pkg = re.split(r"[<>=\[\]]", line)[0].strip().lower()
                # Normalize common aliases
                pkg = pkg.replace("-", "_")
                declared.add(pkg)

        # Map import names to package names
        import_to_pkg = {
            "bs4": "beautifulsoup4",
            "dotenv": "python_dotenv",
            "psycopg": "psycopg",
        }

        # Find all imports in src/
        imports_found = set()
        stdlib = self._get_stdlib_modules()

        for py_file in SRC.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports_found.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports_found.add(node.module.split(".")[0])
            except SyntaxError:
                pass

        # Get local module names (src subdirectories)
        local_modules = {"src"}
        for p in SRC.iterdir():
            if p.is_dir() and not p.name.startswith("_"):
                local_modules.add(p.name)
        # Also add any .py file names as potential relative imports
        for py_file in SRC.rglob("*.py"):
            local_modules.add(py_file.stem)

        # Filter to third-party only
        third_party = set()
        for imp in imports_found:
            if imp in stdlib or imp in local_modules:
                continue
            # Map to package name
            pkg = import_to_pkg.get(imp, imp).lower().replace("-", "_")
            third_party.add(pkg)

        # Normalize declared for comparison
        declared_normalized = {p.replace("-", "_") for p in declared}

        # Check for missing
        missing = third_party - declared_normalized
        if missing:
            self.warn(f"Imports not in requirements.txt: {missing}")
            return False

        self.ok("requirements.txt covers all imports")
        return True

    def _get_stdlib_modules(self) -> set:
        """Get standard library module names."""
        return {
            "abc", "argparse", "ast", "asyncio", "base64", "collections",
            "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal",
            "enum", "functools", "hashlib", "html", "http", "io", "itertools",
            "json", "logging", "math", "os", "pathlib", "pickle", "random",
            "re", "shutil", "socket", "sqlite3", "string", "subprocess", "sys",
            "tempfile", "textwrap", "threading", "time", "traceback", "typing",
            "unittest", "urllib", "uuid", "warnings", "xml", "zipfile",
        }

    # -------------------------------------------------------------------------
    # Check 2: CLAUDE.md references valid modules
    # -------------------------------------------------------------------------
    def check_claude_md(self) -> bool:
        """Check if CLAUDE.md references existing src/ modules."""
        self.log("\n📄 Checking CLAUDE.md...")

        claude_md = ROOT / "CLAUDE.md"
        if not claude_md.exists():
            self.error("CLAUDE.md not found")
            return False

        content = claude_md.read_text()

        # Get actual project Python files (src/ and scripts/)
        actual_files = set()
        for py_file in SRC.rglob("*.py"):
            if py_file.name != "__init__.py":
                actual_files.add(py_file.name)
        scripts_dir = ROOT / "scripts"
        if scripts_dir.exists():
            for py_file in scripts_dir.glob("*.py"):
                actual_files.add(py_file.name)

        # Check for referenced files that don't exist
        referenced_files = re.findall(r"(\w+\.py)", content)
        issues = []

        # Files that are OK to reference even if they don't exist
        allowed_refs = {"setup.py", "conftest.py", "main.py"}

        for ref in referenced_files:
            # Skip if it's a test file reference
            if ref.startswith("test_"):
                continue
            # Check if it exists somewhere in project
            if ref not in actual_files and ref not in allowed_refs:
                issues.append(ref)

        if issues:
            self.warn(f"CLAUDE.md references non-existent files: {issues}")
            return False

        # Check for stale architecture references
        if "data_preprocessing.py" in content:
            self.error("CLAUDE.md still references legacy data_preprocessing.py")
            return False

        self.ok("CLAUDE.md references are valid")
        return True

    # -------------------------------------------------------------------------
    # Check 3: README component list matches src/
    # -------------------------------------------------------------------------
    def check_readme_components(self) -> bool:
        """Check if README component list matches actual src/ modules."""
        self.log("\n📋 Checking README.md components...")

        readme = ROOT / "README.md"
        if not readme.exists():
            self.error("README.md not found")
            return False

        content = readme.read_text()

        # Expected components based on src/ structure
        expected_components = {
            "UniverseBuilder": SRC / "universe" / "universe_builder.py",
            "FilingFetcher": SRC / "filing_fetcher" / "filing_fetcher.py",
            "HTMLSegmenter": SRC / "extraction" / "html_segmenter.py",
            "MetricClassifier": SRC / "extraction" / "metric_classifier.py",
            "ValueExtractor": SRC / "extraction" / "value_extractor.py",
            "DefinitionExtractor": SRC / "extraction" / "definition_extractor.py",
            "QualityScorer": SRC / "extraction" / "quality_scorer.py",
        }

        issues = []
        for component, path in expected_components.items():
            if not path.exists():
                issues.append(f"{component} listed but {path} missing")
            elif component not in content:
                issues.append(f"{component} exists but not in README")

        if issues:
            for issue in issues:
                self.warn(issue)
            return False

        self.ok("README.md components match src/ structure")
        return True

    # -------------------------------------------------------------------------
    # Check 4: Test coverage freshness
    # -------------------------------------------------------------------------
    def check_coverage_freshness(self) -> bool:
        """Check if README coverage number is reasonably current."""
        self.log("\n🧪 Checking test coverage freshness...")

        readme = ROOT / "README.md"
        content = readme.read_text()

        # Extract claimed coverage
        match = re.search(r"(\d+)%\s*overall", content)
        if not match:
            self.warn("Could not find coverage percentage in README")
            return False

        claimed = int(match.group(1))

        # Try to get actual coverage (if pytest-cov available)
        try:
            result = subprocess.run(
                ["pytest", "--cov=src", "--cov-report=term", "-q", "--tb=no"],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=120,
            )
            # Parse output for TOTAL line
            for line in result.stdout.splitlines():
                if "TOTAL" in line:
                    actual_match = re.search(r"(\d+)%", line)
                    if actual_match:
                        actual = int(actual_match.group(1))
                        diff = abs(actual - claimed)
                        if diff > 5:
                            self.warn(
                                f"README claims {claimed}% coverage, "
                                f"actual is {actual}% (diff: {diff}%)"
                            )
                            return False
                        self.ok(f"Coverage is current ({actual}%)")
                        return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self.log("  (skipped - pytest not available or timed out)")
            return True

        return True

    # -------------------------------------------------------------------------
    # Run all checks
    # -------------------------------------------------------------------------
    def run_all(self) -> bool:
        """Run all documentation checks."""
        self.log("=" * 60)
        self.log("Documentation Sync Check")
        self.log("=" * 60)

        results = [
            self.check_requirements(),
            self.check_claude_md(),
            self.check_readme_components(),
            self.check_coverage_freshness(),
        ]

        self.log("\n" + "=" * 60)
        if all(results):
            self.log("✅ All documentation checks passed")
            return True
        else:
            self.log(f"⚠️  {len(self.warnings)} warnings, {len(self.errors)} errors")
            return False


def main():
    parser = argparse.ArgumentParser(description="Check documentation sync")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")
    parser.add_argument(
        "--ci", action="store_true", help="CI mode (exit 1 on warnings)"
    )
    args = parser.parse_args()

    checker = DocsChecker(quiet=args.quiet)
    success = checker.run_all()

    if args.ci and (checker.warnings or checker.errors):
        sys.exit(1)
    elif checker.errors:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
