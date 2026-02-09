# Ralph Loop Execution
1. Read the plan file specified by the user
2. Immediately begin implementation (do NOT stay in planning mode)
3. After each file change, run relevant tests
4. Fix any test failures before proceeding
5. When all acceptance criteria are met, run full test suite
6. Stage ONLY the files changed for this task (git add <specific-files>)
7. Commit with descriptive message and push
8. Report: tests passed, coverage %, files changed
