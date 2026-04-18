(() => {
  const APP_KEY = "sidebarCollapsed";
  const app = document.querySelector(".app") || document.body;
  if (!app) return;

  const applyState = (collapsed) => {
    app.classList.toggle("sidebar-collapsed", collapsed);
    document.querySelectorAll("[data-sidebar-toggle]").forEach((btn) => {
      btn.setAttribute(
        "aria-label",
        collapsed ? "Expand sidebar" : "Collapse sidebar"
      );
      btn.setAttribute("aria-pressed", String(collapsed));
    });
  };

  const saved = localStorage.getItem(APP_KEY);
  const initial = saved === "true";
  applyState(initial);

  const handleToggle = () => {
    const next = !app.classList.contains("sidebar-collapsed");
    applyState(next);
    localStorage.setItem(APP_KEY, String(next));
  };

  document.addEventListener("click", (event) => {
    const target = event.target instanceof HTMLElement
      ? event.target.closest("[data-sidebar-toggle]")
      : null;
    if (!target) return;
    event.preventDefault();
    handleToggle();
  });
})();

window.cancelInventoryNotionSync = async function cancelInventoryNotionSync(button) {
  const container = document.getElementById("inventory-notion-sync-status");
  if (!container) return;

  if (button instanceof HTMLButtonElement) {
    button.disabled = true;
  }

  try {
    const response = await fetch("/inventory/sync_to_notion/cancel", {
      method: "POST",
      headers: {
        "HX-Request": "true",
      },
      credentials: "same-origin",
    });

    if (!response.ok) {
      throw new Error("Cancel request failed");
    }

    container.outerHTML = await response.text();
  } catch (_) {
    if (button instanceof HTMLButtonElement) {
      button.disabled = false;
    }
  }
};
