// Apply the local appearance preference before the stylesheet's first paint.
(() => {
  "use strict";

  const storageKey = "backtest.ui.theme";
  const defaultTheme = "warm";
  const validTheme = (value) => value === "warm" || value === "dark";
  let theme = defaultTheme;
  let persistenceAvailable = true;

  function handleStorageError(error) {
    if (!(error instanceof DOMException)
        || !["SecurityError", "QuotaExceededError"].includes(error.name)) {
      throw error;
    }
    // Privacy settings or a full quota must not prevent an in-tab theme change.
    persistenceAvailable = false;
  }

  try {
    const savedTheme = localStorage.getItem(storageKey);
    if (validTheme(savedTheme)) theme = savedTheme;
  } catch (error) {
    handleStorageError(error);
  }
  document.documentElement.dataset.theme = theme;

  document.addEventListener("DOMContentLoaded", () => {
    const selector = document.querySelector("#theme-select");
    const notice = document.querySelector("#theme-persistence");

    function renderTheme() {
      document.documentElement.dataset.theme = theme;
      selector.value = theme;
      notice.hidden = persistenceAvailable;
    }

    renderTheme();
    selector.addEventListener("change", () => {
      if (!validTheme(selector.value)) return;
      theme = selector.value;
      try {
        localStorage.setItem(storageKey, theme);
        persistenceAvailable = true;
      } catch (error) {
        handleStorageError(error);
      }
      renderTheme();
    });

    // Keep already-open Control and result pages in sync without any API call.
    globalThis.addEventListener("storage", (event) => {
      if (event.key !== storageKey && event.key !== null) return;
      try {
        if (event.storageArea !== localStorage) return;
      } catch (error) {
        handleStorageError(error);
        renderTheme();
        return;
      }
      theme = validTheme(event.newValue) ? event.newValue : defaultTheme;
      renderTheme();
    });
  }, { once: true });
})();
