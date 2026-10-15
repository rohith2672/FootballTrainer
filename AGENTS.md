# Working in FootballTrainer

Read `MEMORY.md` first for the current session handoff, then `CLAUDE.md` for
historical tickets and project rules. Check the actual branch and source before
relying on either document; recorded validation is not a current test result.

## Project rules

- Features must use only information available strictly before the predicted match.
- Keep training, validation, and evaluation chronological; never randomly split matches.
- Keep database ingestion idempotent and credentials in environment variables.
- Complete and verify one scoped task at a time. Preserve unrelated user changes.
- Keep training and inference feature ordering consistent with `FEATURE_COLS`.
- Use an isolated test database for integration tests and temporary artifact paths
  for training tests; existing tests are not fully isolated from configured storage.

## Session continuity

- The user selected `dev` as the working branch. Verify with `git branch -vv`;
  do not automatically switch branches in a later session with uncommitted work.
- Update `MEMORY.md` after meaningful work with changes, actual verification,
  unresolved issues, and the next agreed task. Keep secrets out of the handoff.
- Preserve historical ticket records in `CLAUDE.md`; clearly label newer context.
- Do not assume that multi-league fixture display means multi-league training data
  exists, or that fallback probabilities are predictions from the model.
