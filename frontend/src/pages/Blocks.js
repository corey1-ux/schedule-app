import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import './Blocks.css';

export default function Blocks() {
  const [blocks, setBlocks]   = useState([]);
  const [name, setName]       = useState('');
  const [startDate, setStart] = useState('');
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [deleteId, setDeleteId] = useState(null);

  const load = () =>
    fetch('/api/blocks')
      .then(r => r.json())
      .then(data => { setBlocks(data); setLoading(false); });

  useEffect(() => { load(); }, []);

  const create = () => {
    if (!name || !startDate) return;
    fetch('/api/blocks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, start_date: startDate }),
    }).then(() => { setName(''); setStart(''); setShowForm(false); load(); });
  };

  const handleDelete = (id) => {
    fetch(`/api/blocks/${id}`, { method: 'DELETE' }).then(() => {
      setDeleteId(null);
      load();
    });
  };

  if (loading) return <div className="status">Loading…</div>;

  return (
    <div className="bl-page">

      {/* Page header */}
      <div className="bl-page-header">
        <div className="bl-page-title">
          <h1>Schedule Blocks</h1>
          <span className="bl-page-meta">
            {blocks.length} block{blocks.length !== 1 ? 's' : ''}
          </span>
        </div>
        {!showForm && (
          <button className="bl-btn-primary" onClick={() => setShowForm(true)}>
            + New Block
          </button>
        )}
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bl-card bl-card-form">
          <p className="bl-card-heading">New 8-Week Block</p>
          <div className="bl-form-row">
            <div className="bl-field">
              <label className="bl-label">Name</label>
              <input
                className="bl-input"
                type="text"
                placeholder="e.g. 2/22 – 4/18"
                value={name}
                onChange={e => setName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="bl-field">
              <label className="bl-label">Start Date</label>
              <input
                className="bl-input"
                type="date"
                value={startDate}
                onChange={e => setStart(e.target.value)}
              />
            </div>
            <button className="bl-btn-primary" onClick={create}>Create</button>
            <button className="bl-btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Blocks table */}
      <div className="bl-card">
        {blocks.length === 0 ? (
          <p className="bl-empty">No blocks yet. Create one to get started.</p>
        ) : (
          <table className="bl-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Start</th>
                <th>End</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {blocks.map(b => (
                <React.Fragment key={b.id}>
                  <tr>
                    <td className="bl-col-name">{b.name}</td>
                    <td className="bl-col-date">{b.start_date}</td>
                    <td className="bl-col-date">{b.end_date}</td>
                    <td className="bl-col-status">
                      <span className={`bl-badge bl-badge-${b.status}`}>{b.status}</span>
                    </td>
                    <td className="bl-col-actions">
                      {deleteId === b.id ? (
                        <div className="bl-col-actions-inner">
                          <span className="bl-confirm-text">Delete "{b.name}"?</span>
                          <button className="bl-btn-danger" onClick={() => handleDelete(b.id)}>Delete</button>
                          <button className="bl-btn-ghost" onClick={() => setDeleteId(null)}>Cancel</button>
                        </div>
                      ) : (
                        <div className="bl-col-actions-inner">
                          <Link to={`/blocks/${b.id}`} className="bl-btn-link">Open</Link>
                          <button className="bl-btn-destruct" onClick={() => setDeleteId(b.id)}>Delete</button>
                        </div>
                      )}
                    </td>
                  </tr>
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
