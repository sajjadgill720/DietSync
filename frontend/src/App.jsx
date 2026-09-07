import React, { useState, useRef, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';
const WS_BASE = import.meta.env.VITE_WS_BASE || 'ws://127.0.0.1:8000';

// Curated Pakistani Brand Suggestions for rapid triage
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

// Clinical Presets for live pitch & physician demonstrations
const CLINICAL_PRESETS = [
  {
    id: 'anticoag_bleeding',
    title: 'Aspirin + Warfarin (Severe Bleeding)',
    drugA: 'Disprin',
    drugB: 'Warfarin',
    allergies: '',
    diet: '',
    description: 'High-risk bleeding contraindication: additive antiplatelet & prothrombin inhibition.',
  },
  {
    id: 'statin_macrolide_grapefruit',
    title: 'Lipitor + Klaricid + Grapefruit',
    drugA: 'Lipitor',
    drugB: 'Klaricid',
    allergies: '',
    diet: 'grapefruit juice',
    description: 'Severe CYP3A4 inhibition leading to elevated statin levels & rhabdomyolysis.',
  },
  {
    id: 'penicillin_allergy',
    title: 'Augmentin + Penicillin Allergy',
    drugA: 'Augmentin',
    drugB: 'Panadol',
    allergies: 'penicillin',
    diet: '',
    description: 'Deterministic cross-reactivity alert via NIH RxClass with zero LLM speculation.',
  },
  {
    id: 'safe_coprescribe',
    title: 'Panadol + Norvasc (Clean Negative)',
    drugA: 'Panadol',
    drugB: 'Norvasc',
    allergies: '',
    diet: '',
    description: 'Documented safety: explicit negative finding with zero hallucinations.',
  },
  {
    id: 'nsaid_interference',
    title: 'Brufen + Disprin (Antiplatelet Block)',
    drugA: 'Brufen',
    drugB: 'Disprin',
    allergies: '',
    diet: '',
    description: 'Competitive COX-1 interference diminishing cardioprotective effect.',
  },
];

// Common Allergies & Diet Factors for quick click-to-add
const QUICK_ALLERGIES = ['penicillin', 'aspirin', 'sulfa', 'codeine', 'cephalosporin'];
const QUICK_DIET = ['grapefruit juice', 'alcohol', 'smoking', 'high-potassium diet'];

/**
 * Drug Resolver / Autocomplete Component
 * Queries POST /resolve synchronously.
 * Strictly adheres to DRAP brand privacy constraint: display names only, no DRAP reg numbers.
 */
function DrugResolver({
  label,
  roleLabel,
  selectedDrug,
  onSelect,
  onClear,
  onQuickSelect,
  inputPlaceholder = 'e.g. Panadol, Brufen, Disprin...',
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
      setErrorMsg(err.message || 'Failed to resolve entity');
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
      <div className="field-group">
        <div className="field-label">
          <span>{label}</span>
          <span className="field-label-pill">{roleLabel}</span>
        </div>
        <div className="selected-drug-card">
          <div className="selected-drug-info">
            <div className="selected-drug-name">
              <span>{selectedDrug.display_name}</span>
            </div>
            <div className="selected-drug-meta">
              <span>Generic Entity ID: #{selectedDrug.drug_id}</span>
              {selectedDrug.dosage_form && <span>• {selectedDrug.dosage_form}</span>}
              <span>• RxNorm Normalized</span>
            </div>
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
            Change Entity
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="field-group">
      <div className="field-label">
        <span>{label}</span>
        <span className="field-label-pill">{roleLabel}</span>
      </div>

      <div className="input-row">
        <input
          type="text"
          className="clinical-input"
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
          className="btn-primary"
          disabled={loading || !query.trim()}
          onClick={() => handleResolve()}
        >
          {loading ? 'Resolving...' : 'Resolve'}
        </button>
      </div>

      {/* Quick Brand Suggestions */}
      <div className="quick-brands-list">
        {QUICK_BRANDS.map((b) => (
          <span
            key={b}
            className="brand-chip"
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
        <div className="status-msg status-loading">
          <span className="spinner-clinical" style={{ width: 14, height: 14, margin: 0, borderWidth: 2 }}></span>
          Standardizing brand entity via RxNorm & openFDA...
        </div>
      )}
      {notFound && (
        <div className="status-msg status-error">
          Brand entity not identified. Verify spelling or enter active generic substance.
        </div>
      )}
      {errorMsg && <div className="status-msg status-error">{errorMsg}</div>}

      {/* Disambiguation Picker */}
      {candidates && candidates.length > 0 && (
        <div className="candidate-picker">
          <div className="candidate-picker-title">
            Multiple formulations identified — Select specific product:
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
 * Displays differentiated clinical safety findings with Doctor Clinical Directives
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
      <div className="loading-progress-card">
        <div className="spinner-clinical"></div>
        <h4 style={{ color: '#ffffff', marginBottom: '8px' }}>
          Clinical Safety Evaluation in Progress
        </h4>
        <p style={{ color: '#94a3b8', fontSize: '0.9rem' }}>
          {jobStatus === 'queued'
            ? 'Task queued in RabbitMQ (priority high)...'
            : 'LangGraph multi-agent pipeline verifying manufacturer citations vs openFDA...'}
        </p>
      </div>
    );
  }

  if (jobStatus === 'failed' || (!result && errorMessage)) {
    return (
      <div className="triage-card triage-critical">
        <div className="triage-header-critical">
          <span className="severity-indicator-pill-critical">System Error</span>
          <span style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f43f5e' }}>
            Verification Pipeline Interrupted
          </span>
        </div>
        <p style={{ color: '#e2e8f0' }}>
          {errorMessage || 'An error occurred during evaluation. Please verify database connectivity.'}
        </p>
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

  // Doctor Action Directives
  const getClinicalDirectives = () => {
    if (isCritical) {
      return [
        'CLINICAL ACTION: Avoid simultaneous co-administration where therapeutic alternatives exist.',
        'LABORATORY MONITORING: Order baseline and serial coagulation / metabolic panels (INR, Serum Creatinine, Liver Transaminases).',
        'PATIENT INSTRUCTION: Counsel patient on early signs of adverse event (melena, unexpected hematoma, dizziness, dark urine).',
      ];
    }
    if (isSafe) {
      return [
        'CLINICAL ACTION: No documented contraindication or kinetic interaction in official manufacturer text.',
        'PRESCRIBING GUIDANCE: Proceed with standard recommended therapeutic dosages and routine clinical follow-up.',
      ];
    }
    return [
      'SAFETY NOTICE: The submitted interaction hypothesis failed verbatim groundedness verification.',
      'CLINICAL ACTION: System refused to speculate. Consult primary clinical literature (BNF / Micromedex) before co-prescribing.',
    ];
  };

  // Generate EMR Formatted Note
  const generateEMRNote = () => {
    const timestamp = new Date().toLocaleString();
    const vitalsStr = `Patient: ${patientProfile.ageGroup} | Renal Function: ${patientProfile.eGFR} | Hepatic: ${patientProfile.hepatic} | Pregnancy/Lactation: ${patientProfile.pregnancy}`;
    const comorbiditiesStr = patientProfile.comorbidities.length
      ? patientProfile.comorbidities.join(', ')
      : 'None reported';
    const allergiesStr = patientProfile.allergies || 'NKDA (No Known Drug Allergies)';
    const dietStr = patientProfile.diet || 'Standard diet';

    let findingText = '';
    if (isCritical) {
      findingText = `[HIGH RISK INTERACTION IDENTIFIED]\nFinding: ${summary}\nManufacturer Citation: "${citation_text || 'N/A'}"`;
    } else if (isSafe) {
      findingText = `[NO DOCUMENTED INTERACTION]\nFinding: ${summary || 'No adverse interaction documented in official manufacturer labeling.'}`;
    } else {
      findingText = `[UNVERIFIABLE / SAFETY REFUSAL]\nFinding: Claim failed strict groundedness verification. Refusal enforced.`;
    }

    let allergyText = '';
    if (allergy_flags && allergy_flags.length > 0) {
      allergyText = `\n[ALLERGY CROSS-REACTIVITY ALERT]\n` +
        allergy_flags
          .map(
            (f) =>
              `- Allergen: ${f.allergy_term || 'Unknown'} | Matched Class: ${f.matched_class || 'N/A'} | Note: ${f.clinical_note || f.cross_reactivity_note || 'Flagged'} (Ref: ${f.reference || 'Pharmacological reference'})`
          )
          .join('\n');
    }

    let foodText = '';
    if (food_interaction_summary) {
      foodText = `\n[DIETARY / FOOD PRECAUTION]\n- ${food_interaction_summary}`;
    }

    return `================================================================================
CLINICAL PHARMACOLOGY CONSULTATION NOTE
DietSync Clinical Decision Support System (CDS)
Timestamp: ${timestamp}
--------------------------------------------------------------------------------
1. PATIENT DEMOGRAPHICS & CLINICAL RISK PROFILE:
   ${vitalsStr}
   Comorbidities: ${comorbiditiesStr}
   Stated Allergies: ${allergiesStr}
   Dietary Factors: ${dietStr}

2. EVALUATED PHARMACEUTICAL REGIMEN:
   Primary Agent:   ${drugA?.display_name || 'Drug A'} (Entity #${drugA?.drug_id || 'N/A'})
   Secondary Agent: ${drugB?.display_name || 'Drug B'} (Entity #${drugB?.drug_id || 'N/A'})

3. DECISION-SUPPORT AUDIT FINDINGS:
${findingText}${allergyText}${foodText}

4. PHYSICIAN MANAGEMENT PLAN & DIRECTIVES:
${getClinicalDirectives().map((d) => '   - ' + d).join('\n')}

5. AUDIT TRAIL:
   Source Authority: ${source || 'openFDA'}
   Groundedness Audit: ${isCritical || isSafe ? 'VERIFIED (100% Entailed)' : 'REFUSAL ENFORCED'}
   Attending Physician Signature: ___________________________ Date: ____________
================================================================================`;
  };

  const handleCopyEMR = () => {
    const text = generateEMRNote();
    navigator.clipboard.writeText(text);
    setCopiedEMR(true);
    setTimeout(() => setCopiedEMR(false), 2500);
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="clinical-card" style={{ marginTop: '24px' }}>
      <div className="result-header-bar">
        <div>
          <div className="result-main-title">
            Clinical Safety Evaluation: {drugA?.display_name} + {drugB?.display_name}
          </div>
          <span style={{ fontSize: '0.82rem', color: '#94a3b8' }}>
            Grounded manufacturer label audit • Zero speculative generation
          </span>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            type="button"
            className="btn-secondary btn-small"
            onClick={() => setShowEMR(!showEMR)}
          >
            {showEMR ? 'Hide EMR Note' : '📋 Generate EMR Consultation Note'}
          </button>
          <button type="button" className="btn-secondary btn-small" onClick={handlePrint}>
            🖨️ Print Clinical Summary
          </button>
        </div>
      </div>

      {/* 1. SEVERE INTERACTION FOUND */}
      {isCritical && (
        <div className="triage-card triage-critical">
          <div className="triage-header-critical">
            <span className="severity-indicator-pill-critical">Critical Hazard</span>
            <span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#f43f5e' }}>
              Significant Drug-Drug Interaction Identified
            </span>
          </div>

          <p style={{ fontSize: '1.02rem', color: '#f8fafc', marginBottom: '14px', lineHeight: 1.6 }}>
            <strong>Mechanism / Clinical Finding:</strong> {summary}
          </p>

          {/* Official Verbatim Citation */}
          {citation_text && (
            <div className="citation-callout">
              <div className="citation-header">
                <span className="citation-tag">
                  Official Manufacturer Verbatim Citation ({source || 'openFDA'})
                </span>
                <span style={{ fontSize: '0.72rem', color: '#38bdf8' }}>✓ Verified Grounded</span>
              </div>
              <div className="citation-quote">&ldquo;{citation_text}&rdquo;</div>
            </div>
          )}

          {/* Doctor Action Directives */}
          {doctorMode && (
            <div className="doctor-action-box">
              <div className="doctor-action-title">
                🩺 Prescriber Clinical Management Directives
              </div>
              <ul className="doctor-action-list">
                {getClinicalDirectives().map((dir, idx) => (
                  <li key={idx} className="doctor-action-item">
                    <span className="action-bullet">▸</span>
                    <span>{dir}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* 2. CLEAN NEGATIVE FINDING */}
      {isSafe && (
        <div className="triage-card triage-safe">
          <div className="triage-header-critical" style={{ marginBottom: '12px' }}>
            <span className="severity-indicator-pill-safe">No Hazard Found</span>
            <span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#34d399' }}>
              No Interaction Documented in Official Labeling
            </span>
          </div>

          <p style={{ color: '#e2e8f0', fontSize: '0.98rem', lineHeight: 1.6 }}>
            {summary ||
              `Official manufacturer documentation does not report a kinetic or dynamic interaction between ${drugA?.display_name} and ${drugB?.display_name}.`}
          </p>

          {doctorMode && (
            <div className="doctor-action-box" style={{ borderColor: 'rgba(16, 185, 129, 0.35)' }}>
              <div className="doctor-action-title" style={{ color: '#34d399' }}>
                🩺 Prescriber Guidance
              </div>
              <ul className="doctor-action-list">
                {getClinicalDirectives().map((dir, idx) => (
                  <li key={idx} className="doctor-action-item">
                    <span className="action-bullet" style={{ color: '#34d399' }}>▸</span>
                    <span>{dir}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* 3. SAFETY REFUSAL */}
      {isRefusal && (
        <div className="triage-card triage-refusal">
          <div className="triage-header-critical" style={{ marginBottom: '12px' }}>
            <span className="severity-indicator-pill-refusal">Safety Refusal</span>
            <span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#c084fc' }}>
              Unverifiable Claim — System Refused Speculation
            </span>
          </div>

          <p style={{ color: '#e2e8f0', fontSize: '0.98rem', lineHeight: 1.6 }}>
            {summary ||
              'The interaction check failed independent groundedness verification against official label sources. Rather than hallucinating, the system strictly refused to guess.'}
          </p>

          <div
            style={{
              marginTop: '12px',
              padding: '10px 14px',
              background: 'rgba(11, 17, 32, 0.6)',
              borderRadius: '8px',
              fontSize: '0.85rem',
              color: '#c084fc',
            }}
          >
            <strong>Safety Constraint:</strong> Refusal is a primary clinical feature. In real medicine,
            abstaining is safer than hallucinating false assurances or spurious contraindications.
          </div>
        </div>
      )}

      {/* ALLERGY CROSS-REACTIVITY BANNER */}
      {allergy_flags && allergy_flags.length > 0 && (
        <div className="allergy-alert-banner">
          <div className="allergy-alert-header">
            <span>🛑 High-Risk Allergy Cross-Reactivity Alert</span>
          </div>
          <p style={{ fontSize: '0.88rem', color: '#fecdd3' }}>
            Deterministic rule-based screening (NIH RxClass) matched patient allergen against drug active ingredients:
          </p>
          {allergy_flags.map((flag, idx) => (
            <div key={idx} className="allergy-item-card">
              <div className="allergy-item-title">
                ⚠️ Allergen: &ldquo;{flag.allergy_term || 'Unknown'}&rdquo; ➔ Matched Class: {flag.matched_class || 'Pharmacological Class'}
                {flag.rxclass_id ? ` (RxClass: ${flag.rxclass_id})` : ''}
              </div>
              <div className="allergy-item-note">
                {flag.clinical_note || flag.cross_reactivity_note || 'High risk of immunologic cross-reactivity.'}
              </div>
              {flag.reference && (
                <div className="allergy-item-ref">Reference: {flag.reference}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* FOOD & DIETARY BANNER */}
      {food_interaction_summary && (
        <div className="diet-alert-banner">
          <div className="diet-alert-header">
            <span>🥗 Dietary & Food Hazard Advisory</span>
          </div>
          <p style={{ fontSize: '0.9rem', color: '#fef3c7', lineHeight: 1.55 }}>
            {food_interaction_summary}
          </p>
        </div>
      )}

      {/* AUDIT META FOOTER */}
      <div className="verification-footer">
        <span className="audit-badge source-fda">
          <span>Authority:</span> {source || 'openFDA Manufacturer Label'}
        </span>
        <span className="audit-badge">
          <span>Entity Translation:</span> DRAP ➔ RxNorm INN/USAN
        </span>
        <span className="audit-badge">
          <span>Allergy Logic:</span> Deterministic RxClass (0 LLM Calls)
        </span>
        <span className="audit-badge">
          <span>Groundedness Audit:</span> {isCritical || isSafe ? 'Passed' : 'Refusal Triggered'}
        </span>
      </div>

      {/* EMR CLINICAL NOTE PREVIEW (Doctor-specific) */}
      {showEMR && (
        <div className="emr-preview-card">
          <div className="emr-header">
            <div>
              <div className="emr-clinic-name">CLINICAL DECISION SUPPORT CONSULTATION NOTE</div>
              <div className="emr-meta-text">Hospital EMR & Prescription Safety Record</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="emr-meta-text">{new Date().toLocaleDateString()}</div>
              <div className="emr-meta-text">Confidential Medical Record</div>
            </div>
          </div>

          <div className="emr-section-title">Patient Profile & Risk Factors</div>
          <div className="emr-text-block">
            <strong>Demographics:</strong> {patientProfile.ageGroup} | <strong>Renal:</strong> {patientProfile.eGFR} | <strong>Hepatic:</strong> {patientProfile.hepatic}
            <br />
            <strong>Comorbidities:</strong> {patientProfile.comorbidities.join(', ') || 'None reported'}
            <br />
            <strong>Documented Allergies:</strong> {patientProfile.allergies || 'No known drug allergies (NKDA)'}
            <br />
            <strong>Dietary Factors:</strong> {patientProfile.diet || 'Standard diet'}
          </div>

          <div className="emr-section-title">Evaluated Pharmaceutical Regimen</div>
          <div className="emr-text-block">
            1. <strong>{drugA?.display_name}</strong> (Generic Entity #{drugA?.drug_id})
            <br />
            2. <strong>{drugB?.display_name}</strong> (Generic Entity #{drugB?.drug_id})
          </div>

          <div className="emr-section-title">Clinical Finding & Verified Citations</div>
          <div className="emr-text-block">
            {isCritical && (
              <>
                <strong style={{ color: '#b91c1c' }}>[CRITICAL INTERACTION]:</strong> {summary}
                {citation_text && (
                  <div className="emr-citation-box">
                    &ldquo;{citation_text}&rdquo; (Source: {source || 'openFDA'})
                  </div>
                )}
              </>
            )}
            {isSafe && (
              <span style={{ color: '#15803d' }}>
                <strong>[SAFE / NEGATIVE]:</strong> {summary}
              </span>
            )}
            {isRefusal && (
              <span style={{ color: '#6b21a8' }}>
                <strong>[UNVERIFIABLE]:</strong> Refusal enforced — no reliable citation found.
              </span>
            )}
          </div>

          {allergy_flags && allergy_flags.length > 0 && (
            <>
              <div className="emr-section-title">Allergy Cross-Reactivity Risk</div>
              <div className="emr-text-block">
                {allergy_flags.map((f, i) => (
                  <div key={i}>
                    • <strong>{f.allergy_term}</strong> vs {f.matched_class}: {f.clinical_note || f.cross_reactivity_note}
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="emr-section-title">Physician Action Directives</div>
          <div className="emr-text-block">
            {getClinicalDirectives().map((d, i) => (
              <div key={i}>• {d}</div>
            ))}
          </div>

          <div className="emr-actions-row">
            <button type="button" className="btn-primary" onClick={handleCopyEMR}>
              {copiedEMR ? '✓ Copied to Clipboard!' : 'Copy Formatted EMR Note'}
            </button>
            <button type="button" className="btn-secondary" onClick={handlePrint}>
              Print Note
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Main Application Component
 */
export default function App() {
  const [roleMode, setRoleMode] = useState('doctor'); // 'doctor' | 'pharmacist'

  // Prescribed Drugs
  const [drugA, setDrugA] = useState(null);
  const [drugB, setDrugB] = useState(null);

  // Ephemeral Patient Profile (Never Persisted to DB)
  const [patientProfile, setPatientProfile] = useState({
    ageGroup: 'Adult (18-64 yrs)',
    eGFR: 'Normal (> 90 mL/min)',
    hepatic: 'Normal Hepatic Function',
    pregnancy: 'Non-pregnant',
    comorbidities: ['Hypertension'],
    allergies: '',
    diet: '',
  });

  // Async Interaction Check State
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
        if (jobStatus !== 'done' && jobStatus !== 'failed') {
          startPollingFallback(newJobId);
        }
      };

      // Safety timer for polling fallback
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

  // Preset Selector Loader
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
    <div className="app-container">
      {/* Top Header & Role Switcher */}
      <header className="header-bar">
        <div className="brand-wrapper">
          <div className="brand-icon-shield">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="M12 8v8" />
              <path d="M8 12h8" />
            </svg>
          </div>
          <div>
            <div className="brand-title">
              DietSync
              <span className="brand-badge">Clinical CDS v2.0</span>
            </div>
            <div className="brand-subtitle">
              Citation-Grounded Drug Interaction & Pakistani Brand Resolution Engine
            </div>
          </div>
        </div>

        {/* Role Toggle Switch: Doctor vs Pharmacist */}
        <div className="mode-switch-group">
          <button
            type="button"
            className={`mode-btn ${roleMode === 'doctor' ? 'active' : ''}`}
            onClick={() => setRoleMode('doctor')}
          >
            🩺 Physician Prescriber
          </button>
          <button
            type="button"
            className={`mode-btn ${roleMode === 'pharmacist' ? 'active' : ''}`}
            onClick={() => setRoleMode('pharmacist')}
          >
            💊 Clinical Pharmacist
          </button>
        </div>
      </header>

      {/* Clinical Demo Preset Quick Bar (For Pitch & Fast Triage) */}
      <div className="demo-preset-bar">
        <span className="preset-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
          Clinical Presets:
        </span>
        <div className="preset-chips-container">
          {CLINICAL_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`preset-chip ${activePreset === preset.id ? 'active-preset' : ''}`}
              onClick={() => loadPreset(preset)}
              title={preset.description}
            >
              {preset.title}
            </button>
          ))}
        </div>
      </div>

      {/* Main Prescription & Drug Resolution Card */}
      <div className="clinical-card">
        <div className="card-header">
          <div className="card-title">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#38bdf8"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
            </svg>
            Prescription Regimen Resolution
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            {drugA && drugB && (
              <button
                type="button"
                className="btn-secondary btn-small"
                onClick={handleSwapDrugs}
                title="Swap Drug A and Drug B"
              >
                ⇄ Swap Entities
              </button>
            )}
            <span className="card-badge">DRAP ➔ RxNorm INN/USAN</span>
          </div>
        </div>

        {/* Drug Resolvers Grid */}
        <div className="grid-two-col">
          <DrugResolver
            label="Primary Pharmaceutical Entity (Drug A)"
            roleLabel="Agent 1"
            selectedDrug={drugA}
            onSelect={setDrugA}
            onClear={() => setDrugA(null)}
            inputPlaceholder="e.g. Disprin, Lipitor, Panadol..."
          />
          <DrugResolver
            label="Secondary Pharmaceutical Entity (Drug B)"
            roleLabel="Agent 2"
            selectedDrug={drugB}
            onSelect={setDrugB}
            onClear={() => setDrugB(null)}
            inputPlaceholder="e.g. Warfarin, Klaricid, Brufen..."
          />
        </div>

        {/* DOCTOR-SPECIFIC PATIENT PROFILE MODULE */}
        {roleMode === 'doctor' && (
          <div className="clinical-profile-panel">
            <div className="profile-header">
              <div className="profile-title">
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#38bdf8"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
                Patient Clinical Risk Factors & Organ Function
              </div>
              <span className="privacy-guarantee">
                🔒 HIPAA & Ephemeral: Request-scoped factors are never stored in DB
              </span>
            </div>

            {/* Organ Function & Demographics Selectors */}
            <div className="clinical-vitals-grid">
              <div className="vital-select-card">
                <div className="vital-select-label">Age Demographics</div>
                <select
                  className="vital-select-input"
                  value={patientProfile.ageGroup}
                  onChange={(e) =>
                    setPatientProfile({ ...patientProfile, ageGroup: e.target.value })
                  }
                >
                  <option>Pediatric (&lt; 18 yrs)</option>
                  <option>Adult (18-64 yrs)</option>
                  <option>Geriatric (65+ yrs)</option>
                </select>
              </div>

              <div className="vital-select-card">
                <div className="vital-select-label">Renal Function (eGFR)</div>
                <select
                  className="vital-select-input"
                  value={patientProfile.eGFR}
                  onChange={(e) =>
                    setPatientProfile({ ...patientProfile, eGFR: e.target.value })
                  }
                >
                  <option>Normal (&gt; 90 mL/min)</option>
                  <option>Mild Impairment (60-89 mL/min)</option>
                  <option>Moderate CKD (30-59 mL/min)</option>
                  <option>Severe / Dialysis (&lt; 30 mL/min)</option>
                </select>
              </div>

              <div className="vital-select-card">
                <div className="vital-select-label">Hepatic Staging</div>
                <select
                  className="vital-select-input"
                  value={patientProfile.hepatic}
                  onChange={(e) =>
                    setPatientProfile({ ...patientProfile, hepatic: e.target.value })
                  }
                >
                  <option>Normal Hepatic Function</option>
                  <option>Mild (Child-Pugh A)</option>
                  <option>Moderate (Child-Pugh B)</option>
                  <option>Severe (Child-Pugh C)</option>
                </select>
              </div>

              <div className="vital-select-card">
                <div className="vital-select-label">Pregnancy / Lactation</div>
                <select
                  className="vital-select-input"
                  value={patientProfile.pregnancy}
                  onChange={(e) =>
                    setPatientProfile({ ...patientProfile, pregnancy: e.target.value })
                  }
                >
                  <option>Non-pregnant</option>
                  <option>Pregnant (1st Trimester)</option>
                  <option>Pregnant (2nd / 3rd Trimester)</option>
                  <option>Lactating / Nursing</option>
                </select>
              </div>
            </div>

            {/* Comorbidities */}
            <div className="comorbidities-group">
              <div style={{ fontSize: '0.78rem', color: '#94a3b8', fontWeight: 600 }}>
                Patient Comorbidities & Chronic Conditions:
              </div>
              <div className="comorbidities-grid">
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
                    className={`condition-pill ${
                      patientProfile.comorbidities.includes(cond) ? 'active' : ''
                    }`}
                    onClick={() => toggleComorbidity(cond)}
                  >
                    {patientProfile.comorbidities.includes(cond) ? '✓ ' : '+ '}
                    {cond}
                  </span>
                ))}
              </div>
            </div>

            {/* Allergies & Diet Inputs with Quick-Add Pills */}
            <div className="grid-two-col" style={{ marginTop: '16px', marginBottom: 0 }}>
              <div>
                <div style={{ fontSize: '0.78rem', color: '#f43f5e', fontWeight: 700 }}>
                  Reported Drug Allergies (Rule-based RxClass):
                </div>
                <input
                  type="text"
                  className="clinical-input"
                  style={{ marginTop: '6px' }}
                  placeholder="e.g. penicillin, aspirin, sulfa..."
                  value={patientProfile.allergies}
                  onChange={(e) =>
                    setPatientProfile({ ...patientProfile, allergies: e.target.value })
                  }
                />
                <div className="pill-selector-row">
                  {QUICK_ALLERGIES.map((a) => {
                    const isSelected = patientProfile.allergies
                      .toLowerCase()
                      .includes(a.toLowerCase());
                    return (
                      <span
                        key={a}
                        className={`pill-tag ${isSelected ? 'selected-allergy' : ''}`}
                        onClick={() => toggleQuickAllergy(a)}
                      >
                        {isSelected ? '✓ ' : '+ '}
                        {a}
                      </span>
                    );
                  })}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.78rem', color: '#f59e0b', fontWeight: 700 }}>
                  Dietary Habits & Supplements:
                </div>
                <input
                  type="text"
                  className="clinical-input"
                  style={{ marginTop: '6px' }}
                  placeholder="e.g. grapefruit juice, alcohol..."
                  value={patientProfile.diet}
                  onChange={(e) =>
                    setPatientProfile({ ...patientProfile, diet: e.target.value })
                  }
                />
                <div className="pill-selector-row">
                  {QUICK_DIET.map((d) => {
                    const isSelected = patientProfile.diet
                      .toLowerCase()
                      .includes(d.toLowerCase());
                    return (
                      <span
                        key={d}
                        className={`pill-tag ${isSelected ? 'selected-diet' : ''}`}
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

        {/* Action Button */}
        <button
          type="button"
          className="btn-primary btn-action-main"
          disabled={!canCheck}
          onClick={handleCheckInteraction}
        >
          {isChecking ? (
            <>
              <span className="spinner-clinical" style={{ width: 18, height: 18, margin: 0, borderWidth: 2 }}></span>
              Evaluating Grounded Interactions & Safety Gates...
            </>
          ) : (
            'Execute Grounded Clinical Safety Check ➔'
          )}
        </button>
      </div>

      {/* Differentiated Results Panel with Doctor Clinical Directives */}
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
