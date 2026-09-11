import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ChevronDown, Moon, Settings, Sun } from 'lucide-react';
import { t, useLocale, setLocale } from './i18n';

function ThemeControl() {
  useLocale();
  const [theme, setTheme] = useState(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'warm');
  const [persistent, setPersistent] = useState(true);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  // Synchronization is independent of storage writes, preventing a cross-tab feedback loop.
  useEffect(() => { const sync = (event: StorageEvent) => { if (event.key === 'backtest.ui.theme' || event.key === null) setTheme(event.newValue === 'dark' ? 'dark' : 'warm'); }; window.addEventListener('storage', sync); return () => window.removeEventListener('storage', sync); }, []);
  function change(value: string) {
    setTheme(value);
    try { localStorage.setItem('backtest.ui.theme', value); setPersistent(true); }
    catch (error) { if (!(error instanceof DOMException) || !['SecurityError', 'QuotaExceededError'].includes(error.name)) throw error; setPersistent(false); }
  }
  // Storage restrictions affect persistence only; the selected in-tab theme still works.
  return <div className="theme-control"><label htmlFor="theme-select">{theme === 'dark' ? <Moon size={17} /> : <Sun size={17} />} {t("Appearance")}</label><select id="theme-select" value={theme} onChange={event => change(event.target.value)}><option value="warm">Warm sunset</option><option value="dark">Dark</option></select>{!persistent && <small role="status">{t("The theme applies to this tab; storage is unavailable.")}</small>}</div>;
}

// Locale changes preserve the mounted route, form values and the selected result page.
function LanguageControl() {
  const locale = useLocale();
  const [persistent, setPersistent] = useState(true);
  return <div className="theme-control"><label htmlFor="language-select">{t('Language')}</label><select id="language-select" value={locale} onChange={event => setPersistent(setLocale(event.target.value === 'ru' ? 'ru' : 'en'))}><option value="en">English</option><option value="ru">Русский</option></select>{!persistent && <small role="status">{t('The language applies to this tab; storage is unavailable.')}</small>}</div>;
}

// Preferences stay mounted while hidden so theme and locale synchronization keep working.
export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  useEffect(() => { setOpen(false); }, [location.pathname]);
  // Outside clicks dismiss the panel; Escape returns keyboard focus to its disclosure button.
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); setOpen(false); trigger.current?.focus(); } };
    // Listeners exist only while open and never intercept preference values or navigation.
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  // This is a group of ordinary labelled form controls, not an ARIA menu of commands.
  return <div className="settings-menu" ref={root}>
    <button className="button settings-toggle" type="button" ref={trigger} aria-expanded={open} aria-controls="workspace-settings-panel" onClick={() => setOpen(!open)}><Settings size={17} /><span>{t('Settings')}</span><ChevronDown className="settings-chevron" size={15} /></button>
    <div className="settings-panel" id="workspace-settings-panel" role="group" aria-label={t('Settings')} hidden={!open}><ThemeControl /><LanguageControl /></div>
  </div>;
}
