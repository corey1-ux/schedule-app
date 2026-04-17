import { useState } from 'react';
import './Login.css';   // reuse login card styles

export default function ChangePassword({ onChanged }) {
  const [currentPw, setCurrentPw] = useState('');
  const [newPw,     setNewPw]     = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [error,     setError]     = useState('');
  const [loading,   setLoading]   = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!currentPw || !newPw || !confirmPw) { setError('All fields are required.'); return; }
    if (newPw !== confirmPw)               { setError('New passwords do not match.'); return; }
    if (newPw.length < 8)                  { setError('New password must be at least 8 characters.'); return; }
    if (newPw === currentPw)               { setError('New password must differ from your current password.'); return; }

    setLoading(true); setError('');
    const res = await fetch('/api/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
    }).then(r => r.json()).catch(() => ({ error: 'Network error. Please try again.' }));

    setLoading(false);
    if (res.error) { setError(res.error); } else { onChanged(); }
  };

  return (
    <div className="login-root">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-title">Set Your Password</h1>
          <p className="login-sub">Your account requires a new password before you can continue.</p>
        </div>

        <form onSubmit={handleSubmit} className="login-form" noValidate>
          <div className="login-field">
            <label className="login-label" htmlFor="cp-current">Temporary Password</label>
            <input id="cp-current" className="login-input" type="password"
              autoComplete="current-password" autoFocus
              value={currentPw} onChange={e => { setCurrentPw(e.target.value); setError(''); }} />
          </div>

          <div className="login-field">
            <label className="login-label" htmlFor="cp-new">New Password</label>
            <input id="cp-new" className="login-input" type="password"
              autoComplete="new-password"
              value={newPw} onChange={e => { setNewPw(e.target.value); setError(''); }} />
          </div>

          <div className="login-field">
            <label className="login-label" htmlFor="cp-confirm">Confirm New Password</label>
            <input id="cp-confirm" className="login-input" type="password"
              autoComplete="new-password"
              value={confirmPw} onChange={e => { setConfirmPw(e.target.value); setError(''); }} />
          </div>

          {error && <p className="login-error">{error}</p>}

          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? 'Saving…' : 'Set Password'}
          </button>
        </form>
      </div>
    </div>
  );
}
