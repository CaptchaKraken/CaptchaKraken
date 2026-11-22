// Records python/tests/fixtures/myuri_cross_port.json from the JS port: `npm run build && node scripts/record-mouse-cross-port.cjs`.
// Never re-record to make the Python test pass: a failure there means the two drivers started moving differently.
const fs = require('node:fs');
const path = require('node:path');
const { Motion, trajectory } = require('../dist/humanize.js');

const CASES = [
  { seed: 42, speed: 'human', from: [120, 80], to: [940, 560] },
  { seed: 7, speed: 'human', from: [300, 300], to: [340, 310] },
  { seed: 1234, speed: 'fast', from: [500, 120], to: [180, 400] },
  { seed: 99, speed: 'fast', from: [60, 700], to: [1100, 90], settings: { mouse: { speedFactor: 3 } } },
];

const out = CASES.map((c) => {
  const [points, timings] = trajectory(c.from, c.to, new Motion(c.settings, c.seed, c.speed));
  return { ...c, points, timings };
});
const dest = path.join(__dirname, '..', '..', 'python', 'tests', 'fixtures', 'myuri_cross_port.json');
fs.writeFileSync(dest, JSON.stringify(out) + '\n');
console.log(`wrote ${out.length} cases to ${dest}`);
