const assert = require("node:assert/strict");
const test = require("node:test");
const { matchesProject, initShowcase } = require("../../core/static/core/js/showcase.js");

const project = { title: "Energia e automação", summary: "Monitoramento para salas de aula", author: "João Santos", area: "Engenharia" };

test("showcase combines accent-insensitive text terms with an exact area filter", () => {
  assert.equal(matchesProject(project, "AUTOMACAO joao", "Engenharia"), true);
  assert.equal(matchesProject(project, "salas energia", "todas"), true);
  assert.equal(matchesProject(project, "automacao", "Psicologia"), false);
  assert.equal(matchesProject(project, "energia inexistente", "todas"), false);
});

test("showcase searches treat HTML and regular expression syntax as plain text", () => {
  assert.equal(matchesProject(project, "[.*", "todas"), false);
  assert.equal(matchesProject({ ...project, title: "<script>" }, "<script>", "todas"), true);
});

function element() {
  return {
    hidden: false, dataset: {}, value: "", textContent: "", attributes: {}, handlers: {},
    classList: { toggle() {} },
    addEventListener(event, handler) { this.handlers[event] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { this.focused = true; },
  };
}

test("showcase updates results, empty state, accessible selected state and clear action together", () => {
  const input = element();
  const clear = element();
  const count = element();
  const empty = element();
  const card = element();
  card.dataset.area = "Engenharia";
  card.querySelector = (selector) => ({ textContent: selector === ".card-title" ? project.title : project.author });
  const chips = ["todas", "Engenharia", "Psicologia"].map((area) => Object.assign(element(), { dataset: { area } }));
  const nodes = { "showcase-search": input, "showcase-clear": clear, "showcase-count": count, "showcase-filter-empty": empty };
  initShowcase({
    getElementById: (id) => nodes[id],
    querySelector: () => ({ querySelectorAll: () => [card] }),
    querySelectorAll: () => chips,
  });
  assert.equal(count.textContent, "1 projeto encontrado");
  assert.equal(empty.hidden, true);
  chips[2].handlers.click();
  assert.equal(card.hidden, true);
  assert.equal(empty.hidden, false);
  assert.equal(chips[2].attributes["aria-pressed"], "true");
  assert.equal(count.textContent, "0 projetos encontrados");
  clear.handlers.click();
  assert.equal(card.hidden, false);
  assert.equal(clear.hidden, true);
  assert.equal(input.focused, true);
});
