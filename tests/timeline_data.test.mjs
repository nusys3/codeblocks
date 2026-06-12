import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";

const context = { window: {} };
vm.runInNewContext(readFileSync("public/economic-timeline/app-data.js", "utf8"), context);
const data = context.window.TIMELINE_SEED;

assert.equal(data.generatedAt, "2026-06-11");
assert.ok(Array.isArray(data.taxonomy) && data.taxonomy.length >= 4);
assert.ok(Array.isArray(data.events) && data.events.length >= 30);

for (const event of data.events) {
  assert.match(event.date, /^\d{4}-\d{2}-\d{2}$/);
  assert.ok(data.taxonomy.some((topic) => topic.id === event.category), `${event.id} has unknown category`);
  assert.ok(["confirmed", "conditional", "watch"].includes(event.confidence), `${event.id} has unknown confidence`);
  assert.ok(event.sources.length > 0, `${event.id} needs at least one source`);
  for (const source of event.sources) assert.ok(data.sources[source], `${event.id} has missing source ${source}`);
}

const ids = data.events.map((event) => event.id);
assert.equal(new Set(ids).size, ids.length, "event ids must be unique");
assert.ok(data.events.some((event) => event.id === "spacex-trading" && event.date === "2026-06-12"));
assert.ok(data.events.some((event) => event.id === "kr-witch-2026-06" && event.date === "2026-06-11"));
assert.ok(data.events.some((event) => event.topic === "OpenAI" && event.confidence === "conditional"));
assert.ok(data.events.some((event) => event.topic === "Anthropic" && event.confidence === "conditional"));
