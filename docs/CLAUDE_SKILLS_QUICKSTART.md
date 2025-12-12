# Claude Skills Quick-Start Guide

**Created:** 2025-12-11
**For Project:** SEC Filings Reviewer

---

## What Are Claude Skills?

Claude Skills are **reusable prompt templates** that reduce context window usage and ensure consistency when working with Claude Code. They encode your project's patterns, conventions, and workflows so you don't have to explain them every time.

**Think of them as:**
- 📚 Project knowledge repositories
- 🎯 Standardized workflows
- ⚡ Context shortcuts
- 🔄 Consistency guarantees

---

## Why Use Skills?

### Without Skills
```
You: "Create an implementation plan for feature X"
Claude: "Sure, what format would you like?"
You: "Use the format from HUMAN_REVIEW_SYSTEM_PLAN.md with A/B/C streams,
      dependency graphs, time estimates, parallel opportunities, and
      reference the existing patterns in src/..."
Claude: "Got it, let me read that file first..."
[Uses 5,000+ tokens of context]
```

### With Skills
```
You: "Use implementation-planner skill to plan feature X"
Claude: [Loads skill] "I'll create a plan following your A/B/C stream
         pattern with dependencies and estimates..."
[Uses 500 tokens, already knows the format]
```

**Result:** 90% less context needed, 10x faster, perfect consistency

---

## Current Skills Available

| Skill | File | Status | Use Case |
|-------|------|--------|----------|
| Implementation Planner | `.claude/skills/implementation-planner.md` | ✅ Ready | Generate structured plans with A/B/C streams |
| Code Module Grader | TBD | ⬜ Planned | Evaluate modules A+ to F, generate improvements |
| Test Coverage Analyzer | TBD | ⬜ Planned | Find gaps, generate test files |
| Database Migration Helper | TBD | ⬜ Planned | Generate SQL migrations + db.py methods |
| Documentation Sync Validator | TBD | ⬜ Planned | Catch stale documentation |

---

## How to Use a Skill

### Method 1: Direct Invocation (Recommended)

```
You: "Use the implementation-planner skill to create a plan for
      building a metrics export feature with CSV, JSON, and Excel formats"

Claude: [Loads skill, follows template, generates plan]
```

### Method 2: Implicit Invocation

```
You: "Create an implementation plan for metrics export feature"

Claude: "I notice this matches the implementation-planner skill pattern.
         Would you like me to use that skill for consistency?"

You: "Yes"

Claude: [Loads skill, generates plan]
```

### Method 3: Reference in Context

```
You: "Following the implementation-planner skill, create a plan for..."

Claude: [Loads skill, applies patterns]
```

---

## Skill Invocation Examples

### Example 1: Simple Feature Planning

**Your Request:**
```
Use implementation-planner skill:

Task: Add export functionality to the review interface
- Support CSV and JSON formats
- Include filtering by status (pending/reviewed)
- Add progress indicator for large exports
```

**Claude's Response:**
```
I'll create an implementation plan for: Export functionality

Identified 3 work streams:
- Stream A: Database methods (2 tasks, 1-2 hours)
- Stream B: Export logic (2 tasks, 2-3 hours)
- Stream D: UI integration (3 tasks, 3-4 hours)

Total estimate: 6-9 hours (1-2 days)

Parallel opportunities: Streams A and B can start immediately

I'll generate:
1. Main plan: docs/EXPORT_FEATURE_PLAN.md
2. Task checklist for DEVELOPMENT_PLAN.md

Proceed? (yes/no)
```

### Example 2: Improvement Planning

**Your Request:**
```
Use implementation-planner skill for improvements:

Component: src/review/pattern_analyzer.py
Improvements needed:
- Add statistical significance testing (P1)
- Add cross-validation (P1)
- Add pattern explanations (P2)
- Add performance optimization (P2)
```

**Claude's Response:**
```
I'll create an improvement tracking plan for: pattern_analyzer.py

Priority breakdown:
- P1 (Critical): 2 improvements, 5-7 hours
- P2 (Important): 2 improvements, 5-7 hours

I'll generate:
1. Improvement tracking: docs/PATTERN_ANALYZER_IMPROVEMENTS.md
2. Quick status table
3. Task checklist with success criteria

Proceed? (yes/no)
```

