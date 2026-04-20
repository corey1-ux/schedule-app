import { useState, useEffect, useCallback } from 'react';
import { HashRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import Blocks from './pages/Blocks';
import BlockGrid from './pages/BlockGrid';
import Admin from './pages/Admin';
import ImportSchedule from './pages/ImportSchedule';
import Login from './pages/Login';
import ChangePassword from './pages/ChangePassword';
import './App.css';

function CalendarPage() {
  const [publishedId, setPublishedId] = useState(null);
  const [loading, setLoading]         = useState(true);

  useEffect(() => {
    fetch('/api/blocks', { credentials: 'include' })
      .then(r => r.json())
      .then(blocksData => {
        const published = blocksData
          .filter(b => b.status === 'published')
          .sort((a, b) => b.start_date.localeCompare(a.start_date));
        setPublishedId(published.length > 0 ? published[0].id : null);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="status">Loading...</div>;

  if (!publishedId) {
    return <div className="status">No published schedule yet.</div>;
  }

  return <BlockGrid blockId={publishedId} readOnly={true} />;
}

// Redirect staff away from routes they can't access
function RoleRoute({ user, allowedRoles, children }) {
  if (!allowedRoles.includes(user.role)) return <Navigate to="/" replace />;
  return children;
}

function Nav({ user, onLogout }) {
  const isScheduler = user.role === 'scheduler' || user.role === 'admin';
  const isAdmin     = user.role === 'admin';

  return (
    <nav className="app-nav">
      <span className="app-brand">IR Schedule</span>
      <Link to="/">Calendar</Link>
      {isScheduler && <Link to="/blocks">Blocks</Link>}
      {isScheduler && <Link to="/import">Import</Link>}
      {isAdmin     && <Link to="/admin">Admin</Link>}
      <span className="app-nav-user">{user.username}</span>
      <button className="app-nav-logout" onClick={onLogout}>Sign Out</button>
    </nav>
  );
}

export default function App() {
  const [user,        setUser]        = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  const checkAuth = useCallback(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        setUser(data.authenticated ? data : null);
        setAuthChecked(true);
      })
      .catch(() => { setUser(null); setAuthChecked(true); });
  }, []);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  const handleLogin  = (userData) => setUser(userData);
  const handleLogout = () => {
    fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
      .finally(() => setUser(null));
  };
  const handlePasswordChanged = () =>
    setUser(prev => ({ ...prev, force_password_change: false }));

  if (!authChecked) return null;

  // Not logged in — show login for every route
  if (!user) return <Login onLogin={handleLogin} />;

  // Logged in but must change password first
  if (user.force_password_change) return <ChangePassword onChanged={handlePasswordChanged} />;

  return (
    <HashRouter>
      <Nav user={user} onLogout={handleLogout} />
      <div className="app">
        <Routes>
          <Route path="/" element={<CalendarPage />} />

          <Route path="/blocks" element={
            <RoleRoute user={user} allowedRoles={['admin', 'scheduler']}>
              <Blocks />
            </RoleRoute>
          } />
          <Route path="/blocks/:id" element={
            <RoleRoute user={user} allowedRoles={['admin', 'scheduler']}>
              <BlockGrid />
            </RoleRoute>
          } />

          <Route path="/import" element={
            <RoleRoute user={user} allowedRoles={['admin', 'scheduler']}>
              <ImportSchedule />
            </RoleRoute>
          } />

          <Route path="/admin" element={
            <RoleRoute user={user} allowedRoles={['admin']}>
              <Admin user={user} onLogout={handleLogout} />
            </RoleRoute>
          } />
          <Route path="/admin/:tab" element={
            <RoleRoute user={user} allowedRoles={['admin']}>
              <Admin user={user} onLogout={handleLogout} />
            </RoleRoute>
          } />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </HashRouter>
  );
}
