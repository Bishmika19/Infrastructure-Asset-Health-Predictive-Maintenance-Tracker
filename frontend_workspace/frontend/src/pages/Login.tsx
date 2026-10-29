import { useState } from 'react';
import { api, describeProblem, type Role, type User } from '../api/client';
import { ErrorNotice } from '../app/AppShell';

interface LoginProps {
  initialError: string | null;
  onAuthenticated: (user: User) => void;
}

// PUBLIC_INTERFACE
export function Login({ initialError, onAuthenticated }: LoginProps) {
  /** Let users explore either demo role without credentials or a backend. */
  const [error, setError] = useState<string | null>(initialError);

  async function chooseRole(role: Role): Promise<void> {
    try {
      onAuthenticated(await api.selectRole(role));
    } catch (selectionError) {
      setError(describeProblem(selectionError));
    }
  }

  return (
    <main className="login-page" aria-labelledby="login-title">
      <section className="login-card">
        <p className="eyebrow">Local demo workspace</p>
        <h1 id="login-title">Explore Asset Health Tracker</h1>
        <p>No account, backend, or database is required. Choose a demo role.</p>
        <p>Edits stay in memory until you reload. Demo Crew ID: <code>demo-crew</code>.</p>
        <ErrorNotice message={error} />
        <button onClick={() => { void chooseRole('asset_manager'); }} type="button">Continue as Asset Manager</button>
        <button className="secondary-button" onClick={() => { void chooseRole('maintenance_crew'); }} type="button">Continue as Maintenance Crew</button>
      </section>
    </main>
  );
}
