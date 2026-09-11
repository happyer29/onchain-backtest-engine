import { useSyncExternalStore } from 'react';
import messages from './messages.ru.json';

// Language is local presentation state; it never enters a command, identity or query key.
export type Locale = 'en' | 'ru';
const key = 'backtest.ui.language';
let locale: Locale = document.documentElement.lang === 'ru' ? 'ru' : 'en';
let persistent = true;
const listeners = new Set<() => void>();

// Literal lookup also handles an error retained while the user switches language.
const russian = new Map(Object.entries(messages));
const english = new Map(Object.entries(messages).map(([en, ru]) => [ru, en]));
const escapePattern = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const patterns = Object.entries(messages).filter(([message]) => message.includes('{0}')).flatMap(([en, ru]) => [en, ru].map(message => ({ en, pattern: new RegExp('^' + message.split(/\{\d+\}/).map(escapePattern).join('(.*?)') + '$') })));

// The HTML bootstrap handles first paint; subscribers preserve mounted form and dialog state.
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export const getLocale = () => locale;
export const localeTag = () => locale === 'ru' ? 'ru-RU' : 'en-US';
export const decimalSeparator = () => locale === 'ru' ? ',' : '.';
export function useLocale() { return useSyncExternalStore(subscribe, getLocale); }

// Only explicit Russian opts out of English, including invalid or removed stored preferences.
function apply(value: string | null) {
  locale = value === 'ru' ? 'ru' : 'en';
  document.documentElement.lang = locale;
  for (const listener of listeners) listener();
}
// Cross-tab notifications do not write storage, avoiding a feedback loop.
window.addEventListener('storage', event => {
  if (event.key === key || event.key === null) apply(event.newValue);
});

// A denied write affects persistence only. Unexpected programming errors are not swallowed.
export function setLocale(value: Locale) {
  try { localStorage.setItem(key, value); persistent = true; }
  catch (error) {
    // Browser privacy/quota failures leave a usable in-tab choice.
    if (!(error instanceof DOMException) || !['SecurityError', 'QuotaExceededError'].includes(error.name)) throw error;
    persistent = false;
  }
  // Notify mounted consumers after persistence is resolved, including the denied-write case.
  apply(value);
  return persistent;
}

// Messages are plain text with positional substitutions; no HTML or executable templates.
export function t(message: string, values: readonly unknown[] = []): string {
  const canonical = english.get(message) ?? message;
  if (!values.length && !russian.has(canonical)) {
    // Only known bounded message templates are matched, never arbitrary executable patterns.
    for (const { en, pattern } of patterns) { const match = pattern.exec(message); if (match) return t(en, match.slice(1)); }
  }
  const template = locale === 'ru' ? russian.get(canonical) ?? canonical : canonical;
  return template.replace(/\{(\d+)\}/g, (match, index: string) => Number(index) < values.length ? String(values[Number(index)]) : match);
}
