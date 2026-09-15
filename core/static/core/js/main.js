/* Shared navigation, feedback and accessible release notes. */
(() => {
  "use strict";

  const header = document.querySelector(".site-header");
  const toggle = document.getElementById("nav-toggle");
  const nav = document.getElementById("main-nav");
  const mobile = window.matchMedia("(max-width: 980px)");

  if (header && toggle && nav) {
    const closeMenu = (restoreFocus = false) => {
      nav.classList.remove("active");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Abrir menu de navegação");
      if (restoreFocus) toggle.focus();
    };

    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") !== "true";
      nav.classList.toggle("active", expanded);
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-label", expanded ? "Fechar menu de navegação" : "Abrir menu de navegação");
    });
    nav.addEventListener("click", (event) => {
      if (mobile.matches && event.target.closest("a")) closeMenu();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        closeMenu(true);
      }
    });
    document.addEventListener("click", (event) => {
      if (mobile.matches && !header.contains(event.target)) closeMenu();
    });
    header.addEventListener("focusout", (event) => {
      if (mobile.matches && event.relatedTarget && !header.contains(event.relatedTarget)) closeMenu();
    });
    mobile.addEventListener("change", () => closeMenu(mobile.matches && nav.contains(document.activeElement)));
    // Keep every navigation link available if JavaScript cannot load.
    header.classList.add("js-nav");
  }

  const modal = document.getElementById("version-modal");
  let modalTrigger = null;
  if (modal && typeof modal.showModal === "function") {
    document.querySelectorAll("[data-open-version]").forEach((button) => {
      button.addEventListener("click", () => {
        modalTrigger = document.activeElement;
        modal.showModal();
        document.body.classList.add("modal-open");
      });
    });
    document.querySelectorAll("[data-close-version]").forEach((button) => {
      button.addEventListener("click", () => modal.close());
    });
    modal.addEventListener("click", (event) => {
      if (event.target === modal) modal.close();
    });
    modal.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const focusable = [...modal.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")]
        .filter((element) => element.getClientRects().length > 0);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    // Native dialog makes the rest of the page inert, contains keyboard focus
    // and handles Escape. Restore the initiating control on every close path.
    modal.addEventListener("close", () => {
      document.body.classList.remove("modal-open");
      if (modalTrigger && modalTrigger.isConnected) modalTrigger.focus();
    });
  }

  document.addEventListener("click", (event) => {
    const dismiss = event.target.closest("[data-dismiss-alert]");
    if (dismiss) dismiss.closest(".alert")?.remove();
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form instanceof HTMLFormElement && form.dataset.confirm) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    }
  });
})();
