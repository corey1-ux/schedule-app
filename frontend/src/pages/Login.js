import { useState } from 'react';
import './Login.css';

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error,    setError]    = useState('');
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password) { setError('Username and password are required.'); return; }
    setLoading(true);
    setError('');

    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username: username.trim(), password }),
    }).then(r => r.json()).catch(() => ({ error: 'Network error. Please try again.' }));

    setLoading(false);

    if (res.error) {
      setError(res.error);
    } else {
      onLogin(res);
    }
  };

  return (
    <div className="login-root">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-title">Admin Sign In</h1>
          <p className="login-sub">Enter your credentials to access the admin portal.</p>
        </div>

        <form onSubmit={handleSubmit} className="login-form" noValidate>
          <div className="login-field">
            <label className="login-label" htmlFor="lg-username">Username</label>
            <input
              id="lg-username"
              className="login-input"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={e => { setUsername(e.target.value); setError(''); }}
            />
          </div>

          <div className="login-field">
            <label className="login-label" htmlFor="lg-password">Password</label>
            <input
              id="lg-password"
              className="login-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={e => { setPassword(e.target.value); setError(''); }}
            />
          </div>

          {error && <p className="login-error">{error}</p>}

          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
