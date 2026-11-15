// Vercel AI SDK adapter for llm-beacon. Duck-typed: no dependency on `ai`.
// Behavior matches beacon's Python framework adapters.

import type { JsonValue, ToolCall } from './index';

/** A normalized tool call: the SDK's `toolName`/`args` as beacon's shape. */
export interface NormalizedToolCall {
  name: string;
  arguments: Record<string, JsonValue>;
}

/**
 * Build a `{ name: schema }` map from AI SDK tool definitions that carry a JSON
 * Schema (e.g. via the SDK's `jsonSchema()` helper). Zod-only definitions are
 * skipped, since a Zod schema is not a JSON Schema.
 */
export function toolSchemas(tools: Record<string, unknown>): Record<string, JsonValue>;

/**
 * Normalize a Vercel AI SDK result's tool calls to `{ name, arguments }`.
 *
 * Accepts a `generateText` result (with `toolCalls`), an array of tool calls,
 * or a single tool call. When `toolSchemas` is given, a call to an unknown tool
 * throws an `Error` whose `.code` is `vercel.unknown_tool`; arguments that
 * violate the schema rethrow beacon's schema error with `.raw` set. Arguments
 * supplied as a JSON string are parsed strictly (`vercel.invalid_arguments`).
 */
export function validatedToolCalls(
  result: unknown,
  toolSchemas?: Record<string, JsonValue>,
): NormalizedToolCall[];

/**
 * Extract and validate structured output from a Vercel AI SDK result.
 *
 * A `generateObject` result (with `.object`) is validated directly; otherwise
 * the result's `.text` (or a plain string) is parsed with `extractJson`.
 * Throws `vercel.no_content` when there is neither. The thrown `Error` carries
 * beacon's stable `code`, and schema violations carry the value as `.raw`.
 */
export function parseOutput(
  result: unknown | string,
  opts?: { schema?: JsonValue; select?: 'first' | 'last' | 'largest' | 'only'; kind?: 'auto' | 'any' | 'object' | 'array' },
): JsonValue;

export type { ToolCall };
