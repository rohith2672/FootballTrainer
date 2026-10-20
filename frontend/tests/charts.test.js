import test from 'node:test';
import assert from 'node:assert/strict';
import {
  indexX,
  labelStep,
  lineGeometry,
  linearScale,
  nearestIndex,
  niceAxis,
  pathOf,
  placeTooltip,
  plottedIndexes,
  segments,
  stepIndex,
} from '../src/lib/charts.js';

const MARGIN = { top: 10, right: 10, bottom: 40, left: 50 };

test('niceAxis covers the range with round ticks and widens flat ranges', () => {
  const axis = niceAxis(0.93, 1.07);
  assert.ok(axis.min <= 0.93 && axis.max >= 1.07);
  assert.deepEqual(axis.ticks, [0.9, 0.95, 1, 1.05, 1.1]);

  const flat = niceAxis(1.0, 1.0); // log-loss default min span 0.02
  assert.ok(flat.min <= 0.98 && flat.max >= 1.02);

  const elo = niceAxis(1700, 1702, { minSpan: 10 });
  assert.ok(elo.min <= 1691 && elo.max >= 1711);
  assert.ok(elo.ticks.every((t) => Number.isInteger(t)));

  assert.deepEqual(niceAxis(null, 3), { min: 0, max: 1, ticks: [0, 1] });
});

test('linearScale maps the domain, and a zero-width domain to the midpoint', () => {
  const s = linearScale(0, 10, 100, 0);
  assert.equal(s(0), 100);
  assert.equal(s(10), 0);
  assert.equal(s(2.5), 75);
  assert.equal(linearScale(5, 5, 0, 200)(5), 100);
});

test('indexX spreads points evenly and centres a single point', () => {
  assert.equal(indexX(0, 1, 50, 200), 150);
  assert.equal(indexX(0, 3, 50, 200), 50);
  assert.equal(indexX(2, 3, 50, 200), 250);
});

test('labelStep keeps x labels apart', () => {
  assert.equal(labelStep(5, 600), 1);
  assert.equal(labelStep(60, 280), 15); // 4 labels fit at 70px
  assert.equal(labelStep(0, 300), 1);
});

test('lineGeometry lays out values, keeps gaps and returns null without data', () => {
  assert.equal(lineGeometry([null, null], { width: 400, height: 200, margin: MARGIN }), null);
  assert.equal(lineGeometry([], { width: 400, height: 200, margin: MARGIN }), null);

  const g = lineGeometry([1, null, 3], { width: 400, height: 200, margin: MARGIN, minSpan: 0.1 });
  assert.equal(g.xs.length, 3);
  assert.equal(g.ys[1], null);
  assert.equal(g.xs[0], MARGIN.left);
  assert.equal(g.xs[2], 400 - MARGIN.right);
  // Higher values sit higher on screen (smaller y).
  assert.ok(g.ys[2] < g.ys[0]);
  assert.equal(g.bottom, 200 - MARGIN.bottom);
  assert.ok(g.ys.every((y) => y === null || (y >= MARGIN.top && y <= g.bottom)));
});

test('segments break on missing values and pathOf draws each run', () => {
  const runs = segments([0, 10, 20, 30], [5, null, 7, 8]);
  assert.equal(runs.length, 2);
  assert.deepEqual(runs[1].map((p) => p.i), [2, 3]);
  assert.equal(pathOf(runs[1]), 'M20.0,7.0 L30.0,8.0');
});

test('nearestIndex finds the closest plotted point by x', () => {
  const xs = [0, 10, 20, 30];
  assert.equal(nearestIndex(xs, [1, 1, 1, 1], 14), 1);
  assert.equal(nearestIndex(xs, [1, 1, 1, 1], 16), 2);
  assert.equal(nearestIndex(xs, [1, 1, 1, 1], 15), 1); // tie → earlier
  assert.equal(nearestIndex(xs, [1, null, 1, 1], 9), 0); // skips gaps
  assert.equal(nearestIndex(xs, [1, null, 1, 1], 11), 2);
  assert.equal(nearestIndex(xs, [null, null, null, null], 11), -1);
  assert.equal(nearestIndex(xs, [1, 1, 1, 1], -500), 0);
  assert.equal(nearestIndex(xs, [1, 1, 1, 1], 900), 3);
});

test('stepIndex moves between plotted points with arrow keys, Home and End', () => {
  const plotted = plottedIndexes([1, null, 2, 3]);
  assert.deepEqual(plotted, [0, 2, 3]);
  assert.equal(stepIndex(plotted, 0, 'ArrowRight'), 2);
  assert.equal(stepIndex(plotted, 2, 'ArrowLeft'), 0);
  assert.equal(stepIndex(plotted, 3, 'ArrowRight'), 3); // stays at the end
  assert.equal(stepIndex(plotted, 0, 'ArrowLeft'), 0);
  assert.equal(stepIndex(plotted, 2, 'Home'), 0);
  assert.equal(stepIndex(plotted, 0, 'End'), 3);
  assert.equal(stepIndex(plotted, 2, 'a'), 2);
  assert.equal(stepIndex([], 4, 'ArrowRight'), 4);
});

test('placeTooltip clamps horizontally and flips below near the top', () => {
  const mid = placeTooltip({ x: 200, y: 150, tipW: 100, tipH: 50, width: 400 });
  assert.deepEqual(mid, { left: 150, anchorY: 138, placement: 'above' });

  const left = placeTooltip({ x: 5, y: 150, tipW: 100, tipH: 50, width: 400 });
  assert.equal(left.left, 4);

  const right = placeTooltip({ x: 398, y: 150, tipW: 100, tipH: 50, width: 400 });
  assert.equal(right.left, 296); // 400 - 100 - 4

  const top = placeTooltip({ x: 200, y: 20, tipW: 100, tipH: 50, width: 400 });
  assert.equal(top.placement, 'below');
  assert.equal(top.anchorY, 32);

  // Wider than the box: pinned to the left padding, never negative.
  const huge = placeTooltip({ x: 50, y: 150, tipW: 500, tipH: 50, width: 300 });
  assert.equal(huge.left, 4);
});
