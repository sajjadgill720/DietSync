import React, { useState, useRef, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';
const WS_BASE = import.meta.env.VITE_WS_BASE || 'ws://127.0.0.1:8000';

/**
 * Drug Resolver / Autocomplete Component
 * Synchronously queries POST /resolve.
 * Handles:
 * - 'resolved': selects the drug
 * - 'ambiguous': renders disambiguation candidate list with display names only
 * - 'not_found': displays error message
 *
 * CRITICAL SAFETY & BRAND PRIVACY CONSTRAINT:
 * Display names only. No DRAP registration numbers or DRAP field names anywhere in UI.
 */
function DrugResolver({ label, selectedDrug, onSelect, onClear }) {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [candidates, setCandidates] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleResolve = async (searchQuery) => {
    const q = (searchQuery || query).trim();
    if (!q) return;

    setLoading(true);
    setNotFound(false);
    setErrorMsg(null);
    setCandidates(null);

    try {
      const resp = await fetch(`${API_BASE}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      });

      if (!resp.ok) {
        throw new Error(`Resolution error (${resp.status})`);
      }

      const data = await resp.json();

      if (data.status === 'resolved' && data.drug) {
        onSelect(data.drug);
        setCandidates(null);
      } else if (data.status === 'ambiguous' && data.candidates) {
        setCandidates(data.candidates);
      } else {
        setNotFound(true);
      }
    } catch (err) {
      setErrorMsg(err.message || 'Failed to resolve drug');
    } finally {
      setLoading(false);
    }
  };

  const handleCandidateClick = (candidate) => {
    if (candidate.drug_id) {
      onSelect(candidate);
      setCandidates(null);
    } else {
      // Candidate not yet persisted; resolve this exact product name
      handleResolve(candidate.display_name);
    }
  };

  if (selectedDrug) {
    return (
      <div className="field-group">
        <label>{label}</label>
        <div className="selected-badge">
          <div>
            <strong>{selectedDrug.display_name}</strong>
            <span style={{ fontSize: '0.85rem', color: '#15803d', marginLeft: '8px' }}>
              (ID: {selectedDrug.drug_id}
              {selectedDrug.dosage_form ? ` • ${selectedDrug.dosage_form}` : ''})
            </span>
          </div>
          <button
            type="button"
            className="btn-secondary btn-small"
            onClick={() => {
              onClear();
              setQuery('');
              setCandidates(null);
            }}
          >
            Change
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="field-group">
      <label>{label}</label>
      <div className="input-row">
        <input
          type="text"
          placeholder="e.g. Panadol, Brufen, Disprin, Warfarin..."
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setNotFound(false);
            setErrorMsg(null);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              handleResolve();
            }
          }}
        />
        <button
          type="button"
          className="btn-primary"
          disabled={loading || !query.trim()}
          onClick={() => handleResolve()}
        >
          {loading ? 'Resolving...' : 'Resolve'}
        </button>
      </div>

      {loading && <div className="status-msg status-loading"><span className="spinner"></span> Resolving active entities...</div>}
      {notFound && <div className="status-msg status-error">Drug not found. Please verify spelling.</div>}
      {errorMsg && <div className="status-msg status-error">{errorMsg}</div>}

      {/* Disambiguation Picker: Display Names Only */}
      {candidates && candidates.length > 0 && (
        <div className="candidate-picker">
          <div className="candidate-picker-title">
            Multiple formulations found. Please select a specific product:
          </div>
          <div className="candidate-list">
            {candidates.map((cand, idx) => (
              <div
                key={idx}
                className="candidate-item"
                onClick={() => handleCandidateClick(cand)}
              >
                <span>{cand.display_name}</span>
                {cand.dosage_form && <span className="badge-form">{cand.dosage_form}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Result Panel Component
 * Renders the 3 distinct clinical/safety outcomes:
 * 1. interaction_found (Real finding with quoted label citation)
 * 2. none_found (Explicit negative finding from openFDA label)
 * 3. unverifiable (Safety refusal — refusal to speculate when ungrounded)
 * 4. failed (Pipeline error)
 */
function ResultPanel({ jobStatus, result, errorMessage, drugA, drugB }) {
  if (!jobStatus) return null;

  if (jobStatus === 'queued' || jobStatus === 'processing') {
    return (
      <div className="card result-container">
        <div className="progress-banner">
          <span className="spinner"></span>
          <strong>Interaction Check in Progress:</strong>{' '}
          {jobStatus === 'queued' ? 'Job queued in RabbitMQ...' : 'LangGraph agent evaluating manufacturer labels...'}
        </div>
      </div>
    );
  }

  if (jobStatus === 'failed' || (!result && errorMessage)) {
    return (
      <div className="card result-container">
        <div className="result-panel panel-failed">
          <div className="panel-header-danger">
            <span>❌ Check Failed</span>
          </div>
          <div className="panel-body">
            {errorMessage || 'An error occurred during evaluation. Please try again.'}
          </div>
        </div>
      </div>
    );
  }

  const {
    final_status,
    summary,
    citation_text,
    source,
    allergy_flags,
    food_interaction_summary,
  } = result || {};

  return (
    <div className="card result-container">
      <h3>
        Interaction Audit: {drugA?.display_name} + {drugB?.display_name}
      </h3>

      {/* CASE 1: REAL FINDING (interaction_found) */}
      {final_status === 'interaction_found' && (
        <div className="result-panel panel-interaction-found">
          <div className="panel-header-danger">
            <span>⚠️ Clinical Drug-Drug Interaction Identified</span>
          </div>
          <div className="panel-body">
            <strong>Clinical Mechanism:</strong>
            <p style={{ marginTop: '4px' }}>{summary}</p>

            {citation_text && (
              <div className="citation-box">
                <div className="citation-label">Official Label Verbatim Citation:</div>
                &ldquo;{citation_text}&rdquo;
              </div>
            )}

            {food_interaction_summary && (
              <div className="flags-box">
                <strong>Dietary / Food Factor:</strong> {food_interaction_summary}
              </div>
            )}

            {allergy_flags && allergy_flags.length > 0 && (
              <div className="flags-box">
                <strong>Allergy Warning:</strong>
                <ul style={{ paddingLeft: '20px', marginTop: '4px' }}>
                  {allergy_flags.map((flag, i) => (
                    <li key={i}>
                      {flag.matched_drug || flag.matched_class || JSON.stringify(flag)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="meta-row">
              <span>Verified Source:</span>
              <span className="meta-tag-source">{source || 'openFDA'}</span>
              <span className="meta-tag">Groundedness Audit: Passed</span>
            </div>
          </div>
        </div>
      )}

      {/* CASE 2: EXPLICIT NEGATIVE (none_found) */}
      {final_status === 'none_found' && (
        <div className="result-panel panel-none-found">
          <div className="panel-header-info">
            <span>ℹ️ No Interaction Found in Available Sources</span>
          </div>
          <div className="panel-body">
            <p>
              {summary ||
                `No drug-drug interaction was documented between ${drugA?.display_name} and ${drugB?.display_name} in their official manufacturer label text.`}
            </p>

            <div className="safety-note">
              <strong>Clinical Scope Notice:</strong> This negative finding confirms that no interaction
              was reported in the retrieved openFDA manufacturer label text. It does not guarantee total
              physiological independence under all patient-specific variables.
            </div>

            {food_interaction_summary && (
              <div className="flags-box">
                <strong>Dietary / Food Factor:</strong> {food_interaction_summary}
              </div>
            )}

            <div className="meta-row">
              <span>Evaluated Source:</span>
              <span className="meta-tag-source">{source || 'openFDA'}</span>
              <span className="meta-tag">Status: Verified Negative</span>
            </div>
          </div>
        </div>
      )}

      {/* CASE 3: SAFETY REFUSAL (unverifiable) */}
      {final_status === 'unverifiable' && (
        <div className="result-panel panel-unverifiable">
          <div className="panel-header-purple">
            <span>🛑 Unverifiable / Safety Refusal (Refusal to Speculate)</span>
          </div>
          <div className="panel-body">
            <p>
              {summary ||
                'Interaction claim could not be verified against the official manufacturer label text.'}
            </p>

            <div className="safety-note">
              <strong>DietSync Safety Philosophy:</strong> Refusal is a valid and preferred clinical outcome.
              The interaction check candidate failed the independent groundedness audit (the claim could not be
              entailed by an exact verbatim sentence in retrieved sources). Rather than hallucinating or speculating
              from general LLM knowledge, the system strictly halts and reports unverifiable.
            </div>

            <div className="meta-row">
              <span>Authority:</span>
              <span className="meta-tag-source">{source || 'openFDA'}</span>
              <span className="meta-tag" style={{ background: '#f3e8ff', color: '#6b21a8' }}>
                Safety Gate: Refusal Triggered
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Main DietSync Frontend Application
 */
export default function App() {
  const [drugA, setDrugA] = useState(null);
  const [drugB, setDrugB] = useState(null);
  const [allergiesInput, setAllergiesInput] = useState('');
  const [dietInput, setDietInput] = useState('');

  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [isChecking, setIsChecking] = useState(false);

  const wsRef = useRef(null);
  const pollIntervalRef = useRef(null);

  // Clean up WebSocket and polling interval on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const handleJobUpdate = (data) => {
    if (!data) return;
    if (data.status) setJobStatus(data.status);
    if (data.result) setResult(data.result);
    if (data.error_message || data.error) setErrorMessage(data.error_message || data.error);

    if (data.status === 'done' || data.status === 'failed') {
      setIsChecking(false);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }
  };

  const startPollingFallback = (id) => {
    if (pollIntervalRef.current) return;

    pollIntervalRef.current = setInterval(async () => {
      try {
        const resp = await fetch(`${API_BASE}/check/${id}`);
        if (!resp.ok) return;
        const data = await resp.json();
        handleJobUpdate(data);
      } catch (e) {
        console.warn('Polling error:', e);
      }
    }, 1500);
  };

  const handleCheckInteraction = async () => {
    if (!drugA?.drug_id || !drugB?.drug_id) return;

    setIsChecking(true);
    setJobStatus('queued');
    setResult(null);
    setErrorMessage(null);

    const allergies = allergiesInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const dietFactors = dietInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    try {
      // 1. POST /check to enqueue job
      const resp = await fetch(`${API_BASE}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          drug_a_id: drugA.drug_id,
          drug_b_id: drugB.drug_id,
          patient_allergies: allergies.length ? allergies : null,
          patient_diet_factors: dietFactors.length ? dietFactors : null,
        }),
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `Server error (${resp.status})`);
      }

      const data = await resp.json();
      const newJobId = data.job_id;
      setJobId(newJobId);
      setJobStatus('queued');

      // 2. Open WebSocket for real-time Postgres LISTEN/NOTIFY push
      const wsUrl = `${WS_BASE}/ws/jobs/${newJobId}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (evt) => {
        try {
          const update = JSON.parse(evt.data);
          handleJobUpdate(update);
        } catch (err) {
          console.error('Error parsing WS message:', err);
        }
      };

      ws.onerror = (err) => {
        console.warn('WebSocket error, switching to polling fallback:', err);
        startPollingFallback(newJobId);
      };

      ws.onclose = () => {
        // If socket closes before final status, continue with polling fallback
        if (jobStatus !== 'done' && jobStatus !== 'failed') {
          startPollingFallback(newJobId);
        }
      };

      // Also set a safety timer to start polling if WS doesn't reply in 4 seconds
      setTimeout(() => {
        if (!result && jobStatus !== 'done' && jobStatus !== 'failed') {
          startPollingFallback(newJobId);
        }
      }, 4000);
    } catch (err) {
      setIsChecking(false);
      setJobStatus('failed');
      setErrorMessage(err.message || 'Failed to submit interaction check');
    }
  };

  const canCheck = Boolean(drugA?.drug_id && drugB?.drug_id && !isChecking);

  return (
    <div className="container">
      <header>
        <h1>DietSync</h1>
        <div className="subtitle">
          AI-Assisted Clinical Interaction Checker with Strict Groundedness Enforcement
        </div>
      </header>

      {/* Drug Selection Section */}
      <div className="card">
        <div className="grid-two-col">
          <DrugResolver
            label="Primary Medication (Drug A)"
            selectedDrug={drugA}
            onSelect={setDrugA}
            onClear={() => setDrugA(null)}
          />
          <DrugResolver
            label="Secondary Medication (Drug B)"
            selectedDrug={drugB}
            onSelect={setDrugB}
            onClear={() => setDrugB(null)}
          />
        </div>

        {/* Optional Ephemeral Clinical Inputs */}
        <div className="optional-section">
          <div className="optional-section-title">
            Optional Patient Factors (Ephemeral — Never Persisted)
          </div>
          <div className="grid-two-col">
            <div>
              <label style={{ fontSize: '0.8rem' }}>Reported Patient Allergies</label>
              <input
                type="text"
                placeholder="e.g. penicillin, aspirin, sulfa (comma-separated)"
                value={allergiesInput}
                onChange={(e) => setAllergiesInput(e.target.value)}
              />
            </div>
            <div>
              <label style={{ fontSize: '0.8rem' }}>Dietary Habits / Supplements</label>
              <input
                type="text"
                placeholder="e.g. grapefruit juice, alcohol (comma-separated)"
                value={dietInput}
                onChange={(e) => setDietInput(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* Action Button */}
        <button
          type="button"
          className="btn-primary btn-action"
          disabled={!canCheck}
          onClick={handleCheckInteraction}
        >
          {isChecking ? 'Checking Interactions...' : 'Check Interaction'}
        </button>
      </div>

      {/* Differentiated Results Panel */}
      <ResultPanel
        jobStatus={jobStatus}
        result={result}
        errorMessage={errorMessage}
        drugA={drugA}
        drugB={drugB}
      />
    </div>
  );
}
