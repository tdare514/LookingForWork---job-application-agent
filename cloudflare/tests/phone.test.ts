import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it, vi } from "vitest";
import { SYNTHETIC_APPLICATIONS } from "../src/fixtures.js";
import { APPLICATION_STATUSES, SYNC_FIELDS } from "../src/types.js";

// Minimal DOM surface for exercising the actual page script without a new
// browser dependency. Visual layout is checked separately in a browser.
class Element {
  children: Element[] = [];
  listeners: Record<string, (event: { preventDefault(): void }) => void> = {};
  textContent = "";
  innerHTML = "";
  value = "";
  disabled = false;
  hidden = false;
  options: Element[] = [];
  constructor(readonly tag = "div") {}
  append(...children: Element[]) { this.children.push(...children); }
  replaceChildren(...children: Element[]) { this.children = children; }
  setAttribute() {}
  addEventListener(name: string, handler: Element["listeners"][string]) { this.listeners[name] = handler; }
  fire(name: string) { this.listeners[name]?.({ preventDefault() {} }); }
}

const script = readFileSync("public/app.js", "utf8");
const html = readFileSync("public/index.html", "utf8");
const flush = () => new Promise((resolve) => setImmediate(resolve));

async function page({ source = "d1", cookie = "jobagent_csrf=test-csrf" } = {}) {
  const elements = new Map<string, Element>();
  const get = (selector: string) => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector)!;
  };
  const filter = get("#status-filter");
  filter.value = "all";
  filter.options = [...html.matchAll(/<option value="([^"]+)">([^<]+)<\/option>/g)].map(([, value, label]) => {
    const option = new Element("option");
    option.value = value;
    option.textContent = label;
    return option;
  });
  const fetch = vi.fn().mockResolvedValueOnce(Response.json({ source, applications: SYNTHETIC_APPLICATIONS }))
    .mockResolvedValueOnce(Response.json({ generated_at: "2026-09-27T00:00:00Z", rows: SYNTHETIC_APPLICATIONS.map((row) => ({ ...row, state: row.status })) }));
  runInNewContext(script, {
    document: { cookie, querySelector: get, createElement: (tag: string) => new Element(tag) },
    window: { location: { reload: vi.fn() } }, navigator: {}, fetch, Intl, Date,
  });
  await flush();
  fetch.mockReset();
  const cards = () => get("#applications").children;
  const editor = () => {
    const form = cards()[0].children[0];
    return { form, select: form.children[0].children[0], button: form.children[1] };
  };
  const choose = (status: string) => {
    const { form, select } = editor();
    select.value = status;
    select.fire("change");
    form.fire("submit");
  };
  return { get, fetch, cards, editor, choose, filter };
}

describe("phone status editing", () => {
  it("uses the complete board vocabulary, labels new as Saved, and leaves snapshots read-only", async () => {
    const live = await page();
    expect(live.editor().select.children.map((option) => option.value)).toEqual(APPLICATION_STATUSES);
    expect(live.editor().select.children[0].textContent).toBe("Saved");
    expect(live.editor().button.disabled).toBe(true);
    const snapshot = await page({ source: "synthetic" });
    expect(snapshot.cards().every((card) => card.children.length === 0)).toBe(true);
  });

  it("sends only allowed fields with CSRF and version, then updates filtering, counts and the next write version", async () => {
    const p = await page();
    p.filter.value = "ready";
    p.filter.fire("change");
    p.fetch.mockResolvedValueOnce(Response.json({ ...SYNTHETIC_APPLICATIONS[0], status: "applied", version: 2 }));
    p.choose("applied");
    expect(p.editor().select.disabled).toBe(true);
    expect(p.editor().button.disabled).toBe(true);
    await flush();
    const [url, request] = p.fetch.mock.calls[0];
    expect(url).toBe("/api/jobs/synthetic-001");
    expect(request.method).toBe("PUT");
    expect(request.credentials).toBe("same-origin");
    expect(request.headers).toMatchObject({ "If-Match": "1", "X-CSRF-Token": "test-csrf" });
    expect(Object.keys(JSON.parse(request.body)).sort()).toEqual([...SYNC_FIELDS].sort());
    expect(JSON.parse(request.body)).toMatchObject({ status: "applied", nextAction: SYNTHETIC_APPLICATIONS[0].nextAction });
    expect(p.get("#summary").children[2].innerHTML).toContain("<strong>1</strong>");
    expect(p.cards()[0].textContent).toBe("Nothing at this status.");
    p.filter.value = "applied";
    p.filter.fire("change");
    expect(p.editor().select.value).toBe("applied");
    p.fetch.mockResolvedValueOnce(Response.json({ ...SYNTHETIC_APPLICATIONS[0], status: "new", version: 3 }));
    p.choose("new");
    await flush();
    expect(p.fetch.mock.calls[1][1].headers["If-Match"]).toBe("2");
    expect(p.get("#status-feedback").textContent).toContain("Saved");
  });

  it.each([401, 403, 404, 409, 429, 500])("never claims a save or retries after HTTP %s", async (status) => {
    const p = await page();
    p.fetch.mockResolvedValueOnce(new Response(null, { status }));
    p.choose("applied");
    await flush();
    expect(p.cards()[0].innerHTML).toContain("status-ready");
    expect(p.cards()[0].children).toHaveLength(0);
    expect(p.get("#refresh-board").hidden).toBe(false);
    expect(p.get("#status-feedback").textContent).not.toContain("Saved to the tracker");
    expect(p.fetch).toHaveBeenCalledTimes(1);
  });

  it("requires a reload on ambiguous network failure without changing the displayed status", async () => {
    const p = await page();
    p.fetch.mockRejectedValueOnce(new Error("offline"));
    p.choose("applied");
    await flush();
    expect(p.cards()[0].innerHTML).toContain("status-ready");
    expect(p.get("#status-feedback").textContent).toContain("Could not confirm");
    expect(p.get("#refresh-board").hidden).toBe(false);
  });

  it("refuses to send a write without the CSRF cookie", async () => {
    const p = await page({ cookie: "" });
    p.choose("applied");
    await flush();
    expect(p.fetch).not.toHaveBeenCalled();
    expect(p.get("#status-feedback").textContent).toContain("sign-in needs refreshing");
  });
});
