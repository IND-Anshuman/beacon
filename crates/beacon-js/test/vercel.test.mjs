// Node ESM test for the Vercel AI SDK adapter (duck-typed fakes, no `ai` dep).
import assert from 'node:assert/strict';
import { init } from '../pkg/index.mjs';
import { parseOutput, toolSchemas, validatedToolCalls } from '../pkg/vercel.mjs';

await init();

const SEARCH = { type: 'object', properties: { q: { type: 'string' } }, required: ['q'] };

// --- validatedToolCalls ---

// generateText result with a toolCalls array (args already an object)
assert.deepEqual(validatedToolCalls({ toolCalls: [{ toolName: 'search', args: { q: 'rust' } }] }), [
  { name: 'search', arguments: { q: 'rust' } },
]);

// args as a JSON string are parsed strictly
assert.deepEqual(validatedToolCalls([{ toolName: 'search', args: '{"q": "go"}' }]), [
  { name: 'search', arguments: { q: 'go' } },
]);

// v5-style `input` field and a single (non-array) call
assert.deepEqual(validatedToolCalls({ toolName: 'search', input: { q: 'zig' } }), [
  { name: 'search', arguments: { q: 'zig' } },
]);

// unknown tool -> vercel.unknown_tool
assert.throws(
  () => validatedToolCalls([{ toolName: 'nope', args: {} }], { search: SEARCH }),
  (e) => e.code === 'vercel.unknown_tool',
);

// schema violation -> beacon error with .raw set
assert.throws(
  () => validatedToolCalls([{ toolName: 'search', args: {} }], { search: SEARCH }),
  (e) => typeof e.code === 'string' && e.raw === '{}',
);

// invalid JSON argument string -> vercel.invalid_arguments
assert.throws(
  () => validatedToolCalls([{ toolName: 'search', args: '{bad' }]),
  (e) => e.code === 'vercel.invalid_arguments',
);

// --- parseOutput ---

// from text via extractJson
assert.deepEqual(parseOutput({ text: 'Here you go: {"intent": "cancel"}' }), { intent: 'cancel' });

// a bare string works too
assert.deepEqual(parseOutput('{"ok": true}'), { ok: true });

// generateObject result (already structured) is validated directly
assert.deepEqual(parseOutput({ object: { ok: true } }, { schema: { type: 'object', required: ['ok'] } }), { ok: true });

// schema violation on text output throws with .code and .raw
assert.throws(
  () => parseOutput({ text: '{"ok": 1}' }, { schema: { type: 'object', properties: { ok: { type: 'boolean' } } } }),
  (e) => typeof e.code === 'string' && typeof e.raw === 'string',
);

// no content -> vercel.no_content
assert.throws(
  () => parseOutput({ finishReason: 'stop' }),
  (e) => e.code === 'vercel.no_content',
);

// --- toolSchemas ---

// JSON-Schema-bearing tool defs are mapped; zod-only ones are skipped
const zodLike = { _def: { typeName: 'ZodObject' } };
assert.deepEqual(toolSchemas({ search: { parameters: SEARCH }, other: { parameters: zodLike } }), { search: SEARCH });

console.log('vercel adapter: all assertions passed');
