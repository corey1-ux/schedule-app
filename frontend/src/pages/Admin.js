import { useState, useEffect, useCallback } from 'react';
import Staff from './Staff';
import './Admin.css';

const ROLES = ['staff', 'scheduler', 'admin'];

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

// ─────────────────────────────────────────────────────────────────────────────
// Skills tab
// ─────────────────────────────────────────────────────────────────────────────

function SkillForm({ initial, onSave, onCancel }) {
  const [name,     setName]     = useState(initial?.name     ?? '');
  const [priority, setPriority] = useState(initial?.priority ?? 0);
  const [minimum,  setMinimum]  = useState(initial?.minimum  ?? 0);
  const [saving,   setSaving]   = useState(false);
  const [error,    setError]    = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setError('Name is required.'); return; }
    setSaving(true); setError('');
    const res = await onSave({ name: name.trim(), priority: parseInt(priority, 10), minimum: parseInt(minimum, 10) });
    if (res?.error) { setError(res.error); setSaving(false); }
  };

  return (
    <form onSubmit={handleSubmit}>
      <div className="adm-form-row">
        <div className="adm-field" style={{ flex: '1 1 180px' }}>
          <label className="adm-label">Skill Name</label>
          <input className="adm-input" value={name} onChange={e => setName(e.target.value)}
            placeholder="e.g. IR RN" autoFocus />
        </div>
        <div className="adm-field">
          <label className="adm-label">Priority (1=highest)</label>
          <input className="adm-input adm-input-sm" type="number" min="0" max="9"
            value={priority} onChange={e => setPriority(e.target.value)} />
        </div>
        <div className="adm-field">
          <label className="adm-label">Daily Minimum</label>
          <input className="adm-input adm-input-sm" type="number" min="0"
            value={minimum} onChange={e => setMinimum(e.target.value)} />
        </div>
        <button type="submit" className="adm-btn-primary" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save' : 'Add Skill'}
        </button>
        <button type="button" className="adm-btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
      {error && <p className="adm-error">{error}</p>}
    </form>
  );
}

