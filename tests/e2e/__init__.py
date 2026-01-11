"""
E2E Tests Package

End-to-end tests using Playwright MCP for browser automation.
These tests verify the review interface functionality in a real browser.

Prerequisites:
- Flask dev server running (see run_server.sh or use port 5003)
- At least one review candidate in database
- Playwright MCP server configured in Claude Code

Run via Claude Code:
1. Start server: DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 -m flask --app src.web.app run --debug --port 5003
2. Use browser_navigate, browser_click, browser_type, browser_snapshot tools
"""
