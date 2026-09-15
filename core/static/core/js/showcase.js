(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root.document) api.initShowcase(root.document);
})(typeof window === "undefined" ? globalThis : window, function () {
  "use strict";

  function normalize(value) {
    return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR").trim();
  }

  function matchesProject(project, query, area) {
    const terms = normalize(query).split(/\s+/).filter(Boolean);
    const text = normalize([project.title, project.summary, project.author, project.area].join(" "));
    return (area === "todas" || normalize(project.area) === normalize(area))
      && terms.every((term) => text.includes(term));
  }

  function initShowcase(document) {
    const input = document.getElementById("showcase-search");
    const grid = document.querySelector(".showcase-grid");
    if (!input || !grid) return null;
    const chips = Array.from(document.querySelectorAll(".showcase-chips [data-area]"));
    const clear = document.getElementById("showcase-clear");
    const count = document.getElementById("showcase-count");
    const empty = document.getElementById("showcase-filter-empty");
    const cards = Array.from(grid.querySelectorAll(".project-card")).map((element) => ({
      element,
      title: element.querySelector(".card-title")?.textContent || "",
      summary: element.querySelector(".card-summary")?.textContent || "",
      author: element.querySelector(".card-author")?.textContent || "",
      area: element.dataset.area || "",
    }));
    let area = "todas";

    function filter() {
      let visible = 0;
      cards.forEach((card) => {
        const match = matchesProject(card, input.value, area);
        card.element.hidden = !match;
        if (match) visible += 1;
      });
      chips.forEach((chip) => {
        const selected = chip.dataset.area === area;
        chip.classList.toggle("active", selected);
        chip.setAttribute("aria-pressed", String(selected));
      });
      if (empty) empty.hidden = visible > 0 || cards.length === 0;
      if (clear) clear.hidden = !input.value && area === "todas";
      if (count) count.textContent = `${visible} ${visible === 1 ? "projeto encontrado" : "projetos encontrados"}`;
    }

    input.addEventListener("input", filter);
    chips.forEach((chip) => chip.addEventListener("click", () => { area = chip.dataset.area; filter(); }));
    if (clear) clear.addEventListener("click", () => {
      input.value = "";
      area = "todas";
      filter();
      input.focus();
    });
    filter();
    return { filter };
  }

  return { normalize, matchesProject, initShowcase };
});
