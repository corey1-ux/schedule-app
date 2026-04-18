import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import './Blocks.css';

const CURRENT_YEAR = new Date().getFullYear();

export default function Blocks() {
  const [blocks, setBlocks]       = useState([]);
  const [startDate, setStart]     = useState('');
  const [loading, setLoading]     = useState(true);
  const [showForm, setShowForm]   = useState(false);
  const [deleteId, setDeleteId]   = useState(null);
  const [selectedYear, setYear]   = useState(CURRENT_YEAR);
  const [toast, setToast]         = useState(null);

  const load = useCallback(() =>
    fetch('/api/blocks')
      .then(r => r.json())
      .then(data => { setBlocks(data); setLoading(false); }), []);

  useEffect(() => { load(); }, [load]);

  // Dismiss toast after 5 s
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [toast]);

  // All years present in blocks + current year, sorted descending
  const years = [...new Set([
    CURRENT_YEAR,
    ...blocks.map(b => new Date(b.start_date + 'T00:00:00').getFullYear()),
  ])].sort((a, b) => b - a);

  const filteredBlocks = blocks.filter(b =>
    new Date(b.start_date + 'T00:00:00').getFullYear() === selectedYear
  );

  const create = () => {
    if (!startDate) return;
    fetch('/api/blocks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start_date: startDate }),
    }).then(async r => {
      if (r.status === 409) {
        const data = await r.json();
        setToast(data.error);
        return;
      }
      setStart(''); setShowForm(false);
      // Switch to the year of the newly created block
      const year = new Date(startDate + 'T00:00:00').getFullYear();
      setYear(year);
      load();
    });
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

      {/* Top toast */}
      {toast && (
        <div className="bl-toast-top">
          <span>{toast}</span>
          <button className="bl-toast-close" onClick={() => setToast(null)}>×</button>
        </div>
      )}

      {/* Page header */}
      <div className="bl-page-header">
        <div className="bl-page-title">
          <h1>Schedule Blocks</h1>
          <span className="bl-page-meta">
            {filteredBlocks.length} block{filteredBlocks.length !== 1 ? 's' : ''} in {selectedYear}
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
              <label className="bl-label">Start Date</label>
              <input
                className="bl-input"
                type="date"
                value={startDate}
                onChange={e => setStart(e.target.value)}
                autoFocus
              />
            </div>
            <button className="bl-btn-primary" onClick={create}>Create</button>
            <button className="bl-btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Year selector */}
      <div className="bl-year-row">
        <div className="bl-year-control">
          <svg className="bl-year-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="1.5" y="2.5" width="13" height="12" rx="1.5"/>
            <path d="M1.5 6.5h13"/>
            <path d="M5 1v3M11 1v3"/>
          </svg>
          <select
            className="bl-year-select"
            value={selectedYear}
            onChange={e => setYear(Number(e.target.value))}
          >
            {years.map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Blocks table */}
      <div className="bl-card">
        {filteredBlocks.length === 0 ? (
          <p className="bl-empty">No blocks for {selectedYear}. Create one to get started.</p>
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
              {filteredBlocks.map(b => (
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
