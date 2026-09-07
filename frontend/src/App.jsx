import React, { useState, useRef, useEffect } from 'react';

const RAW_API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';
const API_BASE = RAW_API_BASE.replace(/\/+$/, '');
const WS_BASE = (import.meta.env.VITE_WS_BASE || API_BASE.replace(/^http/, 'ws')).replace(/\/+$/, '');

// Curated Pakistani Brands for fast one-click resolution
const QUICK_BRANDS = [
  'Panadol',
  'Disprin',
  'Augmentin',
  'Brufen',
  'Lipitor',
  'Klaricid',
  'Norvasc',
  'Risek',
  'Warfarin',
  'Keflex',
];

// High-impact Clinical Demo Presets (Bento Grid)
const CLINICAL_PRESETS = [
  {
    id: 'anticoag_bleeding',
    title: 'Aspirin + Warfarin',
    badge: '🔴 Critical Hazard',
    drugA: 'Disprin',
    drugB: 'Warfarin',
    allergies: '',
    diet: '',
    description: 'Additive antiplatelet & prothrombin inhibition causing severe bleeding risk.',
  },
  {
    id: 'statin_macrolide_grapefruit',
    title: 'Lipitor + Klaricid + Grapefruit',
    badge: '🔴 Contraindicated + Diet',
    drugA: 'Lipitor',
    drugB: 'Klaricid',
    allergies: '',
    diet: 'grapefruit juice',
    description: 'CYP3A4 blockade elevating statin levels; rhabdomyolysis warning.',
  },
  {
    id: 'penicillin_allergy',
    title: 'Augmentin + Penicillin Allergy',
    badge: '🛑 Allergy Cross-Reactivity',
    drugA: 'Augmentin',
    drugB: 'Panadol',
    allergies: 'penicillin',
    diet: '',
    description: 'Deterministic beta-lactam class match via NIH RxClass with 0 LLM calls.',
  },
  {
    id: 'safe_coprescribe',
    title: 'Panadol + Norvasc',
    badge: '🟢 Safe Co-Prescribing',
    drugA: 'Panadol',
    drugB: 'Norvasc',
    allergies: '',
    diet: '',
    description: 'Documented safety: explicit negative finding with zero hallucinations.',
  },
  {
    id: 'nsaid_interference',
    title: 'Brufen + Disprin',
    badge: '🟠 Antiplatelet Block',
    drugA: 'Brufen',
    drugB: 'Disprin',
    allergies: '',
    diet: '',
    description: 'Competitive COX-1 interference diminishing aspirin cardioprotection.',
  },
];

// Quick click-to-add allergies and dietary factors
const QUICK_ALLERGIES = ['penicillin', 'aspirin', 'sulfa', 'codeine', 'cephalosporin'];
const QUICK_DIET = ['grapefruit juice', 'alcohol', 'smoking', 'high-potassium diet'];

/**
 * Drug Resolver Component
 * Adheres strictly to DRAP brand privacy constraint: display names only, no DRAP registration numbers.
 */
