// Renders public/og.png (1200x630 social preview) from an inline SVG.
//   node scripts/build-og.mjs
import sharp from 'sharp';

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#07080c"/>
  <circle cx="1020" cy="110" r="260" fill="#14b8a6" opacity="0.10"/>
  <circle cx="1020" cy="110" r="150" fill="#14b8a6" opacity="0.10"/>
  <text x="80" y="250" font-family="Georgia, 'Times New Roman', serif" font-size="150" fill="#f4f4f5">beacon</text>
  <text x="84" y="340" font-family="Helvetica, Arial, sans-serif" font-size="44" fill="#a1a1aa">The deterministic layer between your</text>
  <text x="84" y="396" font-family="Helvetica, Arial, sans-serif" font-size="44" fill="#a1a1aa">Python code and your LLM.</text>
  <text x="84" y="500" font-family="Menlo, Consolas, monospace" font-size="34" fill="#2dd4bf">same input, same output, every time</text>
  <text x="84" y="570" font-family="Menlo, Consolas, monospace" font-size="28" fill="#71717a">pip install llm-beacon</text>
</svg>`;

await sharp(Buffer.from(svg)).png().toFile('public/og.png');
console.log('wrote public/og.png');
