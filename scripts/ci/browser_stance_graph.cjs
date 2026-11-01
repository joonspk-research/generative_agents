// Optional browser smoke test: NODE_PATH=<Playwright modules> node this-file <dashboard URL>.
// Uses fixture HTTP responses; never launches a simulation or calls an LLM.
const {chromium} = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");

async function main() {
  const url = process.argv[2] || "http://127.0.0.1:8012/dashboard";
  const origin = new URL(url).origin;
  const names = ["Maya Okonkwo", "Luis Hernandez", "Denise Brooks", "Rachel Nguyen",
    "Tom Whitaker", "Aisha Rahman", "Marcus Williams", "Elena Chen"];
  const bands = [
    ["very_strong_opposition", 0, 19, "Very strong opposition", "#A32834"],
    ["moderate_opposition", 20, 39, "Moderate opposition", "#DD645D"],
    ["slight_opposition", 40, 49, "Slight opposition", "#EFAA86"],
    ["neutral_mixed", 50, 50, "Neutral / genuinely mixed", "#D5B55C"],
    ["slight_support", 51, 60, "Slight support", "#A0CAA0"],
    ["moderate_support", 61, 80, "Moderate support", "#48A276"],
    ["very_strong_support", 81, 100, "Very strong support", "#17754E"],
  ].map(([category, min, max, label, color]) => ({category, min, max, label, color}));
  let stage = 0;
  const time = "February 13, 2023, 12:00:00";
  const agent = (name) => ({name, first_name: name.split(" ")[0],
    act_description: "Reviewing the proposal", schedule: [["Review proposal", 1440]],
    schedule_idx: 0, memory_counts: {}, events: [], thoughts: [], chats: [], reflections: [],
    reflect_trigger: [20, 150], daily_req: [], llm: []});
  function response(selected, saved = false) {
    const nodes = names.map((name, i) => ({name,
      ...(stage && bands[i] ? {score: bands[i].min, scale: 100,
        category: bands[i].category, label: bands[i].label, color: bands[i].color,
        time, scoring_version: "rubric_v1"} : {score: null, label: "Unrated", color: "#9299A4"}),
      conversations: stage && i < 2 ? stage === 1 ? 1 : 350 : 0,
      partners: stage && i < 2 ? 1 : 0,
    }));
    const step = stage ? 720 : 0;
    return {status: "idle", run_env: "staging", settings: {opinion_steps: 360},
      sims: [{name: "fixture-saved", step: 720, maze: "the_ville_datacenter"}], results: [],
      sim: {sim_code: saved ? "fixture-saved" : "fixture-live", pid: 123, step,
        sec_per_step: 10, curr_time: time, persona_order: names, roster: names.map(agent),
        agent: agent(selected || names[0]), start_step: 0, run_env: "staging"},
      conversations: [], events: [],
      opinions: stage ? [0, 100, null].map((score, i) => ({name: names[0], score,
        category: score === 0 ? bands[0].category : bands[6].category,
        scale: 100, scoring_version: "rubric_v1", step: 360 * i, time,
        rationale: "Fixture evidence", conditions: []})) : [],
      network: {nodes, bands, conversations: stage ? stage === 1 ? 1 : 350 : 0,
        edges: stage ? [{source: names[0], target: names[1],
          count: stage === 1 ? 1 : 350, time}] : []},
    };
  }
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", async (route) => {
      const request = new URL(route.request().url());
      if (request.origin !== origin) return route.abort();
      const path = request.pathname;
      if (path.startsWith("/dashboard/state/")) return route.fulfill({json: response(request.searchParams.get("agent"))});
      if (path.startsWith("/dashboard/run/")) return route.fulfill({json: response(request.searchParams.get("agent"), true)});
      if (path.startsWith("/dashboard/usage/")) return route.fulfill({json: {since: null}});
      if (path.startsWith("/simulator_home")) return route.fulfill({body: "<html><body>Map fixture</body></html>", contentType: "text/html"});
      return route.continue();
    });
    await page.goto(url);
    await page.waitForFunction(() => document.querySelectorAll(".social-node").length === 8);
    assert.equal(await page.locator('.social-node circle[fill="#9299A4"]').count(), 8);
    assert.equal(await page.locator(".social-edge").count(), 0);
    const positions = () => page.locator(".social-node").evaluateAll((nodes) => nodes.map((n) => {
      const c = n.querySelector("circle"); return [n.dataset.networkNode, c.getAttribute("cx"), c.getAttribute("cy")];
    }));
    const before = await positions();
    stage = 1;
    await page.waitForFunction(() => document.querySelectorAll(".social-edge").length === 1);
    assert.deepEqual(await positions(), before);
    const width = Number(await page.locator(".social-edge").getAttribute("stroke-width"));
    stage = 2;
    await page.waitForFunction(() => document.querySelector("#social-note").textContent.includes("350 completed"));
    assert(Number(await page.locator(".social-edge").getAttribute("stroke-width")) > width);
    assert.equal(await page.locator(".social-edge").count(), 1);
    assert.match(await page.locator(".social-edge title").textContent(), /350 completed/);
    assert.match(await page.locator("#stance svg").getAttribute("aria-label"), /0 opposed/);
    assert.equal(await page.locator("#stance circle.dot").count(), 2);
    assert.match(await page.locator('.social-node[data-network-node="Maya Okonkwo"] title').textContent(), /Last valid probe/);
    await page.locator('.social-node[data-network-node="Rachel Nguyen"]').click();
    await page.waitForFunction(() => document.querySelector("#who").textContent.includes("Rachel Nguyen"));
    const shotDir = process.env.SCREENSHOT_DIR || "/private/tmp/stance-graph-v2-ui";
    fs.mkdirSync(shotDir, {recursive: true});
    for (const [label, width] of [["desktop", 1440], ["mobile", 390]]) {
      await page.setViewportSize({width, height: 1000});
      for (const theme of ["light", "dark"]) {
        await page.evaluate((t) => document.documentElement.dataset.theme = t, theme);
        await page.locator("#social-card").scrollIntoViewIfNeeded();
        await page.waitForFunction(() => document.querySelector("#social-network svg") != null);
        await page.locator(".bottom").screenshot({path: `${shotDir}/${label}-${theme}.png`});
        const bounds = await page.locator("#social-card").boundingBox();
        assert(bounds.width <= width);
        assert.equal(await page.locator("#social-legend span").count(), 8);
        const labelsFit = await page.locator(".social-node text").evaluateAll((texts) =>
          texts.every((t) => {const box = t.getBBox(); const svg = t.ownerSVGElement;
            return box.x >= 0 && box.x + box.width <= svg.viewBox.baseVal.width;
          }));
        assert(labelsFit, "Network names should fit inside the SVG");
      }
    }
    await page.selectOption("#run-select", "fixture-saved");
    await page.waitForFunction(() => document.querySelector("#status").textContent.includes("read-only"));
    assert.equal(await page.locator(".social-node").count(), 8);
    await page.reload();
    await page.waitForFunction(() => document.querySelector("#social-note").textContent.includes("350 completed"));
    assert.equal(await page.locator(".social-edge").count(), 1);
    assert.deepEqual(errors, []);
    console.log(`Browser smoke passed: startup, live polling, selection, saved view, reload, desktop/mobile, light/dark. Screenshots: ${shotDir}`);
  } finally {
    await browser.close();
  }
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
