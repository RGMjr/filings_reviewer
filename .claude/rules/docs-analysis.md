---
paths:
  - "docs/analysis/**"
---

# docs/analysis/

## Placement

Evaluation results, validation reports, and bakeoff results belong in `docs/analysis/`, not `docs/operations/`. Operations is for runbooks and procedures; analysis is for evaluation outputs. When writing a new eval/validation/bakeoff doc, default here.

## README maintenance

`docs/analysis/README.md` is an actively curated index that lists and describes every current file in the folder. Unlike other `docs/` subfolders, this README must be updated whenever files are added to or removed from `docs/analysis/` — including when files arrive from other folders (e.g. misplaced ops files being relocated). Verify the index after any add/remove/move that touches this folder.
