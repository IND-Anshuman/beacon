# llm-beacon

Deterministic, tested building blocks for AI pipelines — the WebAssembly / TypeScript
build of [beacon](https://github.com/IND-Anshuman/beacon).

Every function is the exact same `beacon-core` Rust code the Python package runs,
compiled to `wasm32`. The same input produces **byte-identical output** in Node,
the browser, and Python — proven by a shared cross-language golden corpus.

## Install

```sh
npm install llm-beacon
```

## Use

```js
import { init, extractJson, repairJson, parsePartial, detectInjection } from 'llm-beacon';

await init(); // load the wasm once

extractJson('The user wants this: {"intent": "cancel"}');
// => { intent: 'cancel' }

repairJson('{"a": 1, "b": 2,}').value;
// => { a: 1, b: 2 }

parsePartial('{"intent": "canc').value;
// => { intent: 'canc' }

detectInjection('1 OR 1=1').map((f) => f.label);
// => ['sql_injection']
```

Errors are thrown as `Error` objects whose `code` property is beacon's stable
error code (e.g. `json.unterminated_string`).

## API

`extractJson`, `extractJsonDetailed`, `repairJson`, `parsePartial`,
`parseToolCall`, `parseToolCalls`, `validateSchema`, `schemaErrors`,
`normalize`, `hashContent`, `cacheKey`, `redact`, `detectPii`, `template`,
`templateVariables`, `extractCitations`, `detectInjection`, `scanArguments`,
`retryClassify`, `retryBackoffMs`. Full TypeScript types are bundled.

## License

MIT
