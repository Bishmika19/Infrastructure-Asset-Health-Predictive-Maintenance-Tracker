import type { PropsWithChildren } from 'react';
import type { User } from '../api/client';

export type View = 'assets' | 'asset-detail' | 'inspection' | 'queue' | 'cases' | 'history';

interface AppShellProps extends PropsWithChildren {
  user: User;
  view: View;
  onNavigate: (view: View) => void;
  onSignOut: () => void;
}

const navigation: Array<{ view: Extract<View, 'assets' | 'queue' | 'cases'>; label: string }> = [
  { view: 'assets', label: 'Asset register' },
  { view: 'queue', label: 'Maintenance queue' },
  { view: 'cases', label: 'Cases' },
];

export function AppShell({ children, onNavigate, onSignOut, user, view }: AppShellProps) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="site-header">
        <div>
          <p className="eyebrow">Operations workspace</p>
          <h1>Asset Health Tracker</h1>
        </div>
        <div className="user-panel">
          <span>{user.username}</span>
          <span className="role-label">{user.role === 'asset_manager' ? 'Asset Manager' : 'Maintenance Crew'}</span>
          <button className="secondary-button" type="button" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      <nav aria-label="Primary navigation" className="primary-nav">
        {navigation.map((item) => (
          <button
            aria-current={view === item.view ? 'page' : undefined}
            className={view === item.view ? 'nav-link active' : 'nav-link'}
            key={item.view}
            onClick={() => onNavigate(item.view)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}

export function ErrorNotice({ message }: { message: string | null }) {
  return message ? <p className="notice error-notice" role="alert">{message}</p> : null;
}

export function StatusNotice({ message }: { message: string | null }) {
  return message ? <p className="notice success-notice" role="status">{message}</p> : null;
}
