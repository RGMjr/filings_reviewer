# ast-grep Rules

Search template rules for the filings_reviewer project. These are primarily **search accelerators** rather than lint rules (use ruff/mypy for linting).

## Available Rules

| Rule | Purpose | Example Usage |
|------|---------|---------------|
| `find-dataclasses` | Find all dataclass definitions | `ast-grep scan --rule ast-grep-rules/find-dataclasses.yml src/` |
| `find-flask-routes` | Find all Flask route handlers | `ast-grep scan --rule ast-grep-rules/find-flask-routes.yml src/web/` |
| `find-sql-queries` | Find all SQL executions | `ast-grep scan --rule ast-grep-rules/find-sql-queries.yml src/` |
| `find-validation-errors` | Find ValidationError raises | `ast-grep scan --rule ast-grep-rules/find-validation-errors.yml src/` |
| `find-test-fixtures` | Find pytest fixtures | `ast-grep scan --rule ast-grep-rules/find-test-fixtures.yml tests/` |
| `find-protocols` | Find Protocol interfaces | `ast-grep scan --rule ast-grep-rules/find-protocols.yml src/` |

## Quick Patterns

Common one-liner searches (no rule file needed):

```bash
# Find all class definitions
ast-grep run --pattern 'class $NAME' --lang python src/

# Find logger calls
ast-grep run --pattern 'logger.$METHOD($$$)' --lang python src/

# Find all raises
ast-grep run --pattern 'raise $EXC($$$)' --lang python src/

# Find specific function usages
ast-grep run --pattern 'generate_candidates($$$)' --lang python .

# Find decorated functions
ast-grep run --pattern '@$DEC
def $FUNC($$$):' --lang python src/
```

## When to Use ast-grep vs grep

| Use ast-grep | Use grep/ripgrep |
|--------------|------------------|
| Finding function/class definitions | Plain text search |
| Structural patterns (e.g., decorated functions) | Searching comments |
| Refactoring: all usages of a pattern | Searching non-code files |
| Understanding code architecture | Simple string matches |

## Adding New Rules

Create a YAML file in this directory:

```yaml
id: rule-name
language: python
severity: hint  # hint for search, warning/error for lint
message: "Description of match"
rule:
  pattern: 'code pattern here'
```

Reference: https://ast-grep.github.io/guide/rule-config.html
