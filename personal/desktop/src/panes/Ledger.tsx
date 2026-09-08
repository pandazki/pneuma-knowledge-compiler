import type { ReactNode, SelectHTMLAttributes } from 'react';

export function Leader() { return <span className="leader" aria-hidden="true" />; }

export function LedgerSelect(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <span className="select-value"><select {...props} /></span>;
}

export function SettingRow({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return <div className="setting-row">
    <label id={`${id}-label`} className="small-caps" htmlFor={id}>{label}</label><Leader /><div className="setting-control">{children}</div>
  </div>;
}
