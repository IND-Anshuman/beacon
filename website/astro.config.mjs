// @ts-check
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

// For a GitHub Pages project site set SITE_URL=https://<owner>.github.io and
// BASE_PATH=/beacon (the deploy workflow does this automatically).
const site = process.env.SITE_URL ?? 'http://localhost:4321';
const base = process.env.BASE_PATH ?? '/';
const repoUrl = process.env.PUBLIC_REPO_URL || 'https://github.com/IND-Anshuman/beacon';

export default defineConfig({
  site,
  base,
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: 'beacon',
      description: 'Deterministic, tested building blocks for AI pipelines.',
      logo: { src: './src/assets/logo.svg', replacesTitle: false },
      favicon: '/favicon.svg',
      social: [{ icon: 'github', label: 'GitHub', href: repoUrl }],
      editLink: { baseUrl: `${repoUrl}/edit/main/website/` },
      lastUpdated: false,
      // The 404 page is a custom page (src/pages/404.astro) with base-aware links.
      disable404Route: true,
      customCss: ['./src/styles/fonts.css', './src/styles/docs.css'],
      components: {
        SiteTitle: './src/components/docs/SiteTitle.astro',
      },
      expressiveCode: {
        themes: ['github-dark-default', 'github-light-default'],
        defaultProps: { wrap: true, preserveIndent: true },
        styleOverrides: {
          borderRadius: '10px',
          codeFontFamily: "'Geist Mono Variable', 'JetBrains Mono', ui-monospace, monospace",
          codeFontSize: '0.84rem',
          uiFontFamily: "'Geist Variable', 'Inter', system-ui, sans-serif",
        },
      },
      sidebar: [
        {
          label: 'Getting started',
          items: [
            'getting-started/introduction',
            'getting-started/installation',
            'getting-started/quickstart',
            'getting-started/core-concepts',
          ],
        },
        {
          label: 'Guarantees',
          items: ['guarantees/determinism', 'guarantees/errors'],
        },
        {
          label: 'Blocks',
          items: [
            'blocks/template',
            'blocks/extract-json',
            'blocks/parse-tool-call',
            'blocks/validate-schema',
            'blocks/normalize',
            'blocks/hash-content',
            'blocks/redact',
            'blocks/retry',
            'blocks/pipelines',
          ],
        },
        {
          label: 'Snapshot testing',
          items: ['snapshots/overview', 'snapshots/pytest', 'snapshots/ci'],
        },
        {
          label: 'Integrations',
          items: [
            'integrations/overview',
            'integrations/openai',
            'integrations/langchain',
            'integrations/llamaindex',
            'integrations/pydantic-ai',
            'integrations/dspy',
          ],
        },
        {
          label: 'Reference',
          items: [
            'reference/api',
            'reference/error-codes',
            'reference/changelog',
            { label: 'Playground', link: '/playground/', badge: { text: 'live', variant: 'tip' } },
          ],
        },
      ],
    }),
  ],
});