function DrugResolver({
  label,
  roleLabel,
  selectedDrug,
  onSelect,
  onClear,
  inputPlaceholder = 'e.g. Disprin, Lipitor, Panadol...',
}) {
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
        throw new Error(`Resolution service error (${resp.status})`);
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
      setErrorMsg(err.message || 'Failed to resolve drug entity');
    } finally {
      setLoading(false);
    }
  };

  const handleCandidateClick = (candidate) => {
    if (candidate.drug_id) {
      onSelect(candidate);
      setCandidates(null);
    } else {
      handleResolve(candidate.display_name);
    }
  };

  if (selectedDrug) {
    return (
      <div className="agent-card-box">
        <div className="agent-header-pill">
          <span className="agent-role-tag">{label}</span>
          <span className="agent-role-pill">{roleLabel}</span>
        </div>
        <div className="resolved-entity-card">
          <div>
            <div className="entity-name-text">{selectedDrug.display_name}</div>
            <div className="entity-sub-text">
              <span>Generic Entity #{selectedDrug.drug_id}</span>
              {selectedDrug.dosage_form && <span>• {selectedDrug.dosage_form}</span>}
              <span>• RxNorm INN/USAN</span>
            </div>
          </div>
          <button
            type="button"
            className="btn-futuristic-primary"
            style={{ padding: '6px 14px', fontSize: '0.8rem' }}
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
    <div className="agent-card-box">
      <div className="agent-header-pill">
        <span className="agent-role-tag">{label}</span>
        <span className="agent-role-pill">{roleLabel}</span>
      </div>

      <div className="input-with-button">
        <input
          type="text"
          className="futuristic-input"
          placeholder={inputPlaceholder}
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
          className="btn-futuristic-primary"
          disabled={loading || !query.trim()}
          onClick={() => handleResolve()}
        >
          {loading ? 'Resolving...' : 'Resolve'}
        </button>
      </div>

      {/* Quick Brand Selector Chips */}
      <div className="quick-brand-chips-row">
        {QUICK_BRANDS.map((b) => (
          <span
            key={b}
            className="brand-chip-item"
            onClick={() => {
              setQuery(b);
              handleResolve(b);
            }}
          >
            + {b}
          </span>
        ))}
      </div>

      {loading && (
        <div style={{ fontSize: '0.8rem', color: '#38bdf8', marginTop: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span className="futuristic-spinner" style={{ width: 14, height: 14, margin: 0, borderWidth: 2 }}></span>
          Standardizing brand entity via DRAP ➔ RxNorm INN/USAN...
        </div>
      )}
      {notFound && (
        <div style={{ fontSize: '0.8rem', color: '#fb7185', marginTop: '10px' }}>
          ⚠️ Entity not identified in DRAP dataset. Check spelling or try generic name.
        </div>
      )}
      {errorMsg && (
        <div style={{ fontSize: '0.8rem', color: '#fb7185', marginTop: '10px' }}>{errorMsg}</div>
      )}

      {/* Disambiguation Picker */}
      {candidates && candidates.length > 0 && (
        <div className="disambiguation-dropdown">
          <div className="disambig-title">Multiple formulations found — Select exact product:</div>
          <div className="disambig-list">
            {candidates.map((cand, idx) => (
              <div
                key={idx}
                className="disambig-item"
                onClick={() => handleCandidateClick(cand)}
              >
                <span>{cand.display_name}</span>
                {cand.dosage_form && (
                  <span style={{ fontSize: '0.7rem', padding: '2px 6px', background: 'rgba(255,255,255,0.1)', borderRadius: '4px' }}>
                    {cand.dosage_form}
                  </span>
                )}
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
 * Bento Grid style results display with Doctor Directives & Verbatim Quotations
 */
function ResultPanel({
  jobStatus,
  result,
  errorMessage,
  drugA,
  drugB,
  doctorMode,
  patientProfile,
}) {
  const [showEMR, setShowEMR] = useState(false);
  const [copiedEMR, setCopiedEMR] = useState(false);

  if (!jobStatus) return null;

  if (jobStatus === 'queued' || jobStatus === 'processing') {
    return (
      <div className="in-flight-card">
        <div className="futuristic-spinner"></div>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: '#ffffff', marginBottom: '8px' }}>
          AI Safety Verification in Progress
        </h3>
        <p style={{ color: '#94a3b8', fontSize: '0.95rem' }}>
          {jobStatus === 'queued'
            ? '⚡ Job queued in CloudAMQP broker (prefetch_count=1)...'
            : '🔬 LangGraph multi-agent pipeline verifying manufacturer citations against raw openFDA text...'}
        </p>
      </div>
    );
  }

  if (jobStatus === 'failed' || (!result && errorMessage)) {
    return (
      <div className="triage-hero-banner triage-hero-critical">
        <span className="severity-pill-pulsing pill-critical">System Error</span>
        <h4 style={{ color: '#ffffff', fontSize: '1.2rem', marginBottom: '8px' }}>Evaluation Pipeline Failed</h4>
        <p style={{ color: '#fda4af' }}>{errorMessage || 'An error occurred during evaluation.'}</p>
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

  const isCritical = final_status === 'interaction_found';
  const isSafe = final_status === 'none_found';
  const isRefusal = final_status === 'unverifiable';

  // Prescriber directives for doctors
  const getClinicalDirectives = () => {
    if (isCritical) {
      return [
        'CLINICAL ACTION: Avoid simultaneous co-administration where therapeutic alternatives exist.',
        'LAB MONITORING: Order baseline and serial coagulation / metabolic panels (INR, Serum Creatinine, LFTs).',
        'PATIENT INSTRUCTION: Counsel patient on early signs of adverse event (melena, unexplained hematoma, dizziness).',
      ];
    }
    if (isSafe) {
      return [
        'CLINICAL ACTION: No documented contraindication or kinetic interaction in official manufacturer text.',
        'PRESCRIBING GUIDANCE: Proceed with standard recommended therapeutic dosages and routine clinical follow-up.',
      ];
    }
    return [
      'SAFETY NOTICE: The submitted interaction claim failed verbatim groundedness verification.',
      'CLINICAL ACTION: System refused to speculate. Consult primary clinical literature (BNF / Micromedex) before co-prescribing.',
    ];
  };

  const generateEMRNote = () => {
    const timestamp = new Date().toLocaleString();
    const vitalsStr = `Patient: ${patientProfile.ageGroup} | eGFR: ${patientProfile.eGFR} | Hepatic: ${patientProfile.hepatic} | Status: ${patientProfile.pregnancy}`;
    const comorbiditiesStr = patientProfile.comorbidities.length ? patientProfile.comorbidities.join(', ') : 'None';
    const allergiesStr = patientProfile.allergies || 'NKDA';
    const dietStr = patientProfile.diet || 'Standard diet';

    let finding = '';
    if (isCritical) finding = `[HIGH RISK INTERACTION IDENTIFIED]\nMechanism: ${summary}\nVerbatim Citation: "${citation_text || 'N/A'}"`;
    else if (isSafe) finding = `[NO DOCUMENTED INTERACTION]\nFinding: ${summary || 'No adverse interaction documented in official manufacturer labeling.'}`;
    else finding = `[UNVERIFIABLE / SAFETY REFUSAL]\nFinding: Claim failed strict groundedness verification. Refusal enforced.`;

    let allergiesBlock = '';
    if (allergy_flags && allergy_flags.length > 0) {
      allergiesBlock = `\n[ALLERGY CROSS-REACTIVITY ALERT]\n` + allergy_flags.map((f) => `- ${f.allergy_term} vs ${f.matched_class}: ${f.clinical_note || f.cross_reactivity_note} (Ref: ${f.reference || 'Literature'})`).join('\n');
    }

    let foodBlock = food_interaction_summary ? `\n[DIETARY / FOOD PRECAUTION]\n- ${food_interaction_summary}` : '';

    return `================================================================================
CLINICAL PHARMACOLOGY DECISION SUPPORT CONSULTATION
DietSync Telehealth & Prescribing Intelligence
Timestamp: ${timestamp}
--------------------------------------------------------------------------------
1. PATIENT RISK PROFILE:
   ${vitalsStr}
   Comorbidities: ${comorbiditiesStr}
   Stated Allergies: ${allergiesStr}
   Dietary Factors: ${dietStr}

2. EVALUATED PHARMACEUTICAL REGIMEN:
   Agent 1: ${drugA?.display_name} (Entity #${drugA?.drug_id})
   Agent 2: ${drugB?.display_name} (Entity #${drugB?.drug_id})

3. DECISION SUPPORT FINDINGS:
${finding}${allergiesBlock}${foodBlock}

4. PHYSICIAN MANAGEMENT DIRECTIVES:
${getClinicalDirectives().map((d) => '   - ' + d).join('\n')}

5. AUDIT TRAIL:
   Source Authority: ${source || 'openFDA'}
   Groundedness Audit: ${isCritical || isSafe ? 'VERIFIED (100% Entailed)' : 'REFUSAL ENFORCED'}
   Attending Physician Signature: ___________________________ Date: ____________
================================================================================`;
  };

  const handleCopyEMR = () => {
    navigator.clipboard.writeText(generateEMRNote());
    setCopiedEMR(true);
    setTimeout(() => setCopiedEMR(false), 2500);
  };

  return (
    <div className="results-bento-dashboard">
      <div className="results-dashboard-header">
        <div>
          <div className="results-main-title">
            Clinical Safety Evaluation: {drugA?.display_name} + {drugB?.display_name}
          </div>
          <span style={{ fontSize: '0.82rem', color: '#94a3b8' }}>
            Multi-agent state machine audit • Verbatim openFDA quotations only
          </span>
        </div>

        <div className="results-action-buttons">
          <button
            type="button"
            className="btn-futuristic-primary"
            style={{ padding: '8px 16px', fontSize: '0.85rem' }}
            onClick={() => setShowEMR(!showEMR)}
          >
            {showEMR ? 'Hide EMR Note' : '📋 Generate EMR Consultation Note'}
          </button>
          <button
            type="button"
            className="btn-futuristic-primary"
            style={{ padding: '8px 16px', fontSize: '0.85rem', background: 'rgba(255,255,255,0.06)' }}
            onClick={() => window.print()}
          >
            🖨️ Print Clinical Summary
          </button>
        </div>
      </div>

      {/* 1. SEVERE INTERACTION FINDING */}
      {isCritical && (
        <div className="triage-hero-banner triage-hero-critical">
          <span className="severity-pill-pulsing pill-critical">Critical Clinical Hazard</span>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: '#ffffff', marginBottom: '10px' }}>
            Significant Drug-Drug Interaction Identified
          </h3>
          <p style={{ fontSize: '1.02rem', color: '#f8fafc', lineHeight: 1.6 }}>
            <strong>Mechanism / Clinical Finding:</strong> {summary}
          </p>

          {citation_text && (
            <div className="citation-glass-box">
              <div className="citation-header-row">
                <span className="citation-authority-tag">
                  Official Manufacturer Verbatim Citation ({source || 'openFDA'})
                </span>
                <span style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: 600 }}>
                  ✓ 100% Groundedness Verified
                </span>
              </div>
              <div className="citation-quote-text">&ldquo;{citation_text}&rdquo;</div>
            </div>
          )}

          {doctorMode && (
            <div className="doctor-directives-bento">
              <div className="directives-title">
                🩺 Prescriber Clinical Management Directives
              </div>
              {getClinicalDirectives().map((dir, idx) => (
                <div key={idx} className="directive-bullet-item">
                  <span style={{ color: '#38bdf8', fontWeight: 700 }}>▸</span>
                  <span>{dir}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 2. SAFE / NEGATIVE FINDING */}
      {isSafe && (
        <div className="triage-hero-banner triage-hero-safe">
          <span className="severity-pill-pulsing pill-safe">Safe / No Hazard Found</span>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: '#ffffff', marginBottom: '10px' }}>
            No Adverse Interaction Documented in Manufacturer Text
          </h3>
          <p style={{ fontSize: '1.02rem', color: '#f1f5f9', lineHeight: 1.6 }}>
            {summary ||
              `Official manufacturer documentation does not report a kinetic or dynamic interaction between ${drugA?.display_name} and ${drugB?.display_name}.`}
          </p>

          {doctorMode && (
            <div className="doctor-directives-bento" style={{ borderColor: 'rgba(16, 185, 129, 0.35)' }}>
              <div className="directives-title" style={{ color: '#34d399' }}>
                🩺 Prescriber Guidance
              </div>
              {getClinicalDirectives().map((dir, idx) => (
                <div key={idx} className="directive-bullet-item">
                  <span style={{ color: '#34d399', fontWeight: 700 }}>▸</span>
                  <span>{dir}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 3. SAFETY REFUSAL */}
      {isRefusal && (
        <div className="triage-hero-banner triage-hero-refusal">
          <span className="severity-pill-pulsing pill-refusal">Safety Refusal Enforced</span>
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', color: '#ffffff', marginBottom: '10px' }}>
            Unverifiable Claim — System Refused Speculation
          </h3>
          <p style={{ fontSize: '1.02rem', color: '#f1f5f9', lineHeight: 1.6 }}>
            {summary ||
              'The interaction check failed independent groundedness verification against official label sources. Rather than hallucinating, the system strictly refused to guess.'}
          </p>
        </div>
      )}

      {/* ALLERGY CROSS-REACTIVITY CARD */}
      {allergy_flags && allergy_flags.length > 0 && (
        <div className="allergy-alert-card">
          <div className="allergy-banner-title">
            <span>🛑 High-Risk Allergy Cross-Reactivity Alert</span>
          </div>
          <p style={{ fontSize: '0.88rem', color: '#fecdd3', marginBottom: '10px' }}>
            Deterministic rule-based screening (NIH RxClass) matched patient allergen against drug active ingredients with zero LLM speculation:
          </p>
          {allergy_flags.map((flag, idx) => (
            <div key={idx} style={{ background: 'rgba(8, 12, 22, 0.65)', border: '1px solid rgba(244, 63, 94, 0.3)', borderRadius: '10px', padding: '12px', marginTop: '8px' }}>
              <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#ffffff' }}>
                ⚠️ Allergen: &ldquo;{flag.allergy_term}&rdquo; ➔ Class: {flag.matched_class} {flag.rxclass_id ? `(RxClass: ${flag.rxclass_id})` : ''}
              </div>
              <div style={{ fontSize: '0.84rem', color: '#e2e8f0', marginTop: '4px' }}>
                {flag.clinical_note || flag.cross_reactivity_note}
              </div>
              {flag.reference && (
                <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontStyle: 'italic', marginTop: '4px' }}>
                  Reference: {flag.reference}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* DIETARY PRECAUTION CARD */}
      {food_interaction_summary && (
        <div className="diet-alert-card">
          <div className="diet-banner-title">
            <span>🥗 Dietary & Food Hazard Advisory</span>
          </div>
          <p style={{ fontSize: '0.92rem', color: '#fef3c7', lineHeight: 1.6 }}>
            {food_interaction_summary}
          </p>
        </div>
      )}

      {/* AUDIT FOOTNOTES */}
      <div className="audit-footnotes-bar">
        <span className="audit-tag-pill pill-verified">
          Authority: {source || 'openFDA'}
        </span>
        <span className="audit-tag-pill">
          Entity Translation: DRAP ➔ RxNorm INN/USAN
        </span>
        <span className="audit-tag-pill">
          Allergy Logic: Deterministic RxClass (0 LLM Calls)
        </span>
        <span className="audit-tag-pill">
          Groundedness Audit: {isCritical || isSafe ? 'Passed' : 'Refusal Triggered'}
        </span>
      </div>

      {/* EMR NOTE MODAL */}
      {showEMR && (
        <div className="emr-preview-modal">
          <div className="emr-modal-header">
            <div>
              <div className="emr-clinic-logo">CLINICAL DECISION SUPPORT CONSULTATION NOTE</div>
              <div style={{ fontSize: '0.8rem', color: '#475569' }}>Hospital EMR & Prescription Safety Record</div>
            </div>
            <div style={{ textAlign: 'right', fontSize: '0.8rem', color: '#475569' }}>
              <div>{new Date().toLocaleDateString()}</div>
              <div>Confidential Medical Record</div>
            </div>
          </div>

          <div className="emr-section-heading">Patient Profile & Risk Factors</div>
          <div style={{ fontSize: '0.88rem', color: '#1e293b' }}>
            <strong>Demographics:</strong> {patientProfile.ageGroup} | <strong>eGFR:</strong> {patientProfile.eGFR} | <strong>Hepatic:</strong> {patientProfile.hepatic}
            <br />
            <strong>Comorbidities:</strong> {patientProfile.comorbidities.join(', ') || 'None'}
            <br />
            <strong>Allergies:</strong> {patientProfile.allergies || 'NKDA'} | <strong>Diet:</strong> {patientProfile.diet || 'Standard'}
          </div>

          <div className="emr-section-heading">Evaluated Pharmaceutical Regimen</div>
          <div style={{ fontSize: '0.88rem', color: '#1e293b' }}>
            1. <strong>{drugA?.display_name}</strong> (Entity #{drugA?.drug_id})
            <br />
            2. <strong>{drugB?.display_name}</strong> (Entity #{drugB?.drug_id})
          </div>

          <div className="emr-section-heading">Decision Support Findings</div>
          <div style={{ fontSize: '0.88rem', color: '#1e293b' }}>
            {isCritical && <span style={{ color: '#b91c1c' }}><strong>[CRITICAL HAZARD]:</strong> {summary}</span>}
            {isSafe && <span style={{ color: '#15803d' }}><strong>[SAFE / NEGATIVE]:</strong> {summary}</span>}
            {isRefusal && <span style={{ color: '#6b21a8' }}><strong>[UNVERIFIABLE]:</strong> Refusal enforced.</span>}
          </div>

          <div className="emr-section-heading">Physician Management Directives</div>
          <div style={{ fontSize: '0.88rem', color: '#1e293b' }}>
            {getClinicalDirectives().map((d, i) => (
              <div key={i}>• {d}</div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
            <button type="button" className="btn-futuristic-primary" onClick={handleCopyEMR}>
              {copiedEMR ? '✓ Copied to Clipboard!' : 'Copy Formatted EMR Note'}
            </button>
            <button
              type="button"
              className="btn-futuristic-primary"
              style={{ background: '#e2e8f0', color: '#0f172a' }}
              onClick={() => window.print()}
            >
              Print Note
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Main Futuristic SaaS Application
 */
export default function App() {
  const [roleMode, setRoleMode] = useState('doctor'); // 'doctor' | 'pharmacist'

  // Selected drugs
  const [drugA, setDrugA] = useState(null);
  const [drugB, setDrugB] = useState(null);

  // Ephemeral patient clinical profile (never saved to database)
  const [patientProfile, setPatientProfile] = useState({
    ageGroup: 'Adult (18-64 yrs)',
    eGFR: 'Normal (> 90 mL/min)',
    hepatic: 'Normal Hepatic Function',
    pregnancy: 'Non-pregnant',
    comorbidities: ['Hypertension'],
    allergies: '',
    diet: '',
  });

  // Async job state
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [isChecking, setIsChecking] = useState(false);
  const [activePreset, setActivePreset] = useState(null);

  const wsRef = useRef(null);
  const pollIntervalRef = useRef(null);

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
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

    const allergies = patientProfile.allergies
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const dietFactors = patientProfile.diet
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    try {
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
        if (jobStatus !== 'done' && jobStatus !== 'failed') {
          startPollingFallback(newJobId);
        }
      };

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

  const loadPreset = async (preset) => {
    setActivePreset(preset.id);
    setJobStatus(null);
    setResult(null);
    setErrorMessage(null);

    setPatientProfile((prev) => ({
      ...prev,
      allergies: preset.allergies,
      diet: preset.diet,
    }));

    try {
      const [resA, resB] = await Promise.all([
        fetch(`${API_BASE}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: preset.drugA }),
        }).then((r) => r.json()),
        fetch(`${API_BASE}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: preset.drugB }),
        }).then((r) => r.json()),
      ]);

      if (resA.drug) setDrugA(resA.drug);
      if (resB.drug) setDrugB(resB.drug);
    } catch (err) {
      console.error('Failed to load preset entities:', err);
    }
  };

  const handleSwapDrugs = () => {
    const temp = drugA;
    setDrugA(drugB);
    setDrugB(temp);
  };

  const toggleComorbidity = (condition) => {
    setPatientProfile((prev) => {
      const exists = prev.comorbidities.includes(condition);
      return {
        ...prev,
        comorbidities: exists
          ? prev.comorbidities.filter((c) => c !== condition)
          : [...prev.comorbidities, condition],
      };
    });
  };

  const toggleQuickAllergy = (allergy) => {
    setPatientProfile((prev) => {
      const list = prev.allergies
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const exists = list.includes(allergy);
      const updated = exists ? list.filter((a) => a !== allergy) : [...list, allergy];
      return { ...prev, allergies: updated.join(', ') };
    });
  };

  const toggleQuickDiet = (factor) => {
    setPatientProfile((prev) => {
      const list = prev.diet
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const exists = list.includes(factor);
      const updated = exists ? list.filter((f) => f !== factor) : [...list, factor];
      return { ...prev, diet: updated.join(', ') };
    });
  };

  const canCheck = Boolean(drugA?.drug_id && drugB?.drug_id && !isChecking);

  return (
    <div className="app-wrapper">
      {/* 1. MEDVI-INSPIRED FLOATING NAVBAR */}
      <nav className="floating-nav">
        <div className="brand-capsule">
          <div className="brand-icon-aura">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <div className="brand-wordmark">
            <div className="brand-name">
              DietSync
              <span className="brand-tag-glow">Medvi Clinical SaaS</span>
            </div>
            <div className="brand-tagline">Citation-Grounded Decision Support</div>
          </div>
        </div>

        <div className="nav-controls">
          {/* Cloud Telemetry Pill */}
          <div className="telemetry-pill">
            <span className="telemetry-dot"></span>
            <span>Supabase & CloudAMQP Live</span>
          </div>

          {/* Segmented Role Switcher */}
          <div className="segmented-role-switch">
            <button
              type="button"
              className={`role-tab-btn ${roleMode === 'doctor' ? 'active' : ''}`}
              onClick={() => setRoleMode('doctor')}
            >
              🩺 Physician Prescriber
            </button>
            <button
              type="button"
              className={`role-tab-btn ${roleMode === 'pharmacist' ? 'active' : ''}`}
              onClick={() => setRoleMode('pharmacist')}
            >
              💊 Clinical Pharmacist
            </button>
          </div>
        </div>
      </nav>

      {/* 2. HERO SECTION */}
      <section className="hero-showcase">
        <div className="hero-pill-badge">
          <span>✨ Citation-Grounded Prescribing Safety Engine</span>
        </div>
        <h1 className="hero-headline">
          Clinical Decision Support Meets <br />
          <span className="gradient-text-glow">Verifiable AI Intelligence</span>
        </h1>
        <p className="hero-subhead">
          Translating local Pakistani brands into standardized pharmacological entities, with deterministic
          allergy cross-reactivity and 100% manufacturer citation verification.
        </p>

        {/* Trust Badges Ribbon */}
        <div className="trust-badges-ribbon">
          <span className="trust-badge-item">✓ 100% Verbatim openFDA Citations</span>
          <span className="trust-badge-item">✓ NIH RxClass Deterministic Matching</span>
          <span className="trust-badge-item">✓ Zero LLM Hallucination Barrier</span>
          <span className="trust-badge-item">✓ HIPAA Ephemeral Privacy</span>
        </div>
      </section>

      {/* 3. CLINICAL DEMO PRESETS (BENTO GRID STRIP) */}
      <section className="presets-bento-strip">
        <div className="presets-strip-label">
          <span className="strip-label-text">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
            Clinical Demonstration Presets:
          </span>
          <span style={{ fontSize: '0.72rem', color: '#64748b' }}>One-click pitch scenarios</span>
        </div>

        <div className="presets-scroll-row">
          {CLINICAL_PRESETS.map((preset) => (
            <div
              key={preset.id}
              className={`preset-card-chip ${activePreset === preset.id ? 'active-preset' : ''}`}
              onClick={() => loadPreset(preset)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <div className="preset-chip-title">{preset.title}</div>
              </div>
              <div style={{ fontSize: '0.68rem', color: '#38bdf8', fontWeight: 600, marginBottom: '2px' }}>
                {preset.badge}
              </div>
              <div className="preset-chip-sub">{preset.description}</div>
            </div>
          ))}
        </div>
      </section>

      {/* 4. MEDICATION WORKBENCH (DUAL AGENT CARDS + SWAP) */}
      <main className="workbench-container">
        <div className="workbench-header">
          <div className="workbench-title-group">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
            </svg>
            <div className="workbench-main-title">Interactive Medication Workbench</div>
          </div>
          <span className="workbench-badge">DRAP ➔ RxNorm INN/USAN Resolution</span>
        </div>

        {/* Dual Column Grid with Center Swap Button */}
        <div className="workbench-grid">
          <DrugResolver
            label="Primary Pharmaceutical Entity"
            roleLabel="Agent 1"
            selectedDrug={drugA}
            onSelect={setDrugA}
            onClear={() => setDrugA(null)}
            inputPlaceholder="e.g. Disprin, Lipitor, Panadol..."
          />

          <button
            type="button"
            className="swap-button-circle"
            onClick={handleSwapDrugs}
            title="Swap Drug A and Drug B"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 16l-4-4m0 0l4-4m-4 4h18" />
              <path d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </button>

          <DrugResolver
            label="Secondary Pharmaceutical Entity"
            roleLabel="Agent 2"
            selectedDrug={drugB}
            onSelect={setDrugB}
            onClear={() => setDrugB(null)}
            inputPlaceholder="e.g. Warfarin, Klaricid, Brufen..."
          />
        </div>

        {/* 5. DOCTOR'S TELEHEALTH PATIENT INTAKE (MEDVI STYLE) */}
        {roleMode === 'doctor' && (
          <div className="clinical-intake-module">
            <div className="intake-header">
              <div className="intake-title">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
                Patient Clinical Profile & Organ Function Intake
              </div>
              <span className="hipaa-shield-pill">
                🔒 HIPAA Ephemeral: Request-scoped factors are never stored in DB
              </span>
            </div>

            {/* Vitals Bento Grid */}
            <div className="vitals-bento-grid">
              <div className="vital-select-card">
                <div className="vital-card-label">Age Demographics</div>
                <select
                  className="futuristic-select"
                  value={patientProfile.ageGroup}
                  onChange={(e) => setPatientProfile({ ...patientProfile, ageGroup: e.target.value })}
                >
                  <option>Pediatric (&lt; 18 yrs)</option>
                  <option>Adult (18-64 yrs)</option>
                  <option>Geriatric (65+ yrs)</option>
                </select>
              </div>

              <div className="vital-select-card">
                <div className="vital-card-label">Renal Function (eGFR)</div>
                <select
                  className="futuristic-select"
                  value={patientProfile.eGFR}
                  onChange={(e) => setPatientProfile({ ...patientProfile, eGFR: e.target.value })}
                >
                  <option>Normal (&gt; 90 mL/min)</option>
                  <option>Mild Impairment (60-89 mL/min)</option>
                  <option>Moderate CKD (30-59 mL/min)</option>
                  <option>Severe / Dialysis (&lt; 30 mL/min)</option>
                </select>
              </div>

              <div className="vital-select-card">
                <div className="vital-card-label">Hepatic Staging</div>
                <select
                  className="futuristic-select"
                  value={patientProfile.hepatic}
                  onChange={(e) => setPatientProfile({ ...patientProfile, hepatic: e.target.value })}
                >
                  <option>Normal Hepatic Function</option>
                  <option>Mild (Child-Pugh A)</option>
                  <option>Moderate (Child-Pugh B)</option>
                  <option>Severe (Child-Pugh C)</option>
                </select>
              </div>

              <div className="vital-select-card">
                <div className="vital-card-label">Pregnancy / Lactation</div>
                <select
                  className="futuristic-select"
                  value={patientProfile.pregnancy}
                  onChange={(e) => setPatientProfile({ ...patientProfile, pregnancy: e.target.value })}
                >
                  <option>Non-pregnant</option>
                  <option>Pregnant (1st Trimester)</option>
                  <option>Pregnant (2nd / 3rd Trimester)</option>
                  <option>Lactating / Nursing</option>
                </select>
              </div>
            </div>

            {/* Comorbidities */}
            <div className="comorbidity-section">
              <div style={{ fontSize: '0.76rem', color: '#94a3b8', fontWeight: 700 }}>
                Patient Comorbidities & Chronic Conditions:
              </div>
              <div className="comorbidity-chips-row">
                {[
                  'Hypertension',
                  'Type 2 Diabetes',
                  'Atrial Fibrillation',
                  'Peptic Ulcer Disease',
                  'Asthma / Bronchospasm',
                  'Heart Failure',
                ].map((cond) => (
                  <span
                    key={cond}
                    className={`comorbidity-pill ${patientProfile.comorbidities.includes(cond) ? 'active' : ''}`}
                    onClick={() => toggleComorbidity(cond)}
                  >
                    {patientProfile.comorbidities.includes(cond) ? '✓ ' : '+ '}
                    {cond}
                  </span>
                ))}
              </div>
            </div>

            {/* Allergies & Diet Inputs */}
            <div className="intake-dual-inputs">
              <div className="allergy-diet-card">
                <div style={{ fontSize: '0.76rem', color: '#fda4af', fontWeight: 700 }}>
                  Reported Drug Allergies (Deterministic RxClass):
                </div>
                <input
                  type="text"
                  className="futuristic-input"
                  style={{ marginTop: '8px' }}
                  placeholder="e.g. penicillin, aspirin, sulfa..."
                  value={patientProfile.allergies}
                  onChange={(e) => setPatientProfile({ ...patientProfile, allergies: e.target.value })}
                />
                <div className="tag-selector-row">
                  {QUICK_ALLERGIES.map((a) => {
                    const isSelected = patientProfile.allergies.toLowerCase().includes(a.toLowerCase());
                    return (
                      <span
                        key={a}
                        className={`tag-pill ${isSelected ? 'selected-allergy' : ''}`}
                        onClick={() => toggleQuickAllergy(a)}
                      >
                        {isSelected ? '✓ ' : '+ '}
                        {a}
                      </span>
                    );
                  })}
                </div>
              </div>

              <div className="allergy-diet-card">
                <div style={{ fontSize: '0.76rem', color: '#fde68a', fontWeight: 700 }}>
                  Dietary Habits & Supplements:
                </div>
                <input
                  type="text"
                  className="futuristic-input"
                  style={{ marginTop: '8px' }}
                  placeholder="e.g. grapefruit juice, alcohol..."
                  value={patientProfile.diet}
                  onChange={(e) => setPatientProfile({ ...patientProfile, diet: e.target.value })}
                />
                <div className="tag-selector-row">
                  {QUICK_DIET.map((d) => {
                    const isSelected = patientProfile.diet.toLowerCase().includes(d.toLowerCase());
                    return (
                      <span
                        key={d}
                        className={`tag-pill ${isSelected ? 'selected-diet' : ''}`}
                        onClick={() => toggleQuickDiet(d)}
                      >
                        {isSelected ? '✓ ' : '+ '}
                        {d}
                      </span>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 6. MAIN CALL-TO-ACTION BUTTON */}
        <div className="main-cta-container">
          <button
            type="button"
            className="btn-cta-futuristic"
            disabled={!canCheck}
            onClick={handleCheckInteraction}
          >
            {isChecking ? (
              <>
                <span className="futuristic-spinner" style={{ width: 20, height: 20, margin: 0, borderWidth: 2.5 }}></span>
                Running Multi-Agent Safety Audit & Citation Verifier...
              </>
            ) : (
              <>
                <span>Run Citation-Grounded Safety Audit</span>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </>
            )}
          </button>
        </div>
      </main>

      {/* 7. BENTO-GRID RESULT DASHBOARD */}
      <ResultPanel
        jobStatus={jobStatus}
        result={result}
        errorMessage={errorMessage}
        drugA={drugA}
        drugB={drugB}
        doctorMode={roleMode === 'doctor'}
        patientProfile={patientProfile}
      />
    </div>
  );
}
