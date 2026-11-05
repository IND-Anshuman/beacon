// Typed public API for llm-beacon (the WebAssembly build of beacon-core).
// Deterministic building blocks for AI pipelines; same input -> same output,
// byte-identical to the Python package.

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export type Select = 'first' | 'last' | 'largest' | 'only';
export type Kind = 'auto' | 'any' | 'object' | 'array';
export type Escape = 'xml' | 'json' | 'none';
export type Form = 'NFC' | 'NFD' | 'NFKC' | 'NFKD';
export type RedactPolicy = 'default' | 'strict' | 'secrets' | 'pii' | 'none';
export type CitationKind = 'numeric' | 'footnote' | 'url';
export type InjectionPolicy = 'default' | 'none';

export interface Extraction {
  value: JsonValue;
  start: number;
  end: number;
  source: string;
  candidates: number;
}

export interface Repair {
  kind: string;
  at: number;
  detail: string;
}

export interface RepairResult {
  value: JsonValue;
  repairs: Repair[];
  incomplete: boolean;
}

export interface PartialResult {
  value: JsonValue;
  complete: boolean;
  consumed: number;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, JsonValue>;
  format?: string;
}

export interface SchemaViolation {
  path: string;
  keyword: string;
  message: string;
}

export interface PiiFinding {
  label: string;
  start: number;
  end: number;
  text: string;
}

export interface Citation {
  kind: CitationKind;
  ref: string;
  start: number;
  end: number;
  text: string;
}

export interface InjectionFinding {
  label: string;
  severity: string;
  start: number;
  end: number;
  text: string;
  path: string;
}

export interface RetryDecision {
  retry: boolean;
  reason: string;
  delay_ms: number;
  attempt: number;
}

/** A thrown error carries beacon's stable `code`. */
export interface BeaconError extends Error {
  code: string;
}

/** Load the WebAssembly module once before calling any function. */
export function init(input?: BufferSource | WebAssembly.Module | URL | Request | Response): Promise<unknown>;

export function extractJson(text: string, opts?: { select?: Select; kind?: Kind; required?: boolean }): JsonValue;
export function extractJsonDetailed(text: string, opts?: { select?: Select; kind?: Kind }): Extraction;
export function repairJson(text: string): RepairResult;
export function parsePartial(text: string): PartialResult;
export function parseToolCall(text: string): ToolCall;
export function parseToolCalls(text: string, opts?: { includeFormat?: boolean }): ToolCall[];
export function validateSchema(instance: JsonValue, schema: JsonValue): void;
export function schemaErrors(instance: JsonValue, schema: JsonValue): SchemaViolation[];
export function normalize(
  text: string,
  opts?: {
    form?: Form | null;
    stripAccents?: boolean;
    lowercase?: boolean;
    removeControl?: boolean;
    removeZeroWidth?: boolean;
    collapseWhitespace?: boolean;
    preserveNewlines?: boolean;
    strip?: boolean;
  },
): string;
export function hashContent(value: JsonValue, opts?: { length?: number }): string;
export function cacheKey(parts: JsonValue[], opts?: { length?: number }): string;
export function redact(text: string, opts?: { policy?: RedactPolicy; replacement?: string }): string;
export function detectPii(text: string, opts?: { policy?: RedactPolicy }): PiiFinding[];
export function template(source: string, variables?: Record<string, string | number | boolean>, opts?: { escape?: Escape; strict?: boolean }): string;
export function templateVariables(source: string): string[];
export function extractCitations(text: string, opts?: { kinds?: CitationKind[] }): Citation[];
export function detectInjection(text: string, opts?: { policy?: InjectionPolicy }): InjectionFinding[];
export function scanArguments(args: JsonValue, opts?: { policy?: InjectionPolicy }): InjectionFinding[];
export function retryClassify(opts: {
  typeNames?: string[];
  status?: number | null;
  retryAfter?: string | null;
  retryAfterMs?: string | null;
  attempt: number;
  maxAttempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  jitterPercent?: number;
  jitterKey?: string;
}): RetryDecision;
export function retryBackoffMs(opts: {
  attempt: number;
  maxAttempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  jitterPercent?: number;
  jitterKey?: string;
}): number;