function SkillsTab() {
  const [skills,    setSkills]    = useState([]);
  const [minimums,  setMinimums]  = useState({});
  const [loading,   setLoading]   = useState(true);
  const [showAdd,   setShowAdd]   = useState(false);
  const [editId,    setEditId]    = useState(null);
  const [deleteId,  setDeleteId]  = useState(null);

  const load = useCallback(() =>
    Promise.all([
      fetch('/api/skills').then(r => r.json()),
      fetch('/api/skill-minimums').then(r => r.json()),
    ]).then(([sk, min]) => { setSkills(sk); setMinimums(min); setLoading(false); })
  , []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async ({ name, priority, minimum }) => {
    const res = await fetch('/api/skills', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, priority }),
    }).then(r => r.json());
    if (res.error) return res;
    // save minimum if non-zero
    if (minimum > 0 && res.id) {
      await fetch('/api/skill-minimums', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [res.id]: minimum }),
      });
    }
    setShowAdd(false); load();
  };

  const handleEdit = async (id, { name, priority, minimum }) => {
    const res = await fetch(`/api/skills/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, priority }),
    }).then(r => r.json());
    if (res.error) return res;
    await fetch('/api/skill-minimums', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [id]: minimum }),
    });
    setEditId(null); load();
  };

  const handleDelete = async (id) => {
    await fetch(`/api/skills/${id}`, { method: 'DELETE' });
    setDeleteId(null); load();
  };

  if (loading) return <p className="adm-empty">Loading…</p>;

  return (
    <>
      <div className="adm-section-header">
        <div>
          <h2 className="adm-section-title">Skills</h2>
          <p className="adm-section-sub">Manage skill types, optimizer priority, and daily minimum staffing.</p>
        </div>
        {!showAdd && (
          <button className="adm-btn-primary" onClick={() => { setShowAdd(true); setEditId(null); }}>
            + Add Skill
          </button>
        )}
      </div>

      {showAdd && (
        <div className="adm-card adm-card-form">
          <p className="adm-card-heading">New Skill</p>
          <SkillForm onSave={handleAdd} onCancel={() => setShowAdd(false)} />
        </div>
      )}

      <div className="adm-card">
        {skills.length === 0 ? (
          <p className="adm-empty">No skills yet.</p>
        ) : (
          <table className="adm-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Priority</th>
                <th>Daily Min.</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {skills.map(sk => (
                <>
                  <tr key={sk.id} className={editId === sk.id ? 'adm-row-active' : ''}>
                    <td className="adm-col-name">{sk.name}</td>
                    <td>
                      <span className="adm-badge">{sk.priority || '—'}</span>
                    </td>
                    <td>{minimums[sk.id] ?? 0}</td>
                    <td className="adm-col-actions">
                      {deleteId === sk.id ? (
                        <div className="adm-delete-confirm">
                          <span className="adm-confirm-text">Delete {sk.name}?</span>
                          <button className="adm-btn-danger" onClick={() => handleDelete(sk.id)}>Delete</button>
                          <button className="adm-btn-ghost" onClick={() => setDeleteId(null)}>Cancel</button>
                        </div>
                      ) : (
                        <div className="adm-col-actions-inner">
                          <button className="adm-btn-ghost"
                            onClick={() => { setEditId(editId === sk.id ? null : sk.id); setShowAdd(false); }}>
                            {editId === sk.id ? 'Cancel' : 'Edit'}
                          </button>
                          <button className="adm-btn-destruct" onClick={() => setDeleteId(sk.id)}>Delete</button>
                        </div>
                      )}
                    </td>
                  </tr>
                  {editId === sk.id && (
                    <tr key={`edit-${sk.id}`} className="adm-edit-row">
                      <td colSpan={4}>
                        <SkillForm
                          initial={{ ...sk, minimum: minimums[sk.id] ?? 0 }}
                          onSave={(data) => handleEdit(sk.id, data)}
                          onCancel={() => setEditId(null)}
                        />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Template tab
// ─────────────────────────────────────────────────────────────────────────────

function TemplateTab() {
  const [skills,       setSkills]       = useState([]);
  const [needs,        setNeeds]        = useState({});   // { day: { skill_id: qty } }
  const [dayPriority,  setDayPriority]  = useState({});   // { day: priority }
  const [loading,      setLoading]      = useState(true);
  const [saving,       setSaving]       = useState(false);
  const [saved,        setSaved]        = useState(false);

  const load = useCallback(() =>
    Promise.all([
      fetch('/api/skills').then(r => r.json()),
      fetch('/api/template/needs').then(r => r.json()),
      fetch('/api/day-priorities').then(r => r.json()),
    ]).then(([sk, n, dp]) => {
      setSkills(sk.filter(s => s.name !== 'Call'));
      // Flatten needs to { day: { skill_id: qty } }
      const flat = {};
      for (const [day, skMap] of Object.entries(n)) {
        flat[day] = {};
        for (const [skid, info] of Object.entries(skMap)) {
          flat[day][skid] = info.quantity;
        }
      }
      setNeeds(flat);
      setDayPriority(dp);
      setLoading(false);
    })
  , []);

  useEffect(() => { load(); }, [load]);

  const getQty = (day, skillId) => needs[day]?.[skillId] ?? 0;

  const setQty = (day, skillId, val) => {
    setNeeds(prev => ({
      ...prev,
      [day]: { ...(prev[day] ?? {}), [skillId]: parseInt(val, 10) || 0 },
    }));
    setSaved(false);
  };

  const setDp = (day, val) => {
    setDayPriority(prev => ({ ...prev, [day]: parseInt(val, 10) || 0 }));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true); setSaved(false);
    // Build rows array
    const rows = [];
    for (const day of WEEKDAYS) {
      for (const sk of skills) {
        const qty = getQty(day, sk.id);
        if (qty > 0) rows.push({ day, skill_id: sk.id, quantity: qty });
      }
    }
    await Promise.all([
      fetch('/api/template/needs', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rows),
      }),
      fetch('/api/day-priorities', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dayPriority),
      }),
    ]);
    setSaving(false); setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  if (loading) return <p className="adm-empty">Loading…</p>;

  return (
    <>
      <div className="adm-section-header">
        <div>
          <h2 className="adm-section-title">Weekly Template</h2>
          <p className="adm-section-sub">
            Set how many staff are needed per skill per day. Day priority (1=highest) affects the optimizer's weighting.
          </p>
        </div>
      </div>

      <div className="adm-card adm-card-form">
        <div className="adm-template-wrap">
          <table className="adm-template-grid">
            <thead>
              <tr>
                <th className="adm-th-skill">Skill</th>
                {WEEKDAYS.map(d => <th key={d}>{d.slice(0, 3)}</th>)}
              </tr>
            </thead>
            <tbody>
              {/* Day priority row */}
              <tr className="adm-priority-row">
                <td style={{ textAlign: 'left' }}>
                  <span className="adm-priority-label">Day priority</span>
                </td>
                {WEEKDAYS.map(d => (
                  <td key={d}>
                    <span className="adm-priority-label">priority</span>
                    <input
                      className="adm-priority-input"
                      type="number" min="0" max="9"
                      value={dayPriority[d] ?? 0}
                      onChange={e => setDp(d, e.target.value)}
                    />
                  </td>
                ))}
              </tr>

              {/* One row per skill */}
              {skills.map(sk => (
                <tr key={sk.id}>
                  <td className="adm-td-skill">{sk.name}</td>
                  {WEEKDAYS.map(d => (
                    <td key={d}>
                      <input
                        className="adm-qty-input"
                        type="number" min="0" max="20"
                        value={getQty(d, sk.id)}
                        onChange={e => setQty(d, sk.id, e.target.value)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="adm-template-footer">
          <button className="adm-btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save Template'}
          </button>
          {saved && <span className="adm-save-msg">Saved</span>}
        </div>
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Closed Dates tab
// ─────────────────────────────────────────────────────────────────────────────

function ClosedDatesTab() {
  const [dates,   setDates]   = useState([]);
  const [newDate, setNewDate] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() =>
    fetch('/api/closed-dates').then(r => r.json()).then(d => { setDates(d); setLoading(false); })
  , []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!newDate) return;
    await fetch('/api/closed-dates', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: newDate }),
    });
    setNewDate(''); load();
  };

  const handleDelete = async (date) => {
    await fetch(`/api/closed-dates/${date}`, { method: 'DELETE' });
    load();
  };

  if (loading) return <p className="adm-empty">Loading…</p>;

  const fmt = (d) => new Date(d + 'T00:00:00').toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  });

  return (
    <>
      <div className="adm-section-header">
        <div>
          <h2 className="adm-section-title">Closed Dates</h2>
          <p className="adm-section-sub">Dates marked closed are excluded from the optimizer and the schedule grid.</p>
        </div>
      </div>

      <div className="adm-card">
        {dates.length === 0 ? (
          <p className="adm-empty" style={{ paddingBottom: 0 }}>No closed dates.</p>
        ) : (
          <div className="adm-date-list">
            {dates.map(d => (
              <span key={d} className="adm-date-chip">
                {fmt(d)}
                <button onClick={() => handleDelete(d)} title="Remove">×</button>
              </span>
            ))}
          </div>
        )}
        <div className="adm-date-add">
          <div className="adm-field">
            <label className="adm-label">Add Closed Date</label>
            <input className="adm-input" type="date" value={newDate}
              onChange={e => setNewDate(e.target.value)} style={{ width: 'auto' }} />
          </div>
          <button className="adm-btn-primary" onClick={handleAdd} disabled={!newDate}>Add</button>
        </div>
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Users tab
// ─────────────────────────────────────────────────────────────────────────────

function UsersTab({ currentUser }) {
  const [users,    setUsers]    = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [showAdd,  setShowAdd]  = useState(false);
  const [error,    setError]    = useState('');
  const [deleteId, setDeleteId] = useState(null);
  const [resetId,  setResetId]  = useState(null);
  const [resetPw,  setResetPw]  = useState('');

  // new user form
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole,     setNewRole]     = useState('staff');
  const [saving,      setSaving]      = useState(false);

  const load = useCallback(() =>
    fetch('/api/users', { credentials: 'include' })
      .then(r => r.json())
      .then(u => { setUsers(u); setLoading(false); })
  , []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!newUsername.trim() || !newPassword) { setError('Username and password are required.'); return; }
    setSaving(true); setError('');
    const res = await fetch('/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username: newUsername.trim(), password: newPassword, role: newRole }),
    }).then(r => r.json());
    setSaving(false);
    if (res.error) { setError(res.error); return; }
    setShowAdd(false); setNewUsername(''); setNewPassword(''); setNewRole('staff');
    load();
  };

  const handleRoleChange = async (id, role) => {
    await fetch(`/api/users/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ role }),
    });
    load();
  };

  const handleDelete = async (id) => {
    await fetch(`/api/users/${id}`, { method: 'DELETE', credentials: 'include' });
    setDeleteId(null); load();
  };

  const handleResetPw = async (id) => {
    if (!resetPw) return;
    setError('');
    const res = await fetch(`/api/users/${id}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ password: resetPw }),
    }).then(r => r.json());
    if (res.error) { setError(res.error); return; }
    setResetId(null); setResetPw(''); load();
  };

  if (loading) return <p className="adm-empty">Loading…</p>;

  return (
    <>
      <div className="adm-section-header">
        <div>
          <h2 className="adm-section-title">Users</h2>
          <p className="adm-section-sub">
            Manage who can access the app. New users are required to set their own password on first login.
          </p>
        </div>
        {!showAdd && (
          <button className="adm-btn-primary" onClick={() => { setShowAdd(true); setError(''); }}>
            + Add User
          </button>
        )}
      </div>

      {showAdd && (
        <div className="adm-card adm-card-form">
          <p className="adm-card-heading">New User</p>
          <div className="adm-form-row">
            <div className="adm-field" style={{ flex: '1 1 160px' }}>
              <label className="adm-label">Username</label>
              <input className="adm-input" value={newUsername} autoFocus
                onChange={e => { setNewUsername(e.target.value); setError(''); }}
                placeholder="e.g. jsmith" />
            </div>
            <div className="adm-field" style={{ flex: '1 1 160px' }}>
              <label className="adm-label">Temporary Password</label>
              <input className="adm-input" type="password" value={newPassword}
                onChange={e => { setNewPassword(e.target.value); setError(''); }}
                placeholder="Min. 8 characters" />
            </div>
            <div className="adm-field">
              <label className="adm-label">Role</label>
              <select className="adm-input" value={newRole} onChange={e => setNewRole(e.target.value)}>
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <button className="adm-btn-primary" onClick={handleAdd} disabled={saving}>
              {saving ? 'Saving…' : 'Create'}
            </button>
            <button className="adm-btn-ghost" onClick={() => { setShowAdd(false); setError(''); }}>
              Cancel
            </button>
          </div>
          {error && <p className="adm-error">{error}</p>}
        </div>
      )}

      <div className="adm-card">
        {users.length === 0 ? (
          <p className="adm-empty">No users yet.</p>
        ) : (
          <table className="adm-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Role</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <>
                  <tr key={u.id}>
                    <td className="adm-col-name">{u.username}</td>
                    <td>
                      {u.id === currentUser.id ? (
                        <span className="adm-badge">{u.role}</span>
                      ) : (
                        <select className="adm-input adm-input-sm" value={u.role}
                          onChange={e => handleRoleChange(u.id, e.target.value)}>
                          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                      )}
                    </td>
                    <td>
                      {u.force_password_change
                        ? <span className="adm-badge adm-badge-warn">Pending password set</span>
                        : <span className="adm-badge adm-badge-ok">Active</span>}
                    </td>
                    <td className="adm-col-actions">
                      {deleteId === u.id ? (
                        <div className="adm-delete-confirm">
                          <span className="adm-confirm-text">Delete {u.username}?</span>
                          <button className="adm-btn-danger" onClick={() => handleDelete(u.id)}>Delete</button>
                          <button className="adm-btn-ghost" onClick={() => setDeleteId(null)}>Cancel</button>
                        </div>
                      ) : resetId === u.id ? (
                        <div className="adm-delete-confirm">
                          <input className="adm-input adm-input-sm" type="password"
                            placeholder="New temp password" value={resetPw}
                            onChange={e => setResetPw(e.target.value)} autoFocus />
                          <button className="adm-btn-primary" onClick={() => handleResetPw(u.id)}>Save</button>
                          <button className="adm-btn-ghost" onClick={() => { setResetId(null); setResetPw(''); }}>Cancel</button>
                        </div>
                      ) : (
                        <div className="adm-col-actions-inner">
                          <button className="adm-btn-ghost" onClick={() => setResetId(u.id)}>Reset PW</button>
                          {u.id !== currentUser.id && (
                            <button className="adm-btn-destruct" onClick={() => setDeleteId(u.id)}>Delete</button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                  {error && resetId === u.id && (
                    <tr key={`err-${u.id}`}>
                      <td colSpan={4}><p className="adm-error">{error}</p></td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Blocks tab (rename only)
// ─────────────────────────────────────────────────────────────────────────────

function BlocksTab() {
  const [blocks,  setBlocks]  = useState([]);
  const [loading, setLoading] = useState(true);
  const [editId,  setEditId]  = useState(null);
  const [editName, setEditName] = useState('');

  const load = useCallback(() =>
    fetch('/api/blocks').then(r => r.json()).then(d => { setBlocks(d); setLoading(false); })
  , []);

  useEffect(() => { load(); }, [load]);

  const startEdit = (b) => { setEditId(b.id); setEditName(b.name); };

  const handleRename = async (id) => {
    if (!editName.trim()) return;
    await fetch(`/api/blocks/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: editName.trim() }),
    });
    setEditId(null);
    load();
  };

  const years = [...new Set(blocks.map(b =>
    new Date(b.start_date + 'T00:00:00').getFullYear()
  ))].sort((a, b) => b - a);

  if (loading) return <p className="adm-empty">Loading…</p>;

  return (
    <>
      <div className="adm-section-header">
        <div>
          <h2 className="adm-section-title">Blocks</h2>
          <p className="adm-section-sub">Rename schedule blocks. Create and delete blocks from the Blocks page.</p>
        </div>
      </div>

      {years.map(year => (
        <div key={year} className="adm-card" style={{ marginBottom: '1rem' }}>
          <div className="adm-blocks-year-header">{year}</div>
          <table className="adm-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Dates</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {blocks
                .filter(b => new Date(b.start_date + 'T00:00:00').getFullYear() === year)
                .map(b => (
                  <>
                    <tr key={b.id} className={editId === b.id ? 'adm-row-active' : ''}>
                      <td className="adm-col-name">{b.name}</td>
                      <td style={{ fontSize: '0.8125rem', color: '#52525b' }}>
                        {b.start_date} – {b.end_date}
                      </td>
                      <td>
                        <span className={`adm-badge${b.status === 'published' ? ' adm-badge-ok' : ''}`}>
                          {b.status}
                        </span>
                      </td>
                      <td className="adm-col-actions">
                        <div className="adm-col-actions-inner">
                          <button
                            className="adm-btn-ghost"
                            onClick={() => editId === b.id ? setEditId(null) : startEdit(b)}
                          >
                            {editId === b.id ? 'Cancel' : 'Rename'}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {editId === b.id && (
                      <tr key={`edit-${b.id}`} className="adm-edit-row">
                        <td colSpan={4}>
                          <div className="adm-form-row">
                            <div className="adm-field" style={{ flex: '1 1 240px' }}>
                              <label className="adm-label">New Name</label>
                              <input
                                className="adm-input"
                                value={editName}
                                onChange={e => setEditName(e.target.value)}
                                onKeyDown={e => e.key === 'Enter' && handleRename(b.id)}
                                autoFocus
                              />
                            </div>
                            <button className="adm-btn-primary" onClick={() => handleRename(b.id)}>
                              Save
                            </button>
                            <button className="adm-btn-ghost" onClick={() => setEditId(null)}>
                              Cancel
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
            </tbody>
          </table>
        </div>
      ))}

      {blocks.length === 0 && <p className="adm-empty">No blocks yet.</p>}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Admin page
// ─────────────────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'users',    label: 'Users'        },
  { id: 'staff',    label: 'Staff'        },
  { id: 'skills',   label: 'Skills'       },
  { id: 'template', label: 'Template'     },
  { id: 'closed',   label: 'Closed Dates' },
  { id: 'blocks',   label: 'Blocks'       },
];

export default function Admin({ user }) {
  const [tab, setTab] = useState('users');

  return (
    <div className="adm-page">
      <div className="adm-page-header">
        <h1>Admin</h1>
        <span className="adm-page-meta">Manage users, staff, skills, scheduling template, and closed dates.</span>
      </div>

      <div className="adm-tabs">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`adm-tab${tab === t.id ? ' active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'users'    && <UsersTab currentUser={user} />}
      {tab === 'staff'    && <Staff embedded />}
      {tab === 'skills'   && <SkillsTab />}
      {tab === 'template' && <TemplateTab />}
      {tab === 'closed'   && <ClosedDatesTab />}
      {tab === 'blocks'   && <BlocksTab />}
    </div>
  );
}
