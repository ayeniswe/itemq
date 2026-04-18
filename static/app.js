(() => {
  const APP_KEY = "sidebarCollapsed";
  const LAST_ROUTE_KEY = "itemq:last-content-route";
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

  const content = document.getElementById("content");
  if (content && window.location.pathname === "/") {
    const savedRoute = localStorage.getItem(LAST_ROUTE_KEY);
    if (savedRoute && savedRoute.startsWith("/")) {
      content.setAttribute("hx-get", savedRoute);
    }
  }

  document.body.addEventListener("htmx:beforeRequest", (event) => {
    const detail = event.detail;
    const target = detail?.target;
    const path = detail?.pathInfo?.requestPath;
    if (!(target instanceof HTMLElement) || target.id !== "content" || !path) {
      return;
    }
    localStorage.setItem(LAST_ROUTE_KEY, path);
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

window.clearAllInventoryImages = async function clearAllInventoryImages(button) {
  const filters = document.getElementById("inventory-filters");
  if (!filters || !window.htmx) return;

  const firstConfirm = window.confirm(
    "This will remove every local inventory image from the app and move the files into the trash. Continue?"
  );
  if (!firstConfirm) return;

  if (button instanceof HTMLButtonElement) {
    button.disabled = true;
  }

  const values = Object.fromEntries(new FormData(filters).entries());
  const cleanup = () => {
    document.body.removeEventListener("htmx:afterSwap", reenable);
    document.body.removeEventListener("htmx:responseError", fail);
  };
  const reenable = (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.id === "inventory-table-wrapper") {
      if (button instanceof HTMLButtonElement) {
        button.disabled = false;
      }
      cleanup();
    }
  };
  const fail = () => {
    if (button instanceof HTMLButtonElement) {
      button.disabled = false;
    }
    cleanup();
  };
  document.body.addEventListener("htmx:afterSwap", reenable);
  document.body.addEventListener("htmx:responseError", fail);

  window.htmx.ajax("POST", "/inventory/images/clear_all", {
    target: "#inventory-table-wrapper",
    swap: "innerHTML",
    values,
  });
};

window.purgeInventoryImageTrash = async function purgeInventoryImageTrash(button) {
  const filters = document.getElementById("inventory-filters");
  if (!filters || !window.htmx) return;

  const firstConfirm = window.confirm(
    "This will permanently delete every file in the inventory image trash. This cannot be undone. Continue?"
  );
  if (!firstConfirm) return;

  const typed = window.prompt('Type "purge image trash" to permanently delete those files.');
  if (typed !== "purge image trash") return;

  if (button instanceof HTMLButtonElement) {
    button.disabled = true;
  }

  const values = Object.fromEntries(new FormData(filters).entries());
  const cleanup = () => {
    document.body.removeEventListener("htmx:afterSwap", reenable);
    document.body.removeEventListener("htmx:responseError", fail);
  };
  const reenable = (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.id === "inventory-table-wrapper") {
      if (button instanceof HTMLButtonElement) {
        button.disabled = false;
      }
      cleanup();
    }
  };
  const fail = () => {
    if (button instanceof HTMLButtonElement) {
      button.disabled = false;
    }
    cleanup();
  };
  document.body.addEventListener("htmx:afterSwap", reenable);
  document.body.addEventListener("htmx:responseError", fail);

  window.htmx.ajax("POST", "/inventory/images/purge_trash", {
    target: "#inventory-table-wrapper",
    swap: "innerHTML",
    values,
  });
};
