# WORKER PROMPT: Task UXI-2-TEST-F3 - E2E Test Automation Script

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-2-TEST-F3
TASK NAME:     Create shell script to guide E2E test execution
WORKSTREAM:    Testing Improvements
SOURCE:        UXI-2-TEST completion evaluation - improvement suggestion #3
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (design 30 min, implementation 60 min, documentation 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None (additive script only)
TASK SIZE:     S
DEPENDS ON:    UXI-2-TEST (must be complete)
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-2-TEST-F1, UXI-2-TEST-F2, UXI-2-TEST-F4
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a shell script that sets up the environment and guides users through E2E test execution using Claude Code + Playwright MCP.

**Business Rationale**: E2E tests via Playwright MCP require manual execution through Claude Code. A setup script ensures proper environment configuration and provides clear instructions.

**Current Behavior**: Users must manually read test docstrings and know how to start the Flask server.

**Desired Behavior**: Run `./scripts/run_e2e_tests.sh` to get environment ready and step-by-step instructions.

## Prerequisites

- UXI-2-TEST complete

## Files to Create

1. **`scripts/run_e2e_tests.sh`** - Setup and instruction script

## Implementation Requirements

### Core Functionality

1. **Environment Setup**
   - Check if PostgreSQL container is running
   - Start Flask dev server on port 5003 if not running
   - Verify server is responding (curl health check)
   - Check for pending review candidates in database

2. **Instructions Output**
   - Print clear instructions for running tests in Claude Code
   - List the 6+ tests with their test function names
   - Provide example Playwright MCP commands
   - Show how to interpret results

3. **Script Features**
   - Use colors for better readability (green = success, red = error)
   - Exit with helpful message if prerequisites not met
   - Option to only check environment (`--check` flag)

### Example Output

```
═══════════════════════════════════════════════════════════════════════════════
E2E Test Runner for UXI-2 Metric Dropdown Search
═══════════════════════════════════════════════════════════════════════════════

[✓] PostgreSQL container running
[✓] Flask server running on port 5003
[✓] 15 pending candidates available

To run tests, open Claude Code and execute each test:

TEST 1: test_search_filters_metrics
  1. browser_navigate('http://localhost:5003/review/31')
  2. browser_press_key('c')
  3. browser_type('arr', ref=search_input)
  4. browser_snapshot() - verify 1 visible metric

... (more tests)

Run tests by copying commands into Claude Code with Playwright MCP.
═══════════════════════════════════════════════════════════════════════════════
```

## Acceptance Criteria

- [ ] Script checks Docker/PostgreSQL status
- [ ] Script starts Flask server if needed
- [ ] Script verifies pending candidates exist
- [ ] Script prints test execution instructions
- [ ] Script is executable (`chmod +x`)
- [ ] Script has `--check` flag for environment validation only

## Do NOT

- Actually run Playwright commands (script is setup only)
- Modify existing test files
- Add Python dependencies

## Verification Commands

```bash
# Verify script is executable
ls -la scripts/run_e2e_tests.sh

# Run environment check
./scripts/run_e2e_tests.sh --check
```

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6
