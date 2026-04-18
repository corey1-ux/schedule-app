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

function ShiftSummaryPanel({ requests, unavail, staff, block, fteTiers, onClose }) {
  const lookupFteTier = (fte) => {
    const sorted = [...fteTiers].sort((a, b) => b.fte - a.fte);
    for (const t of sorted) if (Math.abs(t.fte - fte) < 0.001) return t;
    for (const t of sorted) if (t.fte <= fte) return t;
    return sorted[sorted.length - 1] || { shifts_per_week: 3, shifts_per_pp: 5 };
  };
  if (!block) return null;

  const allDates = [];
  let d = new Date(block.start_date + 'T00:00:00');
  const end = new Date(block.end_date + 'T00:00:00');
  while (d <= end) {
    allDates.push(d.toISOString().slice(0, 10));
    d.setDate(d.getDate() + 1);
  }

  const blockStartDate = new Date(block.start_date + 'T00:00:00');
  const dayOfWeek = blockStartDate.getDay();
  const firstSunday = new Date(blockStartDate);
  firstSunday.setDate(firstSunday.getDate() - dayOfWeek);

  const weeks = [];
  let wkStart = new Date(firstSunday);
  while (wkStart <= end) {
    const wkEnd = new Date(wkStart);
    wkEnd.setDate(wkEnd.getDate() + 6);
    const wkDates = allDates.filter(dt => {
      const dtDate = new Date(dt + 'T00:00:00');
      return dtDate >= wkStart && dtDate <= wkEnd;
    });
    if (wkDates.length > 0) weeks.push(wkDates);
    wkStart.setDate(wkStart.getDate() + 7);
  }

  const payPeriods = [];
  const blockStartD = new Date(block.start_date + 'T00:00:00');
  const daysToSun   = blockStartD.getDay();
  const ppAnchor    = new Date(blockStartD);
  ppAnchor.setDate(ppAnchor.getDate() - daysToSun);
  let ps = new Date(ppAnchor);
  while (ps <= end) {
    const pe = new Date(ps);
    pe.setDate(pe.getDate() + 13);
    payPeriods.push({
      start: ps.toISOString().slice(0, 10),
      end:   pe.toISOString().slice(0, 10),
    });
    ps = new Date(pe);
    ps.setDate(ps.getDate() + 1);
  }

  const fteTarget = (fte) => lookupFteTier(fte).shifts_per_pp;
  const weeklyMax = (fte) => lookupFteTier(fte).shifts_per_week;

  const workedDates = {};
  staff.forEach(s => { workedDates[s.id] = new Set(); });
  Object.entries(requests).forEach(([key, entries]) => {
    const date = key.split('|')[0];
    entries.forEach(e => {
      if (workedDates[e.staff_id]) workedDates[e.staff_id].add(date);
    });
  });

  const unavailDates = {};
  staff.forEach(s => { unavailDates[s.id] = new Set(); });
  Object.entries(unavail).forEach(([date, entries]) => {
    entries.forEach(e => {
      if (unavailDates[e.staff_id]) unavailDates[e.staff_id].add(date);
    });
  });

  const weeklyShifts = {};
  staff.forEach(s => {
    weeklyShifts[s.id] = weeks.map(wk => {
      const weekdays = wk.filter(dt => {
        const day = new Date(dt + 'T00:00:00').getDay();
        return day >= 1 && day <= 5;
      });
      return weekdays.filter(dt => workedDates[s.id].has(dt)).length;
    });
  });

  const ppTotals = {};
  staff.forEach(s => {
    ppTotals[s.id] = payPeriods.map(pp => {
      let shifts = 0, unavailCount = 0;
      allDates.forEach(dt => {
        if (dt < pp.start || dt > pp.end) return;
        const day = new Date(dt + 'T00:00:00').getDay();
        if (day < 1 || day > 5) return;
        if (workedDates[s.id].has(dt))    shifts++;
        if (unavailDates[s.id].has(dt))   unavailCount++;
      });
      return { shifts, unavailCount, total: shifts + unavailCount };
    });
  });

  const getWeekColor = (count, fte) => {
    if (count === 0) return '#f8fafc';
    const max = weeklyMax(fte);
    if (count > max)   return '#fee2e2';
    if (count === max) return '#f0fdf4';
    return '#fffbeb';
  };

  const getPPColor = (total, fte) => {
    const target = fteTarget(fte);
    if (total === target) return '#f0fdf4';
    if (total > target)   return '#fee2e2';
    return '#fffbeb';
  };

  return (
    <div className="shift-summary">
      <div className="shift-summary-header">
        <h3>Shifts Per Staff Per Week</h3>
        <div className="shift-summary-legend">
          <span className="ss-legend-item" style={{background:'#f0fdf4'}}>on target</span>
          <span className="ss-legend-item" style={{background:'#fffbeb'}}>under</span>
          <span className="ss-legend-item" style={{background:'#fee2e2'}}>over</span>
        </div>
        <button className="preview-close" onClick={onClose}>×</button>
      </div>

      <div className="shift-summary-scroll">
        <table className="ss-table">
          <thead>
            <tr>
              <th className="ss-name-col">Staff</th>
              <th className="ss-fte-col">FTE</th>
              {weeks.map((wk, wi) => (
                <th key={wi} className="ss-week-col">
                  Wk {wi + 1}
                  <div className="ss-week-date">
                    {new Date(wk[0] + 'T00:00:00').toLocaleDateString('en-US', {month:'numeric', day:'numeric'})}
                  </div>
                </th>
              ))}
              {payPeriods.map((pp, pi) => (
                <th key={pi} className="ss-pp-col">
                  PP {pi + 1}
                  <div className="ss-week-date">
                    {new Date(pp.start + 'T00:00:00').toLocaleDateString('en-US', {month:'numeric', day:'numeric'})}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {staff.map(s => (
              <tr key={s.id}>
                <td className="ss-name-col">{s.name}</td>
                <td className="ss-fte-col">{s.fte}</td>
                {weeklyShifts[s.id].map((count, wi) => (
                  <td key={wi} className="ss-cell"
                    style={{ background: getWeekColor(count, s.fte) }}>
                    {count}
                  </td>
                ))}
                {ppTotals[s.id].map((pp, pi) => (
                  <td key={pi} className="ss-cell"
                    style={{ background: getPPColor(pp.total, s.fte),
                             fontWeight: 700 }}>
                    {pp.shifts}{pp.unavailCount > 0 ? `+${pp.unavailCount}` : ''}
                  </td>
                ))}
              </tr>
            ))}
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
  const [shiftSummary, setShiftSummary] = useState(null);
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

  const numPayPeriods = useMemo(() => {
    if (!block) return 4;
    const start = new Date(block.start_date + 'T00:00:00');
    const end   = new Date(block.end_date   + 'T00:00:00');
    const anchor = new Date(start);
    anchor.setDate(anchor.getDate() - start.getDay());
    let count = 0, ps = new Date(anchor);
    while (ps <= end) { count++; ps.setDate(ps.getDate() + 14); }
    return count;
  }, [block]);

  const maxShifts = useCallback((fte) =>
    lookupFteTier(fte).shifts_per_pp * numPayPeriods
  , [lookupFteTier, numPayPeriods]);

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

                        const statusClass = count === 0    ? 'cell-empty'
                                          : count < target  ? 'cell-under'
                                          : count === target ? 'cell-met'
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

      {/* Shift summary — shown after optimizer runs */}
      {shiftSummary && (
        <ShiftSummaryPanel
          requests={requests}
          unavail={unavail}
          staff={sortedStaff}
          block={block}
          fteTiers={fteTiers}
          onClose={() => setShiftSummary(null)}
        />
      )}
      </div>
    </div>
  );
}
