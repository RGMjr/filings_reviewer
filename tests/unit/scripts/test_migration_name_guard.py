"""Unit tests for scripts/pre-commit-migration-name-guard.sh.

Verifies that the guard catches both newly added files (diff-filter=A) and
renamed files (diff-filter=R) so that a `git mv sql/old.sql sql/new.sql`
cannot silently change a migration ID on databases that already ran the old
filename.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_GUARD = Path(__file__).resolve().parents[3] / "scripts" / "pre-commit-migration-name-guard.sh"


def _clean_env() -> dict[str, str]:
    # pre-commit / pre-push hooks set GIT_DIR + GIT_WORK_TREE to the host repo,
    # which overrides cwd= for any git invocation. Strip them so tests get a
    # clean environment that respects cwd.
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _init_repo(tmp_path: Path) -> Path:
    """Initialise a minimal git repo with a sql/ dir and one committed migration."""
    env = _clean_env()
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env=env,
    )
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    # Commit an initial legacy-style migration (not subject to the guard).
    legacy = sql_dir / "31_drop_old.sql"
    legacy.write_text("-- legacy\n")
    subprocess.run(
        ["git", "add", str(legacy)], cwd=tmp_path, check=True, capture_output=True, env=env
    )
    subprocess.run(
        ["git", "commit", "-m", "init", "--no-gpg-sign"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env=env,
    )
    return tmp_path


def _run_guard(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_GUARD)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )


class TestMigrationNameGuardAdds:
    def test_valid_timestamp_name_passes(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        f = repo / "sql" / "202601010000_add_something.sql"
        f.write_text("-- ok\n")
        subprocess.run(
            ["git", "add", str(f)], cwd=repo, check=True, capture_output=True, env=_clean_env()
        )
        result = _run_guard(repo)
        assert result.returncode == 0, result.stderr

    def test_legacy_prefix_add_is_blocked(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        f = repo / "sql" / "99_new_migration.sql"
        f.write_text("-- bad\n")
        subprocess.run(
            ["git", "add", str(f)], cwd=repo, check=True, capture_output=True, env=_clean_env()
        )
        result = _run_guard(repo)
        assert result.returncode == 1
        assert "legacy" in result.stderr.lower() or "NN_" in result.stderr

    def test_bad_format_add_is_blocked(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        f = repo / "sql" / "add_something.sql"
        f.write_text("-- bad\n")
        subprocess.run(
            ["git", "add", str(f)], cwd=repo, check=True, capture_output=True, env=_clean_env()
        )
        result = _run_guard(repo)
        assert result.returncode == 1

    def test_no_staged_sql_exits_0(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        result = _run_guard(repo)
        assert result.returncode == 0


class TestMigrationNameGuardRenames:
    def test_rename_of_legacy_to_bad_name_is_blocked(self, tmp_path: Path) -> None:
        """git mv of a legacy file to a non-timestamp name must be caught."""
        repo = _init_repo(tmp_path)
        old = repo / "sql" / "31_drop_old.sql"
        new = repo / "sql" / "99_renamed.sql"
        subprocess.run(
            ["git", "mv", str(old), str(new)],
            cwd=repo,
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        result = _run_guard(repo)
        assert result.returncode == 1, (
            "Guard should reject the rename — the new name uses the legacy NN_ scheme"
        )

    def test_rename_to_valid_timestamp_passes(self, tmp_path: Path) -> None:
        """git mv to a properly-formatted timestamp name should pass."""
        repo = _init_repo(tmp_path)
        old = repo / "sql" / "31_drop_old.sql"
        new = repo / "sql" / "202601010000_drop_old.sql"
        subprocess.run(
            ["git", "mv", str(old), str(new)],
            cwd=repo,
            check=True,
            capture_output=True,
            env=_clean_env(),
        )
        result = _run_guard(repo)
        assert result.returncode == 0, result.stderr
