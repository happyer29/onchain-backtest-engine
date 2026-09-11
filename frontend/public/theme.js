// Prepaint only: React owns the visible theme control and cross-tab synchronization for appearance and language.
(() => {
  try {
    const saved = localStorage.getItem('backtest.ui.theme');
    document.documentElement.dataset.theme = saved === 'dark' ? 'dark' : 'warm';
    // English is the default regardless of the browser or operating-system language.
    document.documentElement.lang = localStorage.getItem('backtest.ui.language') === 'ru' ? 'ru' : 'en';
  } catch (error) {
    // Privacy settings affect persistence only, never initial UI availability.
    if (!(error instanceof DOMException) || !['SecurityError', 'QuotaExceededError'].includes(error.name)) throw error;
    document.documentElement.dataset.theme = 'warm';
    document.documentElement.lang = 'en';
  }
})();
