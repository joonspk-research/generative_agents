// Exercise the actual graph functions without browser or API dependencies.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("environment/frontend_server/templates/dashboard/dashboard.html", "utf8");
const script = html.slice(html.indexOf("const STANCE_COLORS"), html.indexOf("let logTimer"));
const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, {id, clientWidth: 800, innerHTML: "",
    textContent: "", hidden: false, addEventListener() {},
    querySelector: () => ({setAttribute() {}})});
  return elements.get(id);
};
const drawn = {};
const context = vm.createContext({
  data: null, selected: null, drawn, $: element,
  document: {getElementById: () => null},
  esc: (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c])),
  paint: (el, value) => { el.innerHTML = value; drawn[el.id] = value; },
  ResizeObserver: class { observe() {} },
  parseGameTime: () => new Date("2023-02-13T00:00:00"),
  spanLabel: () => "1h", showConvo() {}, selectAgent() {},
});
vm.runInContext(script, context);
const run = (code) => vm.runInContext(code, context);
assert.equal(run('stanceY({score:0,scale:100,scoring_version:"rubric_v1"})'), 272);
assert.equal(run('stanceY({score:100,scale:100,scoring_version:"rubric_v1"})'), 12);
assert.equal(run('stanceY({score:50,scale:100,scoring_version:"rubric_v1"})'), 142);
assert.equal(run('stanceY({score:1,scale:100})'), 272);
assert.equal(run('stanceY({score:10,scale:10})'), 12);
assert.equal(run('stanceY({score:null,scale:100})'), null);
const nodes = ["Maya", "Rachel", "Elena"].map((name) => ({name, color: "#9299A4", score: null}));
context.data = {sim: {persona_order: nodes.map((n) => n.name)}, network: {nodes, edges: []}};
run("renderNetwork()");
assert.equal((element("social-network").innerHTML.match(/<circle /g) || []).length, 3);
assert.equal((element("social-network").innerHTML.match(/#9299A4/g) || []).length, 3);
const originalPositions = run("JSON.stringify(socialPositions(data.network.nodes,800))");
context.data.network.nodes.reverse();
context.data.network.edges = [{source: "Maya", target: "Rachel", count: 301, time: "now"}];
run("renderNetwork()");
assert.equal(run("JSON.stringify(socialPositions(data.network.nodes,800))"), originalPositions);
assert.equal((element("social-network").innerHTML.match(/class="social-edge"/g) || []).length, 1);
assert.match(element("social-network").innerHTML, /301 completed conversations/);
assert(run("socialEdgeWidth(2) > socialEdgeWidth(1)"));
assert(run("socialEdgeWidth(1000000) <= 8"));
context.data.network.nodes[0].name = '<img src=x onerror="alert(1)">';
run("renderNetwork()");
assert(!element("social-network").innerHTML.includes("<img"));
context.data.opinions = [
  {name: "Maya", score: 1, step: 1, scale: 100},
  {name: "Maya", score: 0, step: 2, scale: 100, scoring_version: "rubric_v1"},
  {name: "Maya", score: null, step: 3, scale: 100, scoring_version: "rubric_v1"},
  {name: "Maya", score: 100, step: 4, scale: 100, scoring_version: "rubric_v1"},
];
run("renderStance()");
assert.match(element("stance").innerHTML, /0 opposed/);
assert.match(element("stance-note").textContent, /not directly comparable/);
const path = element("stance").innerHTML.match(/class="line[^"]*"[^>]*d="([^"]+)"/)[1];
assert.equal((path.match(/M/g) || []).length, 3); // Break at method change and null.
assert.equal((path.match(/L/g) || []).length, 0);
console.log("Stance plotting, historical versions, network rendering, layout, escaping: passed");
