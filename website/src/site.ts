/** Site-wide constants. */
export const SITE = {
  name: 'beacon',
  /** PyPI distribution name ("beacon" is taken); the import name is `beacon`. */
  pypi: 'llm-beacon',
  version: '0.1.0',
  tagline: 'Deterministic, tested building blocks for AI pipelines.',
  description:
    'beacon is the deterministic layer between your Python code and your LLM: prompt templates, JSON extraction, tool-call parsing, schema validation, redaction, retry classification and snapshot testing. Same input, same output, every time.',
  repoUrl: process.env.PUBLIC_REPO_URL || 'https://github.com/IND-Anshuman/beacon',
};

/** Prefix an internal path with the configured base (for GitHub Pages project sites). */
export function url(path: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  return `${base}/${path.replace(/^\//, '')}`;
}
