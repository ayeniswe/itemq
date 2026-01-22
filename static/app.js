const initializePage = () => {
  const overlayToggle = document.getElementById("inventory-add-toggle");
  const overlay = document.getElementById("inventory-add-overlay");
  const overlayCard = document.getElementById("inventory-add-card");

  if (overlayToggle && overlay && overlayCard) {
    overlayToggle.addEventListener("click", () => {
      overlay.classList.remove("is-hidden");
    });

    overlay.addEventListener("click", (event) => {
      if (!overlayCard.contains(event.target)) {
        overlay.classList.add("is-hidden");
      }
    });

    overlayCard.addEventListener("submit", () => {
      overlay.classList.add("is-hidden");
    });
  }

  const includeToggle = document.getElementById("include-notion-toggle");
  const inventoryTable = document.getElementById("inventory-table");
  const STORAGE_KEY = "inventoryIncludeNotion";

  if (includeToggle && inventoryTable && window.htmx) {
    const applySavedPref = () => {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        includeToggle.checked = saved === "true";
      }
    };

    const fetchTable = () => {
      const values = {};
      if (includeToggle.checked) {
        values.include_notion = "true";
      }

      htmx.ajax("GET", "/inventory/table", {
        target: "#inventory-table",
        swap: "innerHTML",
        values,
      });
    };

    applySavedPref();
    fetchTable();

    includeToggle.addEventListener("change", () => {
      localStorage.setItem(STORAGE_KEY, String(includeToggle.checked));
      fetchTable();
    });
  }

  const notionForm = document.querySelector("[data-plugin-form='notion']");
  const notionStatus = document.getElementById("plugin-status");

  if (notionForm && notionStatus && window.htmx) {
    const setStatus = (message, state) => {
      const target = document.getElementById("plugin-status");
      if (!target) {
        return;
      }

      const stateClass = state === "disconnect"
        ? "plugin-status plugin-status--disconnect"
        : "plugin-status plugin-status--loading";

      const spinner = state === "disconnect"
        ? ""
        : '<span class="plugin-spinner" aria-hidden="true"></span>';

      target.innerHTML = `${spinner}${message}`;
      target.className = stateClass;
      if (state) {
        target.dataset.pluginState = state;
      }
    };

    notionForm.addEventListener("htmx:afterSwap", (event) => {
      const statusTarget = event.detail.target;
      if (!statusTarget || statusTarget.id !== "plugin-status") {
        return;
      }

      const state = statusTarget.dataset.pluginState;
      if (state === "pulling") {
        window.setTimeout(() => {
          setStatus("Disconnect", "disconnect");
        }, 1200);
      }
    });
  }
};

document.addEventListener("DOMContentLoaded", initializePage);
document.addEventListener("htmx:load", initializePage);
