import React, { useState, useEffect } from 'react';
import './ImportSchedule.css';

export default function ImportSchedule() {
  const [spreadsheetInput, setSpreadsheetInput] = useState('');
  const [sheetName, setSheetName]               = useState('Sheet1');
  const [blockId, setBlockId]                   = useState('');
  const [blocks, setBlocks]                     = useState([]);
  const [preview, setPreview]                   = useState(null);
  const [applyResult, setApplyResult]           = useState(null);
  const [loading, setLoading]                   = useState(false);
  const [error, setError]                       = useState('');

  useEffect(() => {
    fetch('/api/blocks', { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        const sorted = [...data].sort((a, b) => b.start_date.localeCompare(a.start_date));
        setBlocks(sorted);
        if (sorted.length > 0) setBlockId(String(sorted[0].id));
      })
      .catch(() => {});
  }, []);

  const reset = () => {
    setSpreadsheetInput('');
    setSheetName('Sheet1');
    setBlockId(blocks.length > 0 ? String(blocks[0].id) : '');
    setPreview(null);
    setApplyResult(null);
    setError('');
  };

  const handlePreview = async () => {
    setLoading(true);
    setError('');
    setPreview(null);
    setApplyResult(null);

    try {
      const res = await fetch('/api/import-schedule/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          spreadsheet_id: spreadsheetInput.trim(),
          sheet_name: sheetName.trim(),
          block_id: parseInt(blockId, 10),
        }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Preview failed'); return; }
      setPreview(data);
    } catch {
      setError('Network error — could not reach the server.');
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async () => {
    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/import-schedule/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          block_id: preview.block_id,
          matched_requests: preview.matched_requests,
          matched_unavail: preview.matched_unavail,
        }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Apply failed'); return; }
      setApplyResult(data);
    } catch {
      setError('Network error — could not reach the server.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="imp-page">
      <div className="imp-page-header">
        <h2>Import from Google Sheets</h2>
        <p>Pull schedule requests and unavailability directly from a shared Google Sheet.</p>
      </div>

      {error && <div className="imp-error">{error}</div>}

      {/* Success state */}
      {applyResult ? (
        <>
          <div className="imp-success">
            <div className="imp-success-title">Import complete</div>
            <div className="imp-success-body">
              {applyResult.requests_imported} shift assignment{applyResult.requests_imported !== 1 ? 's' : ''} and{' '}
              {applyResult.unavail_imported} unavailability record{applyResult.unavail_imported !== 1 ? 's' : ''} added
              {preview?.block_name ? ` to "${preview.block_name}"` : ''}.
            </div>
          </div>
          <button className="imp-btn-ghost" onClick={reset}>Import Another</button>
        </>
      ) : (
        <>
          {/* Step 1 — Config form */}
          <div className="imp-card">
            <div className="imp-card-title">Step 1 — Configure</div>
            <div className="imp-form">
              <div className="imp-field">
                <label className="imp-label">Spreadsheet URL or ID</label>
                <input
                  className="imp-input"
                  type="text"
                  placeholder="https://docs.google.com/spreadsheets/d/... or just the ID"
                  value={spreadsheetInput}
                  onChange={e => { setSpreadsheetInput(e.target.value); setPreview(null); }}
                />
              </div>

              <div className="imp-field">
                <label className="imp-label">Sheet Tab Name</label>
                <input
                  className="imp-input"
                  type="text"
                  placeholder="Sheet1"
                  value={sheetName}
                  onChange={e => { setSheetName(e.target.value); setPreview(null); }}
                />
              </div>

              <div className="imp-field">
                <label className="imp-label">Schedule Block</label>
                <select
                  className="imp-select"
                  value={blockId}
                  onChange={e => { setBlockId(e.target.value); setPreview(null); }}
                >
                  {blocks.length === 0 && <option value="">No blocks available</option>}
                  {blocks.map(b => (
                    <option key={b.id} value={b.id}>
                      {b.name} ({b.start_date} → {b.end_date})
                    </option>
                  ))}
                </select>
              </div>

              <div className="imp-actions">
                <button
                  className="imp-btn-primary"
                  onClick={handlePreview}
                  disabled={loading || !spreadsheetInput.trim() || !blockId || !sheetName.trim()}
                >
                  {loading && !preview ? 'Previewing…' : 'Preview Import'}
                </button>
              </div>
            </div>
          </div>

          {/* Step 2 — Preview results */}
          {preview && (
            <div className="imp-card">
              <div className="imp-card-title">Step 2 — Review & Apply</div>

              <div className="imp-summary">
                <span className="imp-summary-chip">
                  <span className="imp-chip-count">{preview.matched_requests.length}</span>
                  shift assignment{preview.matched_requests.length !== 1 ? 's' : ''} matched
                </span>
                <span className="imp-summary-chip">
                  <span className="imp-chip-count">{preview.matched_unavail.length}</span>
                  unavailability record{preview.matched_unavail.length !== 1 ? 's' : ''} matched
                </span>
              </div>

              {preview.unmatched_staff.length > 0 && (
                <div className="imp-warning">
                  <div className="imp-warning-title">
                    {preview.unmatched_staff.length} staff name{preview.unmatched_staff.length !== 1 ? 's' : ''} could not be matched
                  </div>
                  <ul className="imp-warning-list">
                    {preview.unmatched_staff.map((n, i) => <li key={i}>{n}</li>)}
                  </ul>
                </div>
              )}

              {preview.unmatched_skills.length > 0 && (
                <div className="imp-warning">
                  <div className="imp-warning-title">
                    {preview.unmatched_skills.length} skill code{preview.unmatched_skills.length !== 1 ? 's' : ''} could not be matched
                  </div>
                  <ul className="imp-warning-list">
                    {preview.unmatched_skills.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}

              <div className="imp-actions">
                <button
                  className="imp-btn-primary"
                  onClick={handleApply}
                  disabled={loading || (preview.matched_requests.length === 0 && preview.matched_unavail.length === 0)}
                >
                  {loading ? 'Applying…' : 'Apply Import'}
                </button>
                <button className="imp-btn-ghost" onClick={() => setPreview(null)}>
                  Back
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
