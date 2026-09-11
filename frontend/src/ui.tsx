import { t, useLocale } from './i18n';
import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Slot } from '@radix-ui/react-slot';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { AlertCircle, ArrowLeft, ArrowRight, X } from 'lucide-react';
import { clsx } from 'clsx';

// Local shadcn-style primitives keep appearance under version control and use the existing CSP.
export function Button({ asChild, tone = 'default', className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean; tone?: 'default' | 'primary' | 'danger' | 'ghost' }) {
  useLocale();
  const Component = asChild ? Slot : 'button';
  return <Component className={clsx('button', `button-${tone}`, className)} {...props} />;
}

// Shared surfaces inherit warm/dark tokens without embedding per-screen style logic.
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  useLocale();
  return <section className={clsx('card', className)}>{children}</section>;
}
// Status emphasis uses a closed CSS vocabulary instead of data-derived markup.
export function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  useLocale();
  return <span className={clsx('badge', tone)}>{children}</span>;
}

// One page heading keeps navigation hierarchy consistent across all workflows.
export function PageTitle({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  useLocale();
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>{children}</div>;
}
// Empty datasets have an explicit state independent of request failure or missing valuation.
export function Empty({ title, detail }: { title: string; detail?: string }) {
  useLocale();
  return <div className="empty"><strong>{title}</strong>{detail && <p>{detail}</p>}</div>;
}
// Errors are announced accessibly and can retry only the associated read or intended operation.
export function Failure({ message, retry }: { message: string; retry?: () => void }) {
  useLocale();
  return <div className="failure" role="alert"><AlertCircle size={18} /><span>{t(message)}</span>{retry && <Button onClick={retry}>{t("Retry")}</Button>}</div>;
}
// Loading remains announced without replacing a missing result with fabricated data.
export function Loading() {
  useLocale(); return <div className="skeleton" role="status" aria-label={t("Loading data")}><span>{t("Loading…")}</span></div>; }

// The same controlled tab set is reused across strategy families.
export function Tabs({ value, onChange, tabs, children }: { value: string; onChange: (value: string) => void; tabs: [string, string][]; children: ReactNode }) {
  useLocale();
  // Radix supplies keyboard tab navigation without injected style elements.
  return <TabsPrimitive.Root value={value} onValueChange={onChange}><TabsPrimitive.List className="tabs" aria-label={t("Result sections")}>
    {tabs.map(([key, text]) => <TabsPrimitive.Trigger key={key} value={key} className="tab">{t(text)}</TabsPrimitive.Trigger>)}
  </TabsPrimitive.List>{children}</TabsPrimitive.Root>;
}
export const TabPanel = TabsPrimitive.Content;

// Arrow navigation requests one server page; disabled controls cannot skip an in-flight cursor.
export function Pager({ index, previous, next, busy, count }: { index: number; previous?: () => void; next?: () => void; busy: boolean; count: number }) {
  useLocale();
  return <div className="pager"><span>{t("Page")} {index + 1} · {count} {t("records")}</span><div>
    <Button aria-label={t("Previous page")} disabled={!previous || busy} onClick={previous}><ArrowLeft size={16} /></Button>
    <Button aria-label={t("Next page")} disabled={!next || busy} onClick={next}><ArrowRight size={16} /></Button>
  </div></div>;
}

// Every detail overlay owns a native modal lifecycle and preserves the underlying page.
export function Overlay({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useLocale();
  const dialog = useRef<HTMLDialogElement>(null);
  // Native modal dialog provides inert background and focus restoration without style injection.
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  // Escape and the close control follow the same cleanup callback, including request cancellation.
  return <dialog ref={dialog} className="overlay" onCancel={event => { event.preventDefault(); onClose(); }}>
    <header><div><p className="eyebrow">{t("Strategy results")}</p><h2>{title}</h2></div><Button aria-label={t("Close details")} onClick={onClose}><X size={20} /></Button></header>
    <div className="overlay-body">{children}</div>
  </dialog>;
}
