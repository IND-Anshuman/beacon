// Vercel AI SDK adapter for llm-beacon.
//
// No dependency on the `ai` package: results and tool calls are duck-typed, so
// the real `generateText` / `generateObject` results, plain objects and test
// fakes all work. Mirrors the behavior of beacon's Python framework adapters:
// tool calls normalize to `{ name, arguments }`, unknown tools and invalid
// arguments throw an Error whose `.code` is provider-prefixed (`vercel.*`), and
// schema violations carry the offending value as `.raw`.
//
// Call `await init()` once (from the main package) before using these.

import { extractJson, validateSchema } from './index.mjs';

function codedError(message, code, raw) {
  const err = new Error(message);
  err.code = code;
  if (raw !== undefined) err.raw = raw;
  return err;
}

function normalizeArgs(name, rawArgs) {
  if (rawArgs === null || rawArgs === undefined) return {};
  if (typeof rawArgs === 'string') {
    let parsed;
    try {
      parsed = JSON.parse(rawArgs);
    } catch {
      throw codedError(`tool call arguments for "${name}" are not valid JSON`, 'vercel.invalid_arguments');
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw codedError(`tool call arguments for "${name}" are not an object`, 'vercel.invalid_arguments');
    }
    return parsed;
  }
  if (typeof rawArgs === 'object' && !Array.isArray(rawArgs)) return rawArgs;
  throw codedError(`tool call arguments for "${name}" are not an object`, 'vercel.invalid_arguments');
}

/**
 * Build a `{ name: schema }` map from AI SDK tool definitions that carry a JSON
 * Schema. `tools` is the SDK `tools` object (keyed by tool name); each entry's
 * `parameters` / `inputSchema` is used when it is a plain JSON Schema object
 * (e.g. from the SDK's `jsonSchema()` helper). Zod-only definitions are skipped.
 */
export function toolSchemas(tools) {
  const out = {};
  for (const [name, def] of Object.entries(tools ?? {})) {
    const schema = def?.parameters ?? def?.inputSchema ?? def?.schema;
    if (schema && typeof schema === 'object' && !Array.isArray(schema)) {
      // A Zod schema is an object too; only keep things that look like JSON Schema.
      if ('type' in schema || 'properties' in schema || '$ref' in schema || 'anyOf' in schema) {
        out[name] = schema;
      }
    }
  }
  return out;
}

/**
 * Normalize a Vercel AI SDK result's tool calls to `[{ name, arguments }]`.
 *
 * `result` may be a `generateText` result (with a `toolCalls` array), an array
 * of tool calls, or a single tool call. `toolSchemas` (optional) maps tool
 * names to JSON Schemas; a call to a name not in it throws `vercel.unknown_tool`,
 * and arguments that violate the schema rethrow beacon's schema error with the
 * arguments attached as `.raw`.
 */
export function validatedToolCalls(result, toolSchemas) {
  let rawCalls;
  if (Array.isArray(result)) rawCalls = result;
  else if (result && Array.isArray(result.toolCalls)) rawCalls = result.toolCalls;
  else rawCalls = [result];

  const calls = rawCalls.map((call) => {
    const name = call?.toolName ?? call?.name;
    if (name === undefined || name === null) {
      throw codedError('tool call has no name', 'vercel.invalid_call');
    }
    const rawArgs = call?.args ?? call?.input ?? call?.arguments;
    return { name: String(name), arguments: normalizeArgs(name, rawArgs) };
  });

  if (toolSchemas) {
    for (const call of calls) {
      const schema = toolSchemas[call.name];
      if (schema === undefined) {
        throw codedError(`model called unknown tool "${call.name}"`, 'vercel.unknown_tool');
      }
      try {
        validateSchema(call.arguments, schema);
      } catch (err) {
        err.raw = JSON.stringify(call.arguments);
        throw err;
      }
    }
  }
  return calls;
}

/**
 * Extract and validate structured output from a Vercel AI SDK result.
 *
 * A `generateObject` result (with `.object`) is validated directly; otherwise
 * the result's `.text` (or a plain string) is parsed with beacon's
 * `extractJson`. `schema` (optional) validates the value. Throws
 * `vercel.no_content` when there is no object or text.
 */
export function parseOutput(result, { schema, select = 'first', kind = 'auto' } = {}) {
  if (result && typeof result === 'object' && 'object' in result && result.object !== undefined) {
    const value = result.object;
    if (schema) {
      try {
        validateSchema(value, schema);
      } catch (err) {
        err.raw = JSON.stringify(value);
        throw err;
      }
    }
    return value;
  }
  const text = typeof result === 'string' ? result : result?.text;
  if (typeof text !== 'string') {
    throw codedError('result has no text or object content', 'vercel.no_content');
  }
  const value = extractJson(text, { select, kind });
  if (schema) {
    try {
      validateSchema(value, schema);
    } catch (err) {
      err.raw = text;
      throw err;
    }
  }
  return value;
}
