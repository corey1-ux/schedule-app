import React, { useState } from 'react';

const STATUS_COLORS = {
  pass: { bg: '#f0fdf4', border: '#86efac', text: '#166534', label: 'PASS' },
  fail: { bg: '#fef2f2', border: '#fca5a5', text: '#991b1b', label: 'FAIL' },
  warn: { bg: '#fffbeb', border: '#fcd34d', text: '#92400e', label: 'WARN' },
  info: { bg: '#f0f9ff', border: '#7dd3fc', text: '#075985', label: 'INFO' },
};

export default function TestRunner() {
  const [running, setRunning]   = useState(false);
  const [results, setResults]   = useState(null);
  const [showRaw, setShowRaw]   = useState(false);
  const [error, setError]       = useState(null);

  const runTests = () => {
    setRunning(true);
    setResults(null);
    setError(null);
    fetch('/api/run_tests', { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        setRunning(false);
        if (data.error) {
          setError(data.error);
        } else {
          setResults(data);
        }
      })
      .catch(err => {
        setRunning(false);
        setError('Failed to run tests: ' + err.message);
      });
  };

  return (
    <div style={{ padding: '1.5rem', fontFamily: '-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.3rem', fontWeight: 700, color: '#0f172a', margin: 0 }}>
          Optimizer Test Suite
        </h2>
        <button
          onClick={runTests}
          disabled={running}
          style={{
            padding: '0.5rem 1.25rem',
            background: running ? '#93c5fd' : '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: 7,
            fontWeight: 700,
            fontSize: '0.85rem',
            cursor: running ? 'not-allowed' : 'pointer',
          }}
        >
          {running ? 'Running tests...' : 'Run Tests'}
        </button>
        {results && (
          <button
            onClick={() => setShowRaw(!showRaw)}
            style={{
              padding: '0.4rem 1rem',
              background: '#f1f5f9',
              border: '1px solid #e2e8f0',
              borderRadius: 6,
              fontSize: '0.78rem',
              cursor: 'pointer',
            }}
          >
            {showRaw ? 'Hide Raw' : 'Show Raw Output'}
          </button>
        )}
      </div>

      {running && (
        <div style={{
          background: '#f0f9ff', border: '1px solid #7dd3fc',
          borderRadius: 8, padding: '1rem 1.25rem', marginBottom: '1rem',
          color: '#075985', fontSize: '0.85rem'
        }}>
          Running adversarial tests — this may take 3–5 minutes while the optimizer
          solves multiple scenarios. Please wait...
        </div>
      )}

      {error && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fca5a5',
          borderRadius: 8, padding: '1rem 1.25rem', color: '#991b1b',
          fontSize: '0.85rem'
        }}>
          Error: {error}
        </div>
      )}

      {results && (
        <>
          {/* Summary bar */}
          <div style={{
            display: 'flex', gap: '1rem', marginBottom: '1.25rem',
            padding: '0.75rem 1rem', background: '#1e293b',
            borderRadius: 8, flexWrap: 'wrap'
          }}>
            <SummaryPill label="Passed" count={results.passed} color="#10b981" />
            <SummaryPill label="Failed" count={results.failed} color="#ef4444" />
            <SummaryPill label="Warnings" count={results.warned} color="#f59e0b" />
            <div style={{ marginLeft: 'auto', color: '#94a3b8', fontSize: '0.78rem', alignSelf: 'center' }}>
              {results.passed + results.failed} checks total
            </div>
          </div>

          {/* Test sections */}
          {results.tests.map((section, si) => {
            const hasFail = section.checks.some(c => c.status === 'fail');
            const hasWarn = section.checks.some(c => c.status === 'warn');
            const allPass = section.checks.length > 0 && !hasFail && !hasWarn;
            return (
              <div key={si} style={{
                border: `1px solid ${hasFail ? '#fca5a5' : hasWarn ? '#fcd34d' : '#e2e8f0'}`,
                borderRadius: 8,
                marginBottom: '0.6rem',
                overflow: 'hidden',
              }}>
                <div style={{
                  background: hasFail ? '#fef2f2' : hasWarn ? '#fffbeb' : '#f8fafc',
                  padding: '0.6rem 0.9rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.75rem',
                }}>
                  <span style={{
                    fontSize: '0.7rem', fontWeight: 700, padding: '2px 7px',
                    borderRadius: 4,
                    background: hasFail ? '#fee2e2' : hasWarn ? '#fef3c7' : '#d1fae5',
                    color: hasFail ? '#991b1b' : hasWarn ? '#92400e' : '#065f46',
                  }}>
                    {hasFail ? 'FAIL' : hasWarn ? 'WARN' : allPass ? 'PASS' : '—'}
                  </span>
                  <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#1e293b' }}>
                    {section.section}
                  </span>
                </div>
                {section.checks.length > 0 && (
                  <div style={{ padding: '0.4rem 0.9rem 0.6rem' }}>
                    {section.checks.map((check, ci) => {
                      const s = STATUS_COLORS[check.status] || STATUS_COLORS.info;
                      return (
                        <div key={ci} style={{
                          display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
                          padding: '3px 0', fontSize: '0.78rem',
                        }}>
                          <span style={{
                            flexShrink: 0, padding: '1px 5px', borderRadius: 3,
                            background: s.bg, border: `1px solid ${s.border}`,
                            color: s.text, fontSize: '0.65rem', fontWeight: 700,
                          }}>
                            {s.label}
                          </span>
                          <span style={{ color: '#374151', lineHeight: 1.5 }}>{check.text}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

          {/* Raw output */}
          {showRaw && (
            <div style={{ marginTop: '1rem' }}>
              <h4 style={{ fontSize: '0.85rem', color: '#475569', marginBottom: '0.5rem' }}>
                Raw Output
              </h4>
              <pre style={{
                background: '#0f172a', color: '#e2e8f0',
                padding: '1rem', borderRadius: 8,
                fontSize: '0.72rem', overflowX: 'auto',
                whiteSpace: 'pre-wrap', lineHeight: 1.6,
                maxHeight: 400, overflowY: 'auto',
              }}>
                {results.raw}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SummaryPill({ label, count, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <span style={{
        width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0
      }} />
      <span style={{ color: '#e2e8f0', fontSize: '0.82rem', fontWeight: 600 }}>
        {count} {label}
      </span>
    </div>
  );
}