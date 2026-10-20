import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BASELINE_LABELS, baselineLabel } from '../src/lib/trackRecord.js';

// The committed registry's backtest baselines are shown on the Track record
// page; each one needs a human label instead of its raw key.
const registry = JSON.parse(
  readFileSync(new URL('../../src/model/artifacts/model_registry.json', import.meta.url), 'utf8'),
);
// Mirrors RETIRED_BASELINE_MARKER in src/api/track_record.py: these are dropped by the API.
const RETIRED_MARKER = 'bookmaker';

test('every registry baseline has a BASELINE_LABELS entry', () => {
  const keys = Object.keys(registry.baselines ?? {}).filter((k) => !k.includes(RETIRED_MARKER));
  assert.ok(keys.length > 0, 'registry has no baselines');
  for (const key of keys) {
    assert.ok(Object.hasOwn(BASELINE_LABELS, key), `missing BASELINE_LABELS entry for "${key}"`);
    assert.notEqual(baselineLabel(key), key);
  }
});

test('poisson baseline is labelled', () => {
  assert.equal(baselineLabel('poisson'), 'Poisson goals model');
});