---

## Creating New Skills

### Step 1: Identify a Pattern

Look for repetitive tasks where you explain the same thing multiple times:

**Good candidates:**
- "Create a plan following the format in HUMAN_REVIEW_SYSTEM_PLAN.md"
- "Evaluate this module like you did for D1_IMPROVEMENTS_FINAL.md"
- "Generate tests following the patterns in tests/unit/"
- "Create a migration like sql/07_create_review_schema.sql"

**Poor candidates:**
- One-off tasks
- Tasks without clear patterns
- Highly variable requirements

### Step 2: Create Skill File

```bash
# Create in .claude/skills/ directory
touch .claude/skills/my-skill-name.md
```

**File structure:**
```markdown
# {Skill Name} Skill

**Purpose:** {One sentence description}

**When to use:** {Specific scenarios}
**When NOT to use:** {Anti-patterns}

---

## {Skill Name} Methodology

{Explain the pattern/methodology this skill follows}

### Key Conventions

- {Convention 1}
- {Convention 2}
- {Convention 3}

---

## Skill Instructions

When this skill is invoked, you should:

1. **Step 1:** {What to do first}
2. **Step 2:** {What to do second}
3. **Step 3:** {What to generate}

---

## Templates

{Include templates that show the expected output format}

---

## Examples

{Provide 2-3 examples of skill usage}

---

## Validation

Before presenting output, check:
- {Validation criterion 1}
- {Validation criterion 2}
```

### Step 3: Extract Patterns

Reference existing documents that show the pattern:

```markdown
## Example: {Feature}

**Input:** {User request}

**Output:** {Generated document}

**Reference files:**
- `{filepath}` - {What pattern to follow}
- `{filepath}` - {What to reference}
```

### Step 4: Test the Skill

Test with 3 scenarios:
1. **Simple** - Minimal complexity
2. **Medium** - Typical use case
3. **Complex** - Edge cases

### Step 5: Document Usage

Add to `docs/CLAUDE_SKILLS_QUICKSTART.md` and `CLAUDE.md`

---

## Best Practices

### ✅ Do:

1. **Include clear examples**
   - Show input and expected output
   - Reference existing files as templates

2. **Define "when NOT to use"**
   - Prevents skill misuse
   - Guides appropriate application

3. **Provide validation criteria**
   - Skills should self-validate before output
   - Check for common errors

4. **Use consistent formatting**
   - Match project documentation style
   - Follow markdown conventions

5. **Version your skills**
   - Add version history at bottom
   - Note when patterns change

### ❌ Don't:

1. **Make skills too broad**
   - "Do anything" skills aren't useful
   - Focus on specific patterns

2. **Hardcode values**
   - Use parameters/placeholders
   - Allow customization

3. **Skip testing**
   - Untested skills create bad output
   - Validate on real scenarios

4. **Forget to update**
   - Skills become stale as project evolves
   - Review quarterly

---

## Skill Development Workflow

### For New Skills:

1. **Identify pattern** (repetitive task)
2. **Create skill file** in `.claude/skills/`
3. **Extract templates** from existing docs
4. **Test with 3 scenarios**
5. **Document in CLAUDE.md**
6. **Add to quickstart guide**

### For Skill Updates:

1. **Notice pattern change** (e.g., new testing framework)
2. **Update skill file** with new conventions
3. **Increment version number**
4. **Test updated skill**
5. **Update documentation**

---

## Troubleshooting

### Problem: Claude doesn't use the skill

**Solution:**
- Explicitly request: "Use {skill-name} skill"
- Check skill file is in `.claude/skills/`
- Verify skill name matches file name

### Problem: Skill generates wrong format

**Solution:**
- Update skill file with clearer instructions
- Add more examples to skill
- Include validation criteria
- Reference specific template files

### Problem: Skill is too rigid

**Solution:**
- Add parameters for customization
- Include "variations" section
- Allow user override of defaults

### Problem: Skill becomes outdated

**Solution:**
- Review skills quarterly
- Update when patterns change
- Version track changes
- Test after updates

---

## Integration with Project Workflow

