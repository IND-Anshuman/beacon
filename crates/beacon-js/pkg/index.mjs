// Typed facade over the wasm-bindgen output. The low-level exports in
// `beacon_js.js` take/return JSON text (so output is byte-identical to the
// Python package); this wraps them into idiomatic functions that accept and
// return JavaScript values. Throws the same Error objects (with a `.code`).

import initWasm, * as wasm from './beacon_js.js';

let readyPromise;

/**
 * Load the WebAssembly module. Call once and `await` it before using any
 * function. In Node you may call `init()` with no argument (it reads the
 * bundled `.wasm`); in the browser it fetches the bundled `.wasm`.
 */
export async function init(input) {
  if (readyPromise) return readyPromise;
  if (input === undefined && typeof process !== 'undefined' && process.versions && process.versions.node) {
    const { readFile } = await import('node:fs/promises');
    input = await readFile(new URL('./beacon_js_bg.wasm', import.meta.url));
  }
  readyPromise = input === undefined ? initWasm() : initWasm({ module_or_path: input });
  await readyPromise;
  return readyPromise;
}

const parse = (s) => JSON.parse(s);

export function extractJson(text, { select = 'first', kind = 'auto', required = true } = {}) {
  return parse(wasm.extractJson(text, select, kind, required));
}

export function extractJsonDetailed(text, { select = 'first', kind = 'auto' } = {}) {
  return parse(wasm.extractJsonDetailed(text, select, kind));
}

export function repairJson(text) {
  return parse(wasm.repairJson(text));
}

export function parsePartial(text) {
  return parse(wasm.parsePartial(text));
}

export function parseToolCall(text) {
  return parse(wasm.parseToolCall(text, false));
}

export function parseToolCalls(text, { includeFormat = false } = {}) {
  return parse(wasm.parseToolCalls(text, includeFormat));
}

export function validateSchema(instance, schema) {
  wasm.validateSchema(JSON.stringify(instance), JSON.stringify(schema));
}

export function schemaErrors(instance, schema) {
  return parse(wasm.schemaErrors(JSON.stringify(instance), JSON.stringify(schema)));
}

export function normalize(text, opts = {}) {
  const {
    form = 'NFKC',
    stripAccents = false,
    lowercase = false,
    removeControl = true,
    removeZeroWidth = true,
    collapseWhitespace = true,
    preserveNewlines = false,
    strip = true,
  } = opts;
  return wasm.normalize(
    text,
    form,
    stripAccents,
    lowercase,
    removeControl,
    removeZeroWidth,
    collapseWhitespace,
    preserveNewlines,
    strip,
  );
}

export function hashContent(value, { length = 16 } = {}) {
  return wasm.hashContent(JSON.stringify(value), length);
}

export function cacheKey(parts, { length = 32 } = {}) {
  if (!Array.isArray(parts) || parts.length === 0) {
    throw new Error('cacheKey requires a non-empty array of parts');
  }
  return wasm.cacheKey(JSON.stringify(parts), length);
}

export function redact(text, { policy = 'default', replacement = '[REDACTED:{label}]' } = {}) {
  return wasm.redact(text, policy, replacement);
}

export function detectPii(text, { policy = 'default' } = {}) {
  return parse(wasm.detectPii(text, policy));
}

export function template(source, variables = {}, { escape = 'xml', strict = true } = {}) {
  return wasm.template(source, JSON.stringify(variables), escape, strict);
}

export function templateVariables(source) {
  return parse(wasm.templateVariables(source));
}

export function extractCitations(text, { kinds = ['numeric', 'footnote', 'url'] } = {}) {
  return parse(wasm.extractCitations(text, JSON.stringify(kinds)));
}

export function detectInjection(text, { policy = 'default' } = {}) {
  return parse(wasm.detectInjection(text, policy));
}

export function scanArguments(args, { policy = 'default' } = {}) {
  return parse(wasm.scanArguments(JSON.stringify(args), policy));
}

export function retryClassify({
  typeNames = [],
  status = null,
  retryAfter = null,
  retryAfterMs = null,
  attempt,
  maxAttempts = 5,
  baseDelayMs = 1000,
  maxDelayMs = 60000,
  jitterPercent = 20,
  jitterKey = '',
}) {
  return parse(
    wasm.retryClassify(
      JSON.stringify(typeNames),
      status,
      retryAfter,
      retryAfterMs,
      attempt,
      maxAttempts,
      baseDelayMs,
      maxDelayMs,
      jitterPercent,
      jitterKey,
    ),
  );
}

export function retryBackoffMs({
  attempt,
  maxAttempts = 5,
  baseDelayMs = 1000,
  maxDelayMs = 60000,
  jitterPercent = 20,
  jitterKey = '',
}) {
  return wasm.retryBackoffMs(attempt, maxAttempts, baseDelayMs, maxDelayMs, jitterPercent, jitterKey);
}
