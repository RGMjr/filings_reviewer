#!/usr/bin/env python3
"""
Sync GitHub Issues with PROJECT_TASK_INVENTORY.md

Compares task inventory status with GitHub issues and reports discrepancies.
Can optionally update GitHub issues to match inventory status.

Usage:
    python scripts/sync_github_issues.py --check          # Report only
    python scripts/sync_github_issues.py --update         # Update GitHub
    python scripts/sync_github_issues.py --create-missing # Create missing issues

Requires: GITHUB_TOKEN environment variable
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class TaskStatus:
    """Task status from inventory."""
    task_id: str
    name: str
    status: str  # 'complete', 'pending', 'blocked', 'in_progress'
    workstream: str


@dataclass
class GitHubIssue:
    """GitHub issue data."""
    number: int
    title: str
    state: str  # 'open', 'closed'
    labels: list[str]


def parse_task_inventory(inventory_path: Path) -> dict[str, TaskStatus]:
    """Parse PROJECT_TASK_INVENTORY.md and extract task statuses."""
    tasks = {}
    content = inventory_path.read_text()

    # Pattern matches task rows in markdown tables
    # | **GR-1** | Lower goldmine threshold | S | 1h | LOW | ✅ COMPLETE | None |
    pattern = r'\|\s*\*\*([A-Z]+-\d+[a-zA-Z]?)\*\*\s*\|\s*([^|]+)\|[^|]*\|[^|]*\|[^|]*\|\s*(✅ COMPLETE|🟡 PENDING|🔴 BLOCKED|⏸️|❌ CLOSED)'

    for match in re.finditer(pattern, content):
        task_id = match.group(1)
        name = match.group(2).strip()
        status_str = match.group(3)

        if '✅ COMPLETE' in status_str:
            status = 'complete'
        elif '🟡 PENDING' in status_str:
            status = 'pending'
        elif '🔴 BLOCKED' in status_str:
            status = 'blocked'
        elif '❌ CLOSED' in status_str:
            status = 'closed'
        else:
            status = 'other'

        # Extract workstream from task ID prefix
        workstream = task_id.split('-')[0]

        tasks[task_id] = TaskStatus(
            task_id=task_id,
            name=name,
            status=status,
            workstream=workstream
        )

    return tasks


def get_github_issues(repo: str, token: str) -> list[GitHubIssue]:
    """Fetch all GitHub issues using gh CLI or API."""
    try:
        # Try using gh CLI first
        result = subprocess.run(
            ['gh', 'issue', 'list', '--repo', repo, '--state', 'all', '--json',
             'number,title,state,labels', '--limit', '100'],
            capture_output=True, text=True, check=True
        )
        issues_data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to curl with API
        import urllib.request
        url = f'https://api.github.com/repos/{repo}/issues?state=all&per_page=100'
        req = urllib.request.Request(url, headers={
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github+json'
        })
        with urllib.request.urlopen(req) as response:
            issues_data = json.loads(response.read().decode())

    issues = []
    for issue in issues_data:
        labels = [l['name'] if isinstance(l, dict) else l for l in issue.get('labels', [])]
        issues.append(GitHubIssue(
            number=issue['number'],
            title=issue['title'],
            state=issue['state'],
            labels=labels
        ))

    return issues


def find_discrepancies(
    tasks: dict[str, TaskStatus],
    issues: list[GitHubIssue]
) -> dict[str, list]:
    """Find discrepancies between task inventory and GitHub issues."""
    discrepancies = {
        'should_close': [],      # Open issues for completed tasks
        'should_reopen': [],     # Closed issues for pending tasks
        'missing_issues': [],    # Tasks without GitHub issues
        'stale_labels': [],      # Issues with outdated labels
    }

    # Map issue titles to issues (simple heuristic matching)
    issue_map = {issue.title.lower(): issue for issue in issues}

    for task_id, task in tasks.items():
        # Try to find matching issue
        matching_issue = None
        for title, issue in issue_map.items():
            if task_id.lower() in title or task.name.lower() in title:
                matching_issue = issue
                break

        if matching_issue:
            # Check for status mismatch
            if task.status == 'complete' and matching_issue.state == 'open':
                discrepancies['should_close'].append({
                    'task': task,
                    'issue': matching_issue,
                    'reason': f'Task {task_id} is complete but issue #{matching_issue.number} is open'
                })
            elif task.status in ('pending', 'in_progress') and matching_issue.state == 'closed':
                discrepancies['should_reopen'].append({
                    'task': task,
                    'issue': matching_issue,
                    'reason': f'Task {task_id} is {task.status} but issue #{matching_issue.number} is closed'
                })

    return discrepancies


def print_report(discrepancies: dict[str, list]) -> None:
    """Print discrepancy report."""
    total = sum(len(v) for v in discrepancies.values())

    if total == 0:
        print("✅ GitHub issues are in sync with task inventory!")
        return

    print(f"⚠️  Found {total} discrepancies:\n")

    if discrepancies['should_close']:
        print("## Issues to Close (task completed)")
        for d in discrepancies['should_close']:
            print(f"  - Issue #{d['issue'].number}: {d['issue'].title}")
            print(f"    Task: {d['task'].task_id} - {d['task'].status}")
        print()

    if discrepancies['should_reopen']:
        print("## Issues to Reopen (task not complete)")
        for d in discrepancies['should_reopen']:
            print(f"  - Issue #{d['issue'].number}: {d['issue'].title}")
            print(f"    Task: {d['task'].task_id} - {d['task'].status}")
        print()


def main():
    parser = argparse.ArgumentParser(description='Sync GitHub issues with task inventory')
    parser.add_argument('--check', action='store_true', help='Report discrepancies only')
    parser.add_argument('--update', action='store_true', help='Update GitHub issues')
    parser.add_argument('--repo', default='RGMjr/filings_reviewer', help='GitHub repo')
    parser.add_argument('--inventory', default='docs/PROJECT_TASK_INVENTORY.md',
                        help='Path to task inventory')
    args = parser.parse_args()

    # Get token
    token = os.environ.get('GITHUB_TOKEN')
    if not token and args.update:
        print("Error: GITHUB_TOKEN environment variable required for --update")
        sys.exit(1)

    # Parse inventory
    inventory_path = Path(args.inventory)
    if not inventory_path.exists():
        print(f"Error: Inventory file not found: {inventory_path}")
        sys.exit(1)

    tasks = parse_task_inventory(inventory_path)
    print(f"Parsed {len(tasks)} tasks from inventory")

    # Get GitHub issues
    if token:
        issues = get_github_issues(args.repo, token)
        print(f"Fetched {len(issues)} GitHub issues")

        # Find discrepancies
        discrepancies = find_discrepancies(tasks, issues)
        print_report(discrepancies)

        if args.update and any(discrepancies.values()):
            print("\n--update flag set but automatic updates not yet implemented")
            print("Please update issues manually or extend this script")
    else:
        print("Note: Set GITHUB_TOKEN to fetch and compare with GitHub issues")
        print(f"\nTask summary by workstream:")
        workstreams = {}
        for task in tasks.values():
            ws = task.workstream
            if ws not in workstreams:
                workstreams[ws] = {'complete': 0, 'pending': 0, 'blocked': 0, 'other': 0}
            workstreams[ws][task.status] = workstreams[ws].get(task.status, 0) + 1

        for ws, counts in sorted(workstreams.items()):
            print(f"  {ws}: {counts}")


if __name__ == '__main__':
    main()
