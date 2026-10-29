import { FormEvent, useState } from 'react';
import { api, describeProblem, type User } from '../api/client';

interface LoginProps {
  initialError: string | null;
  onAuthenticated: (user: User) => void;
}

const highlights = [
  'Live health scores for every registered asset',
  'Predictive queue of Amber and Red assets',
  'Inspections, Cases and full asset history',
];

// PUBLIC_INTERFACE
export function Login({ initialError, onAuthenticated }: LoginProps) {
  /** Sign-in screen: validates the username and password, then opens the workspace for that user's role. */
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(initialError);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onAuthenticated(await api.login(username, password));
    } catch (loginError) {
      setError(describeProblem(loginError));
      setPassword('');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <div className="login-layout">
        <section aria-label="About Asset Health Tracker" className="login-brand">
          <div className="brand-mark" aria-hidden="true">
            <svg fill="none" height="28" viewBox="0 0 24 24" width="28">
              <path d="M3 12h4l2-6 4 12 2-6h6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" />
            </svg>
          </div>
          <p className="login-kicker">Infrastructure operations</p>
          <p className="login-brand-title">Asset Health &amp; Predictive Maintenance</p>
          <p className="login-brand-copy">Spot failing transformers, pumps and pipelines early, and keep every maintenance Case moving.</p>
          <ul className="login-highlights">
            {highlights.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>

        <section aria-labelledby="login-title" className="login-panel">
          <h1 id="login-title">Sign in</h1>
          <p className="login-subtitle">Welcome back. Enter your account details to continue.</p>
          {error && <p className="notice error-notice" id="login-error" role="alert">{error}</p>}
          <form className="login-form" noValidate onSubmit={submit}>
            <label htmlFor="login-username">Username</label>
            <input
              aria-describedby={error ? 'login-error' : undefined}
              aria-invalid={error ? true : undefined}
              autoCapitalize="none"
              autoComplete="username"
              autoFocus
              id="login-username"
              onChange={(event) => setUsername(event.target.value)}
              placeholder="e.g. asset manager"
              required
              value={username}
            />
            <label htmlFor="login-password">Password</label>
            <div className="password-field">
              <input
                aria-describedby={error ? 'login-error' : undefined}
                aria-invalid={error ? true : undefined}
                autoComplete="current-password"
                id="login-password"
                onChange={(event) => setPassword(event.target.value)}
                required
                type={showPassword ? 'text' : 'password'}
                value={password}
              />
              <button
                aria-controls="login-password"
                aria-pressed={showPassword}
                className="password-toggle"
                onClick={() => setShowPassword((visible) => !visible)}
                type="button"
              >
                {showPassword ? 'Hide' : 'Show'}
                <span className="sr-only"> password</span>
              </button>
            </div>
            <button className="login-submit" disabled={submitting} type="submit">
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
