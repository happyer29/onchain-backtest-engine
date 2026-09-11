import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { getLocale, setLocale, t, useLocale } from './i18n';
import { atomic, percent } from './format';

// Each test restores presentation state; no command or financial value is localized in storage.
afterEach(() => { vi.restoreAllMocks(); setLocale('en'); localStorage.clear(); });
it('keeps exact integer digits while formatting each supported language', () => {
  expect(atomic('9007199254740993001', 9, 9)).toBe('9,007,199,254.740993001');
  setLocale('ru');
  expect(atomic('9007199254740993001', 9, 9)).toBe('9\u00a0007\u00a0199\u00a0254,740993001');
  // The ratio retains the same integer rounding policy in either locale.
  expect(percent('1', '3')).toBe('33,33%');
  expect(t('Minimum 12')).toBe('Минимум 12');
  setLocale('en');
  expect(t('Минимум 12')).toBe('Minimum 12');
  // Dictionary lookup must not accidentally resolve inherited object properties.
  expect(t('constructor')).toBe('constructor');
});

// Subscribers update in place, including when browser storage denies persistence.
it('keeps the current tab usable when storage is unavailable', () => {
  function View() { useLocale(); return <p>{t('Overview')}</p>; }
  render(<View />);
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('denied', 'SecurityError'); });
  act(() => { expect(setLocale('ru')).toBe(false); });
  // Both visible text and the document language update despite the denied write.
  expect(screen.getByText('Обзор')).toBeVisible();
  expect(document.documentElement.lang).toBe('ru');
});

// Cross-tab removal or an unknown stored value restores English without consulting navigator.
it('synchronizes a closed locale choice and does not swallow unexpected errors', () => {
  window.dispatchEvent(new StorageEvent('storage', { key: 'backtest.ui.language', newValue: 'ru' }));
  expect(getLocale()).toBe('ru');
  window.dispatchEvent(new StorageEvent('storage', { key: 'backtest.ui.language', newValue: 'fr' }));
  expect(getLocale()).toBe('en');
  // Programming failures remain visible rather than pretending to save a preference.
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('unexpected'); });
  expect(() => setLocale('ru')).toThrow('unexpected');
});
