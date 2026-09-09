import { t, type Locale } from '../lib/i18n';
import { checkedTime } from '../lib/readouts';
import type { Snapshot } from '../lib/state';

export default function Footer({ state, busy, status, locale, settings, onSettings, onQuit, onDismiss }: {
  state: Snapshot; busy: boolean; status: { text: string; error: boolean; id: number } | null;
  locale: Locale; settings: boolean; onSettings: () => void; onQuit: () => void; onDismiss: () => void;
}) {
  return <footer>
    <div className="footer-readout">
      {status ? <span key={status.id} className={`footer-status ${status.error ? 'error-status' : ''}`} role={status.error ? 'alert' : 'status'}>
        <button title={status.text} aria-label={`${status.text} · ${t(locale, 'dismiss')}`} onClick={onDismiss}>{status.text}</button>
      </span> : <span role="status">{busy ? t(locale, 'applying') : state.fetched_at ? t(locale, 'checked', { time: checkedTime(state.fetched_at, locale) }) : t(locale, 'unavailable')}</span>}
    </div>
    <div className="footer-actions"><button aria-controls="panel-body" aria-expanded={settings} onClick={onSettings}>{t(locale, settings ? 'back' : 'settings')}</button>
      <span aria-hidden="true">·</span><button onClick={onQuit}>{t(locale, 'quit')}</button></div>
  </footer>;
}