### Planning Phase
```
1. Use implementation-planner skill → Generate plan
2. Review plan → Adjust if needed
3. Copy to docs/{FEATURE}_PLAN.md
4. Add to DEVELOPMENT_PLAN.md tracking
```

### Implementation Phase
```
1. Follow plan from implementation-planner
2. Create code
3. Use code-module-grader skill → Evaluate quality
4. Address P1/P2 improvements
```

### Testing Phase
```
1. Use test-coverage-analyzer skill → Find gaps
2. Generate test files
3. Run tests
4. Iterate until coverage target met
```

### Documentation Phase
```
1. Use documentation-sync-validator skill → Check for stale docs
2. Apply suggested fixes
3. Update CLAUDE.md if needed
4. Commit changes
```

---

## Advanced: Skill Composition

Skills can reference other skills:

**Example:**
```markdown
# Code Module Grader Skill

## Step 3: Generate Improvement Plan

If P1/P2/P3 improvements identified:
- Invoke implementation-planner skill
- Pass improvements as input
- Generate improvement tracking document
```

This creates a workflow:
```
code-module-grader → Identifies improvements
                  → Calls implementation-planner
                  → Generates improvement tracking doc
```

---

## Measuring Skill Effectiveness

Track these metrics:

### Context Reduction
```
Before skill: 5,000 tokens to explain pattern
After skill: 500 tokens to invoke
Reduction: 90%
```

### Time Savings
```
Before skill: 5 minutes explaining + 10 minutes generating = 15 min
After skill: 30 seconds invoking + 2 minutes generating = 2.5 min
Savings: 83%
```

### Consistency
```
Before skill: 3 plans, 3 different formats
After skill: 3 plans, identical format
Consistency: 100%
```

### Quality
```
Before skill: 60% match to project patterns
After skill: 95%+ match to project patterns
Improvement: 58%
```

---

## Skill Catalog

Maintain a catalog of all skills:

| Skill | Purpose | When to Use | Time Saved | Context Saved |
|-------|---------|-------------|------------|---------------|
| implementation-planner | Generate structured plans | Starting new features | 12 min | 90% |
| code-module-grader | Evaluate code quality | After implementation | TBD | TBD |
| test-coverage-analyzer | Find test gaps | Testing phase | TBD | TBD |
| database-migration-helper | Generate migrations | Schema changes | TBD | TBD |
| documentation-sync-validator | Check doc accuracy | Monthly maintenance | TBD | TBD |

Update after each skill creation.

---

## FAQs

**Q: How many skills should I create?**
A: Start with 3-5 highest-impact patterns. Add more as needed.

**Q: Can skills call other skills?**
A: Yes! Advanced skills can reference others for composition.

**Q: What if a skill doesn't fit my task?**
A: Don't force it. Skills work best for repetitive patterns.

**Q: How often should I update skills?**
A: Review quarterly or when project patterns change significantly.

**Q: Can I share skills across projects?**
A: Yes, but customize for each project's conventions.

**Q: What's the ideal skill size?**
A: 200-500 lines. Smaller = too specific, Larger = too complex.

---

## Next Steps

1. **Try the implementation-planner skill:**
   ```
   "Use implementation-planner skill to plan [your feature]"
   ```

2. **Review generated plan** - Does it match project patterns?

3. **Provide feedback** - What works? What needs adjustment?

4. **Create skill #2** - Follow CLAUDE_SKILLS_DEVELOPMENT_PLAN.md

5. **Measure impact** - Track time/context saved

---

## Resources

- **Development Plan:** `docs/CLAUDE_SKILLS_DEVELOPMENT_PLAN.md`
- **Skill Directory:** `.claude/skills/`
- **Project Patterns:** `CLAUDE.md`
- **Example Plans:** `docs/HUMAN_REVIEW_SYSTEM_PLAN.md`, `docs/E1_IMPROVEMENTS_TRACKING.md`

---

## Feedback & Iteration

After using a skill:

1. **What worked well?**
2. **What didn't match expectations?**
3. **What was missing?**
4. **How can it be improved?**

Update skill files based on feedback.

---

**Last Updated:** 2025-12-11
**Version:** 1.0
