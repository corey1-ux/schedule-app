import { useState, useEffect, useCallback, useRef } from 'react';
import './Staff.css';

const FTE_OPTIONS = [
  { value: 0.5,  label: '0.5',  detail: '2 shifts/wk · 4/PP' },
  { value: 0.6,  label: '0.6',  detail: '2–3 shifts/wk · 5/PP' },
  { value: 0.75, label: '0.75', detail: '3 shifts/wk · 6/PP' },
  { value: 1.0,  label: '1.0',  detail: '4 shifts/wk · 8/PP' },
];

// Three-dot menu for each staff row
function KebabMenu({ onEdit, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <div className="sf-kebab-wrap" ref={ref}>
      <button className="sf-kebab-btn" onClick={() => setOpen(o => !o)} title="Actions">⋮</button>
      {open && (
        <div className="sf-kebab-menu">
          <button onClick={() => { onEdit(); setOpen(false); }}>Edit</button>
          <button className="sf-kebab-delete" onClick={() => { onDelete(); setOpen(false); }}>Delete</button>
        </div>
      )}
    </div>
  );
}

function StaffForm({ initial, skills, onSave, onCancel }) {
  const [name, setName]               = useState(initial?.name || '');
  const [isCasual, setIsCasual]       = useState(initial?.is_casual ?? false);
  const [fte, setFte]                 = useState(initial?.fte ?? 1.0);
  const [selectedSkills, setSelected] = useState(initial?.skills?.map(s => s.id) || []);
  // minimums keyed by skill id (integer)
  const [minimums, setMinimums] = useState(
    Object.fromEntries(
      Object.entries(initial?.skill_minimums || {}).map(([k, v]) => [parseInt(k, 10), v])
    )
  );
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState('');

  const toggleSkill = (id) =>
    setSelected(prev => prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]);

  const setMin = (skillId, val) =>
    setMinimums(prev => ({ ...prev, [skillId]: parseInt(val, 10) || 0 }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setError('Name is required.'); return; }
    setSaving(true);
    setError('');
    // Only send non-zero minimums for currently selected skills
    const skill_minimums = Object.fromEntries(
      selectedSkills
        .filter(id => (minimums[id] ?? 0) > 0)
        .map(id => [id, minimums[id]])
    );
    const res = await onSave({
      name:           name.trim(),
      fte:            parseFloat(fte),
      is_casual:      isCasual,
      skill_ids:      selectedSkills,
      skill_minimums,
    });
    if (res?.error) { setError(res.error); setSaving(false); }
  };

  return (
    <form className="sf-form" onSubmit={handleSubmit}>
      <div className="sf-form-grid">
        <div className="sf-field">
          <label className="sf-label">Name</label>
          <input
            className="sf-input"
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Full name"
            autoFocus
          />
        </div>

        <div className="sf-field">
          <label className="sf-label">Type</label>
          <div className="sf-fte-group">
            <button
              type="button"
              className={`sf-fte-btn ${!isCasual ? 'active' : ''}`}
              onClick={() => setIsCasual(false)}
            >
              <span className="sf-fte-val">Scheduled</span>
              <span className="sf-fte-sub">Optimizer-managed</span>
            </button>
            <button
              type="button"
              className={`sf-fte-btn ${isCasual ? 'active' : ''}`}
              onClick={() => setIsCasual(true)}
            >
              <span className="sf-fte-val">Casual</span>
              <span className="sf-fte-sub">Excluded from optimizer</span>
            </button>
          </div>
        </div>

        {!isCasual && (
          <div className="sf-field">
            <label className="sf-label">FTE</label>
            <div className="sf-fte-group">
              {FTE_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  className={`sf-fte-btn ${parseFloat(fte) === opt.value ? 'active' : ''}`}
                  onClick={() => setFte(opt.value)}
                >
                  <span className="sf-fte-val">{opt.label}</span>
                  <span className="sf-fte-sub">{opt.detail}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="sf-field">
          <label className="sf-label">Skills</label>
          <div className="sf-skill-group">
            {skills.map(s => (
              <button
                key={s.id}
                type="button"
                className={`sf-skill-btn ${selectedSkills.includes(s.id) ? 'active' : ''}`}
                onClick={() => toggleSkill(s.id)}
              >
                {s.name}
              </button>
            ))}
          </div>
        </div>

        {selectedSkills.length > 0 && (
          <div className="sf-field">
            <label className="sf-label">Min / Week</label>
            <div className="sf-minimums-group">
              {skills.filter(s => selectedSkills.includes(s.id)).map(s => (
                <div key={s.id} className="sf-minimum-row">
                  <span className="sf-minimum-label">{s.name}</span>
                  <input
                    type="number" min="0" max="7"
                    className="sf-minimum-input"
                    value={minimums[s.id] ?? 0}
                    onChange={e => setMin(s.id, e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {error && <p className="sf-error">{error}</p>}

      <div className="sf-form-footer">
        <button type="submit" className="sf-btn-primary" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save Changes' : 'Add Member'}
        </button>
        <button type="button" className="sf-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── FTE Tiers section ──────────────────────────────────────────────────────

function TierForm({ initial, onSave, onCancel }) {
  const [fte,    setFte]    = useState(initial?.fte    ?? '');
  const [weekly, setWeekly] = useState(initial?.shifts_per_week ?? '');
  const [pp,     setPp]     = useState(initial?.shifts_per_pp   ?? '');
  const [saving, setSaving] = useState(false);
  const [error,  setError]  = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    const fteVal = parseFloat(fte);
    const wVal   = parseInt(weekly, 10);
    const ppVal  = parseInt(pp, 10);
    if (isNaN(fteVal) || fteVal <= 0 || fteVal > 1 || isNaN(wVal) || isNaN(ppVal) || wVal < 1 || ppVal < 1) {
      setError('Enter a valid FTE (0–1) and positive integers for shifts.'); return;
    }
    setSaving(true); setError('');
    const res = await onSave({ fte: fteVal, shifts_per_week: wVal, shifts_per_pp: ppVal });
    if (res?.error) { setError(res.error); setSaving(false); }
  };

  return (
    <form className="sf-tier-form" onSubmit={handleSubmit}>
      <div className="sf-tier-form-row">
        <div className="sf-field">
          <label className="sf-label">FTE</label>
          <input className="sf-input sf-input-sm" type="number" step="0.05" min="0.05" max="1"
            value={fte} onChange={e => setFte(e.target.value)}
            placeholder="e.g. 0.5" disabled={!!initial} />
        </div>
        <div className="sf-field">
          <label className="sf-label">Shifts / Week</label>
          <input className="sf-input sf-input-sm" type="number" min="1" max="7"
            value={weekly} onChange={e => setWeekly(e.target.value)} placeholder="e.g. 2" />
        </div>
        <div className="sf-field">
          <label className="sf-label">Shifts / Pay Period</label>
          <input className="sf-input sf-input-sm" type="number" min="1"
            value={pp} onChange={e => setPp(e.target.value)} placeholder="e.g. 4" />
        </div>
        <div className="sf-tier-form-actions">
          <button type="submit" className="sf-btn-primary" disabled={saving}>
            {saving ? 'Saving…' : initial ? 'Save' : 'Add'}
          </button>
          <button type="button" className="sf-btn-ghost" onClick={onCancel}>Cancel</button>
        </div>
      </div>
      {error && <p className="sf-error">{error}</p>}
    </form>
  );
}

export default function Staff(props) {
  const [staff, setStaff]           = useState([]);
  const [skills, setSkills]         = useState([]);
  const [loading, setLoading]       = useState(true);
  const [showAdd, setShowAdd]       = useState(false);
  const [editId, setEditId]         = useState(null);
  const [deleteId, setDeleteId]     = useState(null);

  // FTE tiers state
  const [tiers, setTiers]           = useState([]);
  const [showAddTier, setShowAddTier] = useState(false);
  const [editTierFte, setEditTierFte] = useState(null);
  const [deleteTierFte, setDeleteTierFte] = useState(null);

  const loadTiers = useCallback(() =>
    fetch('/api/fte-tiers').then(r => r.json()).then(setTiers)
  , []);

  const load = useCallback(() =>
    Promise.all([
      fetch('/api/staff').then(r => r.json()),
      fetch('/api/skills').then(r => r.json()),
    ]).then(([s, sk]) => { setStaff(s); setSkills(sk); setLoading(false); })
  , []);

  useEffect(() => { load(); loadTiers(); }, [load, loadTiers]);

  const handleAddTier = async (data) => {
    const res = await fetch('/api/fte-tiers', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => r.json());
    if (res.error) return res;
    setShowAddTier(false); loadTiers();
  };

  const handleEditTier = async (fte, data) => {
    const res = await fetch(`/api/fte-tiers/${fte}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => r.json());
    if (res.error) return res;
    setEditTierFte(null); loadTiers();
  };

  const handleDeleteTier = async (fte) => {
    await fetch(`/api/fte-tiers/${fte}`, { method: 'DELETE' });
    setDeleteTierFte(null); loadTiers();
  };

  const handleAdd = async (data) => {
    const res = await fetch('/api/staff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => r.json());
    if (res.error) return res;
    setShowAdd(false);
    load();
  };

  const handleEdit = async (id, data) => {
    const res = await fetch(`/api/staff/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => r.json());
    if (res.error) return res;
    setEditId(null);
    load();
  };

  const handleDelete = async (id) => {
    await fetch(`/api/staff/${id}`, { method: 'DELETE' });
    setDeleteId(null);
    load();
  };

  const openEdit = (id) => {
    setEditId(editId === id ? null : id);
    setShowAdd(false);
  };

  const openAdd = () => {
    setShowAdd(true);
    setEditId(null);
  };

  if (loading) return <div className="status">Loading…</div>;

  const totalFte = staff.reduce((sum, s) => sum + s.fte, 0);

  return (
    <div className={props.embedded ? undefined : 'sf-page'}>

      {/* Page header */}
      <div className="sf-page-header">
        <div className="sf-page-title">
          <h1>Staff</h1>
          <span className="sf-page-meta">
            {staff.length} member{staff.length !== 1 ? 's' : ''} &middot; {totalFte.toFixed(2)} FTE
          </span>
        </div>
        {!showAdd && (
          <button className="sf-btn-primary" onClick={openAdd}>+ Add Member</button>
        )}
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="sf-card sf-card-form">
          <p className="sf-card-heading">New Staff Member</p>
          <StaffForm
            skills={skills}
            onSave={handleAdd}
            onCancel={() => setShowAdd(false)}
          />
        </div>
      )}

      {/* FTE Tiers */}
      <div className="sf-section-header">
        <div>
          <h2 className="sf-section-title">FTE Tiers</h2>
          <p className="sf-section-sub">Controls optimizer limits and shift summary targets. Changes apply immediately to the next optimization run.</p>
        </div>
        {!showAddTier && (
          <button className="sf-btn-ghost" onClick={() => { setShowAddTier(true); setEditTierFte(null); }}>
            + Add Tier
          </button>
        )}
      </div>

      {showAddTier && (
        <div className="sf-card sf-card-form">
          <p className="sf-card-heading">New FTE Tier</p>
          <TierForm onSave={handleAddTier} onCancel={() => setShowAddTier(false)} />
        </div>
      )}

      <div className="sf-card">
        {tiers.length === 0 ? (
          <p className="sf-empty">No tiers configured.</p>
        ) : (
          <table className="sf-table">
            <thead>
              <tr>
                <th>FTE</th>
                <th>Shifts / Week</th>
                <th>Shifts / Pay Period</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {tiers.map(t => (
                <>
                  <tr key={t.fte} className={editTierFte === t.fte ? 'sf-row-active' : ''}>
                    <td className="sf-col-name">
                      <span className="sf-badge">{t.fte} FTE</span>
                    </td>
                    <td>{t.shifts_per_week}</td>
                    <td>{t.shifts_per_pp}</td>
                    <td className="sf-col-actions">
                      {deleteTierFte === t.fte ? (
                        <span className="sf-delete-confirm">
                          <span className="sf-confirm-text">Remove {t.fte} FTE tier?</span>
                          <button className="sf-btn-danger" onClick={() => handleDeleteTier(t.fte)}>Delete</button>
                          <button className="sf-btn-ghost" onClick={() => setDeleteTierFte(null)}>Cancel</button>
                        </span>
                      ) : (
                        <>
                          <button
                            className={`sf-btn-ghost ${editTierFte === t.fte ? 'sf-active' : ''}`}
                            onClick={() => { setEditTierFte(editTierFte === t.fte ? null : t.fte); setShowAddTier(false); }}
                          >
                            {editTierFte === t.fte ? 'Cancel' : 'Edit'}
                          </button>
                          <button className="sf-btn-ghost sf-btn-destruct" onClick={() => setDeleteTierFte(t.fte)}>
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                  {editTierFte === t.fte && (
                    <tr key={`edit-${t.fte}`} className="sf-edit-row">
                      <td colSpan={4}>
                        <TierForm
                          initial={t}
                          onSave={(data) => handleEditTier(t.fte, data)}
                          onCancel={() => setEditTierFte(null)}
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

      {/* Staff table */}
      <div className="sf-section-header" style={{ marginTop: '0.5rem' }}>
        <div>
          <h2 className="sf-section-title">Members</h2>
        </div>
      </div>

      <div className="sf-card">
        {staff.length === 0 ? (
          <p className="sf-empty">No staff members yet.</p>
        ) : (
          <table className="sf-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>FTE</th>
                <th>Skills</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {staff.map(s => (
                <>
                  <tr key={s.id} className={editId === s.id ? 'sf-row-active' : ''}>
                    <td className="sf-col-name">{s.name}</td>
                    <td className="sf-col-fte">
                      {s.is_casual
                        ? <span className="sf-badge sf-badge-casual">Casual</span>
                        : <span className="sf-badge">{s.fte} FTE</span>
                      }
                    </td>
                    <td className="sf-col-skills">
                      {s.skills.length === 0
                        ? <span className="sf-no-skills">—</span>
                        : s.skills.map(sk => (
                            <span key={sk.id} className="sf-skill-tag">{sk.name}</span>
                          ))
                      }
                    </td>
                    <td className="sf-col-actions">
                      {deleteId === s.id ? (
                        <span className="sf-delete-confirm">
                          <span className="sf-confirm-text">Remove {s.name}?</span>
                          <button className="sf-btn-danger" onClick={() => handleDelete(s.id)}>Delete</button>
                          <button className="sf-btn-ghost" onClick={() => setDeleteId(null)}>Cancel</button>
                        </span>
                      ) : (
                        <KebabMenu
                          onEdit={() => openEdit(s.id)}
                          onDelete={() => setDeleteId(s.id)}
                        />
                      )}
                    </td>
                  </tr>
                  {editId === s.id && (
                    <tr key={`edit-${s.id}`} className="sf-edit-row">
                      <td colSpan={4}>
                        <StaffForm
                          initial={s}
                          skills={skills}
                          onSave={(data) => handleEdit(s.id, data)}
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
    </div>
  );
}
