import { createContext, useContext, type ReactNode } from 'react';
import { t } from './i18n';

// The static shell opts in; the operational product keeps its existing behavior.
const StaticPreviewContext = createContext(false);
export function StaticPreviewProvider({ enabled = true, children }: { enabled?: boolean; children: ReactNode }) {
  return <StaticPreviewContext.Provider value={enabled}>{children}</StaticPreviewContext.Provider>;
}
export function useStaticPreview() {
  return useContext(StaticPreviewContext);
}
export function PreviewNotice() {
  return useStaticPreview() ? <p className="notice" role="note">{t('Explore the controls and saved results. New runs, data preparation and analysis are disabled on this published preview.')}</p> : null;
}
