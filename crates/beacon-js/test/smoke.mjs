// Node ESM smoke test: load the wasm package and exercise each block.
import assert from 'node:assert/strict';
import * as beacon from '../pkg/index.mjs';

await beacon.init();

// extract / repair / partial
assert.deepEqual(beacon.extractJson('here: {"intent": "cancel"} done'), { intent: 'cancel' });
assert.deepEqual(beacon.repairJson('{"a": 1, "b": 2,}').value, { a: 1, b: 2 });
assert.equal(beacon.repairJson('{"a": 1, "b": 2,}').repairs[0].kind, 'trailing_comma');
const partial = beacon.parsePartial('{"intent": "canc');
assert.deepEqual(partial.value, { intent: 'canc' });
assert.equal(partial.complete, false);

// tool calls
assert.deepEqual(beacon.parseToolCall('search(query="rust", limit=5)'), {
  name: 'search',
  arguments: { query: 'rust', limit: 5 },
});

// schema
assert.equal(beacon.schemaErrors({ n: 'x' }, { type: 'object', properties: { n: { type: 'integer' } } }).length, 1);
beacon.validateSchema({ n: 1 }, { type: 'object', properties: { n: { type: 'integer' } } });

// normalize / hash / cache
assert.equal(beacon.normalize('Hello   World\n\n'), 'Hello World');
assert.equal(beacon.hashContent({ a: 1, b: 2 }), beacon.hashContent({ b: 2, a: 1 }));
assert.equal(beacon.cacheKey(['sys', 'prompt']).length, 32); // length is hex-char count

// redact / pii
assert.equal(beacon.redact('Email me at alice@example.com'), 'Email me at [REDACTED:email]');
assert.equal(beacon.detectPii('alice@example.com')[0].label, 'email');

// template
assert.equal(beacon.template('Hi {name}', { name: 'Al' }), 'Hi Al');
assert.deepEqual(beacon.templateVariables('{b} and {a}'), ['b', 'a']);

// citations / injection
assert.equal(beacon.extractCitations('see [1] and [^a]')[0].ref, '1');
assert.deepEqual(beacon.detectInjection('1 OR 1=1').map((f) => f.label), ['sql_injection']);
assert.equal(beacon.scanArguments({ q: "x'; DROP TABLE t" })[0].path, '/q');

// retry
const d = beacon.retryClassify({ status: 429, attempt: 1 });
assert.equal(d.retry, true);
assert.equal(typeof beacon.retryBackoffMs({ attempt: 1 }), 'number');

// errors carry a code
try {
  beacon.extractJson('no json here at all', { required: true });
  throw new Error('expected a throw');
} catch (e) {
  assert.equal(typeof e.code, 'string');
  assert.ok(e.code.startsWith('json.'));
}

console.log('smoke: all assertions passed');
