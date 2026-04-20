import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import './BlockGrid.css';

const DAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

function getDates(startDate, endDate) {
  const dates = [];
  let d = new Date(startDate + 'T00:00:00');
  const end = new Date(endDate + 'T00:00:00');
  while (d <= end) {
    dates.push(d.toISOString().slice(0, 10));
    d.setDate(d.getDate() + 1);
  }
  return dates;
}

function getDayName(dateStr) {
  return DAYS[new Date(dateStr + 'T00:00:00').getDay()];
}

function isWeekend(dateStr) {
  const day = new Date(dateStr + 'T00:00:00').getDay();
  return day === 0 || day === 6;
}

function getMonthLabel(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleString('default', { month: 'short', year: 'numeric' });
}

function SkillCoveragePanel({ requests, block, skills, needs, onClose }) {
  if (!block) return null;

  const weekdayDates = getDates(block.start_date, block.end_date).filter(d => !isWeekend(d));

  // Group Mon–Fri into calendar weeks
  const weeks = [];
  let wk = [];
  weekdayDates.forEach(d => {
    wk.push(d);
    if (getDayName(d) === 'Friday') { weeks.push(wk); wk = []; }
  });
  if (wk.length) weeks.push(wk);

  const coverageSkills = skills.filter(s => s.name !== 'Call');

  return (
    <div className="skill-coverage">
      <div className="skill-coverage-header">
        <h3>Skill Coverage by Day</h3>
        <div className="skill-coverage-legend">
          <span className="sc-legend-item" style={{background:'#f0fdf4'}}>met</span>
          <span className="sc-legend-item" style={{background:'#fee2e2'}}>below minimum</span>
        </div>
        <button className="preview-close" onClick={onClose}>×</button>
      </div>

      <div className="skill-coverage-scroll">
        <table className="sc-table">
          <thead>
            <tr className="sc-week-row">
              <th className="sc-skill-col" />
              {weeks.map((w, wi) => (
                <th key={wi} colSpan={w.length} className="sc-week-label">
                  Week {wi + 1} &nbsp;·&nbsp; {getMonthLabel(w[0])}
                </th>
              ))}
            </tr>
            <tr>
              <th className="sc-skill-col">Skill</th>
              {weekdayDates.map(d => (
                <th key={d} className="sc-date-col">
                  <div>{getDayName(d).slice(0, 3)}</div>
                  <div>{new Date(d + 'T00:00:00').getDate()}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {coverageSkills.map(skill => (
              <tr key={skill.id}>
                <td className="sc-skill-label">{skill.name}</td>
                {weekdayDates.map(d => {
                  const count  = (requests[`${d}|${skill.id}`] || []).length;
                  const target = needs[getDayName(d)]?.[skill.id]?.quantity || 0;
                  const bg = target === 0 ? '#fafafa'
                           : count < target ? '#fee2e2'
                           : '#f0fdf4';
                  return (
                    <td key={d} className="sc-cell" style={{ background: bg }}>
                      {target > 0 ? `${count}/${target}` : (count > 0 ? count : '')}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RotationPanel({ rotationPoints, onClose }) {
  if (!rotationPoints.length) return (
    <div className="skill-coverage">
      <div className="skill-coverage-header">
        <h3>Rotation Points</h3>
        <button className="preview-close" onClick={onClose}>×</button>
      </div>
      <p style={{ padding: '1rem', color: '#71717a' }}>No rotation data yet. Run the optimizer first.</p>
    </div>
  );

  const maxTotal = Math.max(...rotationPoints.map(r => r.ecu_total + r.irc_total + r.ir_late_total));
  const minTotal = Math.min(...rotationPoints.map(r => r.ecu_total + r.irc_total + r.ir_late_total));

  return (
    <div className="skill-coverage">
      <div className="skill-coverage-header">
        <h3>Rotation Points</h3>
        <div className="skill-coverage-legend">
          <span className="sc-legend-item" style={{ background: '#f0fdf4' }}>balanced</span>
          <span className="sc-legend-item" style={{ background: '#fef9c3' }}>above average</span>
        </div>
        <button className="preview-close" onClick={onClose}>×</button>
      </div>
      <div className="skill-coverage-scroll">
        <table className="sc-table">
          <thead>
            <tr>
              <th className="sc-skill-col" rowSpan={2} style={{ verticalAlign: 'bottom' }}>Staff</th>
              <th colSpan={2} style={{ textAlign: 'center', borderBottom: '1px solid #e4e4e7' }}>ECU</th>
              <th colSpan={2} style={{ textAlign: 'center', borderBottom: '1px solid #e4e4e7' }}>IRC</th>
              <th colSpan={2} style={{ textAlign: 'center', borderBottom: '1px solid #e4e4e7' }}>IR Late</th>
            </tr>
            <tr>
              <th style={{ textAlign: 'center', fontSize: '0.7rem' }}>Block</th>
              <th style={{ textAlign: 'center', fontSize: '0.7rem' }}>Total</th>
              <th style={{ textAlign: 'center', fontSize: '0.7rem' }}>Block</th>
              <th style={{ textAlign: 'center', fontSize: '0.7rem' }}>Total</th>
              <th style={{ textAlign: 'center', fontSize: '0.7rem' }}>Block</th>
              <th style={{ textAlign: 'center', fontSize: '0.7rem' }}>Total</th>
            </tr>
          </thead>
          <tbody>
            {rotationPoints.map(row => {
              const total    = row.ecu_total + row.irc_total + row.ir_late_total;
              const aboveAvg = maxTotal > minTotal && total > minTotal;
              const bg       = aboveAvg ? '#fef9c3' : '#f0fdf4';
              return (
                <tr key={row.id}>
                  <td className="sc-skill-label">{row.name}</td>
                  <td className="sc-cell" style={{ textAlign: 'center' }}>{row.ecu_current}</td>
                  <td className="sc-cell" style={{ textAlign: 'center', fontWeight: 600, background: bg }}>{row.ecu_total}</td>
                  <td className="sc-cell" style={{ textAlign: 'center' }}>{row.irc_current}</td>
                  <td className="sc-cell" style={{ textAlign: 'center', fontWeight: 600, background: bg }}>{row.irc_total}</td>
                  <td className="sc-cell" style={{ textAlign: 'center' }}>{row.ir_late_current}</td>
                  <td className="sc-cell" style={{ textAlign: 'center', fontWeight: 600, background: bg }}>{row.ir_late_total}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function BlockGrid({ blockId: propBlockId, readOnly = false }) {
  const { id: paramId } = useParams();
  const id = propBlockId || paramId;

  const [block, setBlock]           = useState(null);
  const [staff, setStaff]           = useState([]);
  const [skills, setSkills]         = useState([]);
  const [needs, setNeeds]           = useState({});
  const [requests, setRequests]     = useState({});
  const [unavail, setUnavail]       = useState({});
  const [selected, setSelected]     = useState(null);
  const [mode, setMode]             = useState(null); // null | 'assign' | 'delete'
  const [loading, setLoading]       = useState(true);
  const [toasts, setToasts]         = useState([]);
  const [saving, setSaving]         = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [shiftSummary, setShiftSummary]   = useState(null);
  const [rotationPanel, setRotationPanel] = useState(false);
  const [rotationPoints, setRotationPoints] = useState([]);
  const [fteTiers, setFteTiers]         = useState([]);
  const [publishHistory, setHistory]    = useState([]);
  const [showAudit, setShowAudit]       = useState(false);
  const [viewMode, setViewMode]         = useState('skill'); // 'skill' | 'staff'
  const [viewDropdownOpen, setViewDropdownOpen] = useState(false);
  const [fullscreen, setFullscreen]     = useState(false);
  const [dragSource, setDragSource]     = useState(null); // { staffId, staffName, date, skillId }
  const [dragOverKey, setDragOverKey]   = useState(null); // 'date|skillId'
  const viewDropdownRef = useRef(null);

  const load = useCallback(() => {
    if (!id) return;
    Promise.all([
      fetch(`/api/blocks/${id}`).then(r => r.json()),
      fetch('/api/staff').then(r => r.json()),
      fetch('/api/skills').then(r => r.json()),
      fetch('/api/template/needs').then(r => r.json()),
      fetch(`/api/blocks/${id}/requests`).then(r => r.json()),
      fetch(`/api/blocks/${id}/unavailability`).then(r => r.json()),
      fetch('/api/fte-tiers').then(r => r.json()),
      fetch(`/api/blocks/${id}/publish-history`).then(r => r.json()),
    ]).then(([blockData, staffData, skillsData, needsData, requestsData, unavailData, tiersData, historyData]) => {
      setBlock(blockData);
      setStaff(staffData);
      setSkills(skillsData);
      setNeeds(needsData);
      setFteTiers(tiersData);
      setHistory(historyData);

      const reqLookup = {};
      requestsData.forEach(r => {
        const key = `${r.date}|${r.skill_id}`;
        if (!reqLookup[key]) reqLookup[key] = [];
        reqLookup[key].push({ staff_id: r.staff_id, staff_name: r.staff_name });
      });
      setRequests(reqLookup);

      const unavailLookup = {};
      unavailData.forEach(u => {
        if (!unavailLookup[u.date]) unavailLookup[u.date] = [];
        unavailLookup[u.date].push({ staff_id: u.staff_id, staff_name: u.staff_name });
      });
      setUnavail(unavailLookup);
      setLoading(false);
    });
  }, [id]);

  useEffect(() => {
    if (id) load();
  }, [id, load]);

  useEffect(() => {
    if (!viewDropdownOpen) return;
    function handleClickOutside(e) {
      if (viewDropdownRef.current && !viewDropdownRef.current.contains(e.target)) {
        setViewDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [viewDropdownOpen]);

  const shiftCount = useCallback((staffId) => {
    let count = 0;
    Object.values(requests).forEach(entries => {
      if (entries.some(e => e.staff_id === staffId)) count++;
    });
    return count;
  }, [requests]);

  const lookupFteTier = useCallback((fte) => {
    const sorted = [...fteTiers].sort((a, b) => b.fte - a.fte);
    for (const t of sorted) if (Math.abs(t.fte - fte) < 0.001) return t;
    for (const t of sorted) if (t.fte <= fte) return t;
    return sorted[sorted.length - 1] || { shifts_per_week: 3, shifts_per_pp: 5 };
  }, [fteTiers]);

  const numWeeks = useMemo(() => {
    if (!block) return 8;
    const start = new Date(block.start_date + 'T00:00:00');
    const end   = new Date(block.end_date   + 'T00:00:00');
    // Anchor to the Monday of the start week
    const monday = new Date(start);
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    let count = 0, wk = new Date(monday);
    while (wk <= end) { count++; wk.setDate(wk.getDate() + 7); }
    return count;
  }, [block]);

  const maxShifts = useCallback((fte) =>
    lookupFteTier(fte).shifts_per_week * numWeeks
  , [lookupFteTier, numWeeks]);

  // Sorted roster: 1.0 FTE first, descending to casual at the bottom
  const sortedStaff = useMemo(() => (
    [...staff].sort((a, b) => {
      if (a.is_casual !== b.is_casual) return a.is_casual ? 1 : -1;
      return b.fte - a.fte;
    })
  ), [staff]);

  const isUnavailable = useCallback((staffId, dateStr) => {
    return (unavail[dateStr] || []).some(u => u.staff_id === staffId);
  }, [unavail]);

  const getTarget = useCallback((dateStr, skillId) => {
    const dayName = getDayName(dateStr);
    const skill   = skills.find(s => s.id === skillId);
    if (!skill) return 0;
    if (isWeekend(dateStr)) return skill.name === 'Call' ? 1 : 0;
    return needs[dayName]?.[skillId]?.quantity || 0;
  }, [skills, needs]);

  const activateMode = useCallback((next) => {
    setMode(prev => {
      if (prev === next) { setSelected(null); return null; } // toggle off
      setSelected(null);
      return next;
    });
  }, []);

  const handleCellClick = useCallback((dateStr, skillId) => {
    if (mode !== 'assign' || !selected) return;

    const key     = `${dateStr}|${skillId}`;
    const entries = requests[key] || [];
    if (entries.some(e => e.staff_id === selected.id)) return; // already assigned — no toggle in assign mode

    if (isUnavailable(selected.id, dateStr)) {
      alert(`${selected.name} is marked unavailable on ${dateStr}.`);
      return;
    }

    const skill    = skills.find(s => s.id === skillId);
    const hasSkill = skill?.name === 'Call' ||
      selected.skills.some(s => s.id === skillId);

    if (!hasSkill) {
      alert(`${selected.name} does not have the ${skill?.name} skill.`);
      return;
    }

    fetch(`/api/blocks/${id}/requests`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ staff_id: selected.id, date: dateStr, skill_id: skillId }),
    }).then(load);
  }, [mode, selected, requests, id, load, skills, isUnavailable]);

  const handleUnavailClick = useCallback((dateStr) => {
    if (mode !== 'assign' || !selected) return;
    const entries = unavail[dateStr] || [];
    const already = entries.some(u => u.staff_id === selected.id);

    if (already) {
      fetch(`/api/blocks/${id}/unavailability/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ staff_id: selected.id, date: dateStr }),
      }).then(load);
    } else {
      fetch(`/api/blocks/${id}/unavailability`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ staff_id: selected.id, date: dateStr }),
      }).then(load);
    }
  }, [mode, selected, unavail, id, load]);

  const handleRemove = useCallback((e, dateStr, skillId, staffId) => {
    e.stopPropagation();
    fetch(`/api/blocks/${id}/requests/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ staff_id: staffId, date: dateStr, skill_id: skillId }),
    }).then(load);
  }, [id, load]);

  const handleUnavailRemove = useCallback((e, dateStr, staffId) => {
    e.stopPropagation();
    fetch(`/api/blocks/${id}/unavailability/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ staff_id: staffId, date: dateStr }),
    }).then(load);
  }, [id, load]);

  const addToast = useCallback((message, type) => {
    const toastId = Date.now() + Math.random();
    setToasts(prev => [...prev, { id: toastId, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== toastId));
    }, 5000);
  }, []);

  const handleDragStart = useCallback((e, staffId, staffName, date, skillId) => {
    setDragSource({ staffId, staffName, date, skillId });
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  const handleDragEnd = useCallback(() => {
    setDragSource(null);
    setDragOverKey(null);
  }, []);

  const handleDragOver = useCallback((e, date, skillId) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverKey(`${date}|${skillId}`);
  }, []);

  const handleDragLeave = useCallback((e) => {
    if (!e.currentTarget.contains(e.relatedTarget)) setDragOverKey(null);
  }, []);

  const handleDrop = useCallback((e, targetDate, targetSkillId) => {
    e.preventDefault();
    setDragOverKey(null);
    if (!dragSource) return;

    const { staffId, staffName, date: sourceDate, skillId: sourceSkillId } = dragSource;
    if (sourceDate === targetDate && sourceSkillId === targetSkillId) return;

    const targetEntries = requests[`${targetDate}|${targetSkillId}`] || [];
    if (targetEntries.some(en => en.staff_id === staffId)) {
      addToast(`${staffName} is already assigned on ${targetDate}.`, 'error');
      return;
    }

    const targetSkill = skills.find(s => s.id === targetSkillId);
    const member = staff.find(s => s.id === staffId);
    const hasSkill = targetSkill?.name === 'Call' || member?.skills.some(s => s.id === targetSkillId);
    if (!hasSkill) {
      addToast(`${staffName} does not have the ${targetSkill?.name} skill.`, 'error');
      return;
    }

    const doMove = () =>
      fetch(`/api/blocks/${id}/requests/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ staff_id: staffId, date: sourceDate, skill_id: sourceSkillId }),
      }).then(() =>
        fetch(`/api/blocks/${id}/requests`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ staff_id: staffId, date: targetDate, skill_id: targetSkillId }),
        })
      ).then(load);

    if (isUnavailable(staffId, targetDate)) {
      if (window.confirm(`${staffName} is marked unavailable on ${targetDate}. Assign anyway?`)) doMove();
    } else {
      doMove();
    }
  }, [dragSource, requests, skills, staff, id, load, isUnavailable, addToast]);

  const handlePublish = useCallback(() => {
    const isRepub = block?.status === 'published';
    const msg = isRepub
      ? 'Re-publish this schedule? Updated assignments will be visible to staff immediately.'
      : 'Publish this schedule? It will appear on the main calendar.';
    if (!window.confirm(msg)) return;
    fetch(`/api/blocks/${id}/publish`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          addToast(`Publish error: ${data.error}`, 'error');
        } else {
          addToast(
            data.is_republish
              ? `Re-published (v${data.version}). Changes are now live.`
              : 'Block published. Schedule is now live on the calendar.',
            'success'
          );
          load();
        }
      })
      .catch(() => addToast('Error publishing block.', 'error'));
  }, [id, block, addToast, load]);

  const handleOptimize = useCallback(() => {
    if (!window.confirm('Run the optimizer? This may take up to 30 seconds.')) return;
    setOptimizing(true);
    fetch(`/api/blocks/${id}/optimize`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          setOptimizing(false);
          addToast(`Optimizer error: ${data.error}`, 'error');
          return;
        }
        fetch(`/api/blocks/${id}/accept_optimized`, { method: 'POST' })
          .then(r => r.json())
          .then(accepted => {
            setOptimizing(false);
            if (accepted.error) {
              addToast(`Error applying results: ${accepted.error}`, 'error');
            } else {
              setShiftSummary(true);
              addToast(`Optimizer applied — ${accepted.added} assignments updated.`, 'success');
              load();
              fetch(`/api/rotation-points?block_id=${id}`).then(r => r.json()).then(setRotationPoints);
            }
          });
      })
      .catch(() => {
        setOptimizing(false);
        addToast('Error running optimizer.', 'error');
      });
  }, [id, addToast, load]);

  const handleSave = useCallback(() => {
    setSaving(true);
    fetch(`/api/blocks/${id}/validate_fte`)
      .then(r => r.json())
      .then(data => {
        setSaving(false);
        if (data.warnings && data.warnings.length > 0) {
          data.warnings.forEach(w => addToast(w.message, w.type));
        } else {
          addToast('Schedule saved. All FTE checks passed.', 'success');
        }
      })
      .catch(() => {
        setSaving(false);
        addToast('Error running FTE validation.', 'error');
      });
  }, [id, addToast]);

  if (loading) return <div className="status">Loading grid...</div>;
  if (!block)  return <div className="status error">Block not found.</div>;

  const dates = getDates(block.start_date, block.end_date);
  const weeks = [];
  let week = [];
  dates.forEach(d => {
    week.push(d);
    if (getDayName(d) === 'Saturday') { weeks.push(week); week = []; }
  });
  if (week.length) weeks.push(week);

  return (
    <div className="block-grid-page">

      {/* Toasts */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            {t.message}
            <button className="toast-close" onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}>×</button>
          </div>
        ))}
      </div>

      {/* Header */}
      <div className="block-header">
        {!readOnly && (
          <Link to="/blocks" style={{ fontSize: '0.82rem', color: '#2563eb', textDecoration: 'none' }}>
            ← Blocks
          </Link>
        )}
        <h2>{block.name}</h2>
        <span className="block-dates">{block.start_date} → {block.end_date}</span>
        <span className={`badge badge-${block.status}`}>{block.status}</span>
        {!readOnly && (
          <>
            <button className="btn-save" onClick={handleSave} disabled={saving}>
              {saving ? 'Checking...' : 'Save & Validate FTE'}
            </button>
            <button className="btn-optimize" onClick={handleOptimize} disabled={optimizing}>
              {optimizing ? 'Optimizing...' : 'Run Optimizer'}
            </button>
            <button className="btn-coverage" onClick={() => setShiftSummary(v => !v)}>
              {shiftSummary ? 'Hide Coverage' : 'Coverage'}
            </button>
            <button className="btn-coverage" onClick={() => {
              if (!rotationPanel) fetch(`/api/rotation-points?block_id=${id}`).then(r => r.json()).then(setRotationPoints);
              setRotationPanel(v => !v);
            }}>
              {rotationPanel ? 'Hide Rotation' : 'Rotation'}
            </button>
            <button className="btn-publish" onClick={handlePublish}>
              {block.status === 'published' ? 'Re-publish' : 'Publish'}
            </button>
            <button
              className={`btn-mode-assign${mode === 'assign' ? ' active' : ''}`}
              onClick={() => activateMode('assign')}
            >
              Assign
            </button>
            <button
              className={`btn-mode-delete${mode === 'delete' ? ' active' : ''}`}
              onClick={() => activateMode('delete')}
            >
              Delete
            </button>
          </>
        )}
        <div className="view-dropdown-wrapper" ref={viewDropdownRef}>
          <button
            className="btn-view-toggle"
            onClick={() => setViewDropdownOpen(v => !v)}
          >
            {viewMode === 'skill' ? 'By Skill' : 'By Staff'} ▾
          </button>
          {viewDropdownOpen && (
            <div className="view-dropdown">
              <button
                className={`view-dropdown-item${viewMode === 'skill' ? ' active' : ''}`}
                onClick={() => { setViewMode('skill'); setViewDropdownOpen(false); }}
              >
                By Skill
              </button>
              <button
                className={`view-dropdown-item${viewMode === 'staff' ? ' active' : ''}`}
                onClick={() => { setViewMode('staff'); setViewDropdownOpen(false); }}
              >
                By Staff Member
              </button>
            </div>
          )}
        </div>
        {publishHistory.length > 0 && !readOnly && (
          <button
            className="btn-audit-toggle"
            onClick={() => setShowAudit(v => !v)}
            title="Publish history"
          >
            History {showAudit ? '▲' : '▼'}
          </button>
        )}
      </div>

      {/* Audit / publish history panel */}
      {showAudit && publishHistory.length > 0 && (
        <div className="audit-panel">
          <div className="audit-panel-header">
            <span>Publish History</span>
            <button className="audit-close" onClick={() => setShowAudit(false)}>×</button>
          </div>
          <div className="audit-entries">
            {publishHistory.map(entry => (
              <div key={entry.id} className="audit-entry">
                <div className="audit-entry-meta">
                  <span className="audit-version">v{entry.version}</span>
                  <span className="audit-time">
                    {new Date(entry.published_at + 'Z').toLocaleString()}
                  </span>
                  {!entry.changes && (
                    <span className="audit-label">Initial publish</span>
                  )}
                  {entry.changes && entry.changes.length === 0 && (
                    <span className="audit-label audit-label-muted">No changes from previous</span>
                  )}
                </div>
                {entry.changes && entry.changes.length > 0 && (
                  <div className="audit-changes">
                    {entry.changes.map((c, i) => (
                      <span key={i} className={`audit-chip audit-chip-${c.type}`}>
                        {c.type === 'added' ? '+' : '−'} {c.staff} · {c.skill} · {c.date}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={`grid-container${fullscreen ? ' grid-fullscreen' : ''}`}>
        <button
          className="btn-fullscreen"
          onClick={() => setFullscreen(v => !v)}
          title={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
        >
          {fullscreen ? '✕' : '⛶'}
        </button>

      <div className="grid-layout">

        {/* Roster */}
        <div className="roster">
          <h3>Staff Roster</h3>
          {mode === 'assign' && (
            <div className="roster-hint">
              {selected ? <>Assigning <strong>{selected.name}</strong> — click cells to place</> : 'Select a staff member'}
            </div>
          )}
          {mode === 'delete' && (
            <div className="roster-hint roster-hint-delete">Click any name on the grid to remove it</div>
          )}
          {sortedStaff.map(s => {
            const count = shiftCount(s.id);
            const max   = s.is_casual ? null : maxShifts(s.fte);
            const full  = max !== null && count >= max;
            return (
              <div
                key={s.id}
                className={`roster-item ${selected?.id === s.id ? 'selected' : ''} ${full ? 'at-limit' : ''} ${readOnly || mode !== 'assign' ? 'disabled' : ''}`}
                onClick={() => mode === 'assign' && setSelected(selected?.id === s.id ? null : s)}
                title={s.is_casual ? `${s.name} — Casual` : `${s.name} — ${s.fte} FTE`}
              >
                <span className="roster-name">{s.name}</span>
                <span className={`roster-count ${full ? 'at-max' : ''}`}>
                  {max !== null ? `${count}/${max}` : count}
                </span>
              </div>
            );
          })}
        </div>

        {/* Grid */}
        <div className="grid-scroll">
          <table className="schedule-grid">
            <thead>
              <tr className="week-row">
                <th className="skill-col"></th>
                {weeks.map((wk, wi) => (
                  <th key={wi} colSpan={wk.length} className="week-label">
                    Week {wi + 1} &nbsp;·&nbsp; {getMonthLabel(wk[0])}
                  </th>
                ))}
              </tr>
              <tr className="date-row">
                <th className="skill-col">{viewMode === 'staff' ? 'Staff' : 'Skill'}</th>
                {dates.map(d => (
                  <th key={d} className={`date-col ${isWeekend(d) ? 'weekend' : ''}`}>
                    <div className="date-day">{getDayName(d).slice(0, 3)}</div>
                    <div className="date-num">{new Date(d + 'T00:00:00').getDate()}</div>
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {viewMode === 'skill' ? (
                <>
                  {/* Skill rows */}
                  {skills.map(skill => (
                    <tr key={skill.id} className="skill-row">
                      <td className="skill-label">{skill.name}</td>
                      {dates.map(d => {
                        const weekend = isWeekend(d);
                        const isCall  = skill.name === 'Call';

                        if (weekend && !isCall) {
                          return <td key={d} className="cell cell-closed" />;
                        }

                        const key     = `${d}|${skill.id}`;
                        const entries = requests[key] || [];
                        const target  = getTarget(d, skill.id);
                        const count   = entries.length;

                        const statusClass = count === 0 && target > 0 ? 'cell-unmet'
                                          : count === 0              ? 'cell-empty'
                                          : count < target           ? 'cell-under'
                                          : count === target         ? 'cell-met'
                                          : 'cell-over';

                        const targetLabel = target > 0
                          ? count < target   ? 'under'
                          : count === target ? 'met'
                          : 'over'
                          : '';

                        const cellKey = `${d}|${skill.id}`;
                        const isDragOver = dragOverKey === cellKey;

                        return (
                          <td
                            key={d}
                            className={`cell ${statusClass} ${isCall && weekend ? 'cell-weekend-call' : ''} ${mode === 'assign' && selected ? 'clickable' : ''} ${isDragOver ? 'drag-over' : ''}`}
                            onClick={() => mode === 'assign' && handleCellClick(d, skill.id)}
                            onDragOver={!readOnly ? e => handleDragOver(e, d, skill.id) : undefined}
                            onDragLeave={!readOnly ? handleDragLeave : undefined}
                            onDrop={!readOnly ? e => handleDrop(e, d, skill.id) : undefined}
                          >
                            {target > 0 && (
                              <div className={`cell-target ${targetLabel}`}>{count}/{target}</div>
                            )}

                            <div className="cell-names">
                              {entries.map(e => {
                                const unavailable = isUnavailable(e.staff_id, d);
                                return (
                                  <span
                                    key={e.staff_id}
                                    className={`name-tag ${isCall ? 'call' : ''} ${unavailable ? 'name-tag-conflict' : ''} ${mode === 'delete' ? 'deletable' : ''}`}
                                    draggable={!readOnly && mode !== 'delete'}
                                    onDragStart={!readOnly && mode !== 'delete' ? ev => handleDragStart(ev, e.staff_id, e.staff_name, d, skill.id) : undefined}
                                    onDragEnd={!readOnly && mode !== 'delete' ? handleDragEnd : undefined}
                                    title={
                                      mode === 'delete' ? `Remove ${e.staff_name}` :
                                      unavailable ? `${e.staff_name} is marked unavailable!` : ''
                                    }
                                    onClick={mode === 'delete' ? ev => handleRemove(ev, d, skill.id, e.staff_id) : undefined}
                                  >
                                    {unavailable ? '⚠ ' : ''}{e.staff_name}
                                    {!readOnly && mode !== 'delete' && (
                                      <button className="remove-btn" onClick={ev => handleRemove(ev, d, skill.id, e.staff_id)}>×</button>
                                    )}
                                  </span>
                                );
                              })}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}

                  {/* Unavailability row */}
                  <tr className="skill-row unavail-row">
                    <td className="skill-label skill-label-unavail">Unavailable</td>
                    {dates.map(d => {
                      const entries = unavail[d] || [];
                      return (
                        <td
                          key={d}
                          className={`cell cell-unavail ${mode === 'assign' && selected ? 'clickable' : ''}`}
                          onClick={() => handleUnavailClick(d)}
                        >
                          <div className="cell-names">
                            {entries.map(u => (
                              <span key={u.staff_id} className="name-tag unavail-tag">
                                {u.staff_name}
                                {!readOnly && (
                                  <button className="remove-btn" onClick={ev => handleUnavailRemove(ev, d, u.staff_id)}>×</button>
                                )}
                              </span>
                            ))}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                </>
              ) : (
                <>
                  {/* Staff rows */}
                  {sortedStaff.map(s => (
                    <tr key={s.id} className="skill-row">
                      <td className="skill-label">{s.name}</td>
                      {dates.map(d => {
                        const assignedSkills = skills.filter(skill => {
                          const key = `${d}|${skill.id}`;
                          return (requests[key] || []).some(e => e.staff_id === s.id);
                        });
                        const isUnavail = isUnavailable(s.id, d);
                        const hasWork = assignedSkills.length > 0;
                        return (
                          <td
                            key={d}
                            className={`cell ${isWeekend(d) && !assignedSkills.some(sk => sk.name === 'Call') ? 'cell-closed' : hasWork ? 'cell-met' : 'cell-empty'}`}
                          >
                            <div className="cell-names">
                              {isUnavail && (
                                <span className="name-tag unavail-tag">Unavailable</span>
                              )}
                              {assignedSkills.map(skill => (
                                <span key={skill.id} className={`name-tag ${skill.name === 'Call' ? 'call' : ''}`}>
                                  {skill.name}
                                </span>
                              ))}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </>
              )}
            </tbody>
          </table>
        </div>

      </div>

      {/* Skill coverage panel */}
      {shiftSummary && (
        <SkillCoveragePanel
          requests={requests}
          block={block}
          skills={skills}
          needs={needs}
          onClose={() => setShiftSummary(null)}
        />
      )}
      {rotationPanel && (
        <RotationPanel
          rotationPoints={rotationPoints}
          onClose={() => setRotationPanel(false)}
        />
      )}
      </div>
    </div>
  );
}
