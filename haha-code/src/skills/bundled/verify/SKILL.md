---
name: verify
description: >
  Verify a code change does what it should by running the app.
  Use this when reviewing a PR, after making a feature change, or when asked to
  "check if it works", "test the change", "verify the fix", "make sure nothing
  broke", or "validate the implementation". Also trigger when the user mentions
  smoke testing, end-to-end verification, manual testing, or running the app to
  confirm behavior.
---

# Verify a Code Change

## Goal

Confirm the change does what it should — and doesn't break existing behavior.

## Steps

1. **Understand the change** — check the diff or recent commits to know what was modified
2. **Build/lint** — ensure the project compiles and passes any lint/type checks
3. **Run tests** — execute existing test suites; add new tests if none exist for the changed area
4. **Manual smoke test** — start the app and exercise the changed path end-to-end
5. **Edge cases** — think about boundary conditions, error paths, and regression scenarios
6. **Report** — summarize what you tested, what passed, and what failed (with specifics)

## What to look for

- Functional correctness: does the feature behave as expected?
- Regressions: did something unrelated break?
- UX: are there visual glitches, broken layouts, or confusing interactions?
- Performance: is anything noticeably slower?
