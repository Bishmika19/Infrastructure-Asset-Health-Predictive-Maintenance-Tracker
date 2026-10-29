import { FormEvent, useState } from 'react';
import { api, describeProblem, type User } from '../api/client';
import { ErrorNotice } from '../app/AppShell';

interface LoginProps {
  initialError: string | null;
  onAuthenticated: (user: User) => void;
}

export function Login({ initialError, onAuthenticated }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(initialError);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onAuthenticated(await api.login(username, password));
    } catch (requestError) {
      setError(describeProblem(requestError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page" aria-labelledby="login-title">
      <section className="login-card">
        <p className="eyebrow">Infrastructure operations</p>
        <h1 id="login-title">Sign in to Asset Health Tracker</h1>
        <p>Use your assigned Asset Manager or Maintenance Crew credentials.</p>
        <ErrorNotice message={error} />
        <form onSubmit={submit}>
          <label htmlFor="username">Username</label>
          <input
            autoComplete="username"
            id="username"
            maxLength={128}
            onChange={(event) => setUsername(event.target.value)}
            required
            value={username}
          />
          <label htmlFor="password">Password</label>
          <input
            autoComplete="current-password"
            id="password"
            maxLength={256}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          <button disabled={submitting} type="submit">{submitting ? 'Signing in…' : 'Sign in'}</button>
        </form>
      </section>
    </main>
  );
}
