/**
 * AgentOps SRE - Asynchronous Investigation, SSE Streaming & Evidence Rendering Module
 */

import { fetchJson, connectSSE, escapeHtml, formatTime } from './api.js';

let activeJobId = null;
let activeEventSource = null;
let progressTimerInterval = null;
let jobStartTime = null;
let lastReceivedEventId = null;
let isSubmittingInvestigation = false;
let currentIncident = null;

export function getActiveJobId() {
  return activeJobId;
}

export function getCurrentIncident() {
  return currentIncident;
}

export async function startInvestigation() {
  if (isSubmittingInvestigation) return;
  if (activeJobId) {
    alert('An autonomous investigation is currently in progress. Please wait for it to complete or cancel it before starting another.');
    return;
  }

  const ns = document.getElementById('invNamespaceSelect')?.value || 'demo';
  const wl = document.getElementById('invWorkloadSelect')?.value || 'demo-app';
  const modelCompound = document.getElementById('invModelSelect')?.value || '';
  const desc = document.getElementById('invDescriptionInput')?.value;
  const dryRun = document.getElementById('invDryRunCheck')?.checked || false;

  // Parse provider:model compound string (e.g. "ollama:granite4.1:3b", "openai:gpt-4o", "mock")
  let provider = 'ollama';
  let model = modelCompound;
  const KNOWN_PROVIDERS = ['ollama', 'openai', 'gemini', 'mock', 'auto'];
  if (modelCompound.includes(':')) {
    const idx = modelCompound.indexOf(':');
    const pref = modelCompound.slice(0, idx).toLowerCase();
    if (KNOWN_PROVIDERS.includes(pref)) {
      provider = pref;
      model = modelCompound.slice(idx + 1) || undefined;
    }
  } else if (modelCompound === 'mock') {
    provider = 'mock';
    model = 'deterministic-rule-engine-v1';
  }

  // Real AI enforcement check in frontend
  if (!model && !document.getElementById('invModelSelect')?.disabled) {
    alert('Please select an active model tag. Mock inference is prohibited in live investigations.');
    return;
  }

  const btn = document.getElementById('btnRunInvestigation');
  isSubmittingInvestigation = true;
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm"></span> Submitting Job...';
  }

  // Update visual lifecycle stepper if present
  if (window.updateLifecycleStepper) {
    window.updateLifecycleStepper(5);
  }

  const payload = {
    namespace: ns,
    workload: wl,
    provider: provider,
    model: model,
    incident_description: desc,
    dry_run: dryRun,
    source: 'MANUAL',
  };

  try {
    const { ok, status, data } = await fetchJson('/api/incidents/investigate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (!ok || status !== 202) {
      alert(`Investigation submission failed (${status}): ${data?.error || 'Unknown error'}`);
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">⚡</span> Run Autonomous Investigation';
      }
      if (window.updateLifecycleStepper) {
        window.updateLifecycleStepper(4, 5);
      }
      return;
    }

    activeJobId = data.job_id;
    localStorage.setItem('agentops_active_job_id', activeJobId);

    // Switch to progress view and start SSE streaming
    showProgressCard(data);
    attachStreamListener(activeJobId);

    // Refresh queue so operator sees the new job immediately
    if (window.loadInvestigationsQueue) {
      window.loadInvestigationsQueue();
    }
  } catch (err) {
    alert(`Failed to start investigation: ${err.message}`);
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span class="btn-icon">⚡</span> Run Autonomous Investigation';
    }
  } finally {
    isSubmittingInvestigation = false;
  }
}

export function showProgressCard(jobData) {
  const progCard = document.getElementById('investigationProgressCard');
  const resultsCard = document.getElementById('investigationResultsCard');
  if (resultsCard) resultsCard.style.display = 'none';
  if (!progCard) return;

  progCard.style.display = 'block';
  const jobIdEl = document.getElementById('progJobId');
  if (jobIdEl) jobIdEl.textContent = jobData.job_id || '--';

  const traceBadge = document.getElementById('progTraceIdBadge');
  if (traceBadge) {
    if (jobData.trace_id) {
      traceBadge.style.display = 'inline-block';
      traceBadge.textContent = `Trace: ${jobData.trace_id.slice(0, 8)}...`;
      traceBadge.title = `W3C Trace ID: ${jobData.trace_id}`;
    } else {
      traceBadge.style.display = 'none';
    }
  }

  const badgeEl = document.getElementById('progCurrentStageBadge');
  if (badgeEl) {
    badgeEl.textContent = (jobData.stage || 'QUEUED').toUpperCase();
    badgeEl.className = 'stage-badge stage-queued';
  }

  const msgEl = document.getElementById('progCurrentMessage');
  if (msgEl) {
    msgEl.textContent = 'Investigation enqueued into durable SQLite store...';
  }

  const eventsList = document.getElementById('progEventsList');
  if (eventsList) {
    eventsList.innerHTML = `<div class="prog-event-item">
      <span class="prog-event-time">${new Date().toLocaleTimeString()}</span>
      <span class="prog-event-stage stage-queued">QUEUED</span>
      <span class="prog-event-msg">Investigation accepted (Job: ${escapeHtml(jobData.job_id)})</span>
    </div>`;
  }

  // Start elapsed timer
  jobStartTime = Date.now();
  if (progressTimerInterval) clearInterval(progressTimerInterval);
  progressTimerInterval = setInterval(() => {
    const elapsedSec = ((Date.now() - jobStartTime) / 1000).toFixed(1);
    const timeEl = document.getElementById('progElapsedTime');
    if (timeEl) timeEl.textContent = `${elapsedSec}s`;
  }, 100);

  const btnCancel = document.getElementById('btnCancelInvestigation');
  if (btnCancel) btnCancel.disabled = false;
}

export function attachStreamListener(jobId, startEventId = null) {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }

  const streamBadge = document.getElementById('progStreamBadge');
  if (streamBadge) {
    streamBadge.className = 'status-pill status-info';
    streamBadge.textContent = 'STREAMING';
  }

  activeEventSource = connectSSE(`/api/investigations/${jobId}/stream`, {
    lastEventId: startEventId,
    onEvent: (event, eventId) => {
      lastReceivedEventId = eventId;
      handleProgressEvent(event);
    },
    onError: (err) => {
      console.warn('SSE stream disconnected, falling back to polling:', err);
      if (streamBadge) {
        streamBadge.className = 'status-pill status-warning';
        streamBadge.textContent = 'POLLING';
      }
      // Start fallback poll loop
      pollInvestigationStatus(jobId);
    },
    onComplete: () => {
      onInvestigationFinished(jobId);
    },
  });
}

function handleProgressEvent(event) {
  const stage = event.stage || 'progress';
  const msg = event.message || '';
  const stageStatus = event.stage_status || (stage === 'completed' ? 'completed' : (stage === 'failed' ? 'failed' : 'running'));

  // Update current stage pill
  const stageBadge = document.getElementById('progCurrentStageBadge');
  if (stageBadge) {
    stageBadge.textContent = stage.replace(/_/g, ' ').toUpperCase();
    stageBadge.className = `stage-badge stage-${stage}`;
  }

  const msgEl = document.getElementById('progCurrentMessage');
  if (msgEl) {
    msgEl.textContent = msg;
  }

  // Update trace ID badge if available
  if (event.trace_id) {
    const traceBadge = document.getElementById('progTraceIdBadge');
    if (traceBadge) {
      traceBadge.style.display = 'inline-block';
      traceBadge.textContent = `Trace: ${event.trace_id.slice(0, 8)}...`;
      traceBadge.title = `W3C Trace ID: ${event.trace_id}`;
    }
  }

  // Append or update ordered events stream (deduplicate by event_id on reconnect)
  const eventsList = document.getElementById('progEventsList');
  if (eventsList) {
    const eventKey = event.event_id ? `prog-event-${event.event_id}` : null;
    let row = eventKey ? document.getElementById(eventKey) : null;

    let metaHtml = '';
    if (event.duration_ms != null) {
      const durText = event.duration_ms < 1000 ? `${event.duration_ms}ms` : `${(event.duration_ms / 1000).toFixed(2)}s`;
      metaHtml += `<span class="prog-event-pill pill-duration" title="Stage Execution Duration">⏱ ${durText}</span>`;
    }
    if (event.evidence_count != null && event.evidence_count > 0) {
      metaHtml += `<span class="prog-event-pill pill-evidence" title="Collected Evidence Items">+${event.evidence_count} items</span>`;
    }
    if (stageStatus && stageStatus !== 'running') {
      const statusClass = stageStatus === 'completed' ? 'pill-status-completed' : (stageStatus === 'failed' ? 'pill-status-failed' : 'pill-status-running');
      metaHtml += `<span class="prog-event-pill ${statusClass}">${escapeHtml(stageStatus.toUpperCase())}</span>`;
    }

    const contentHtml = `
      <span class="prog-event-time">${formatTime(event.timestamp)}</span>
      <span class="prog-event-stage stage-${stage}">${escapeHtml(stage.toUpperCase())}</span>
      <span class="prog-event-msg">${escapeHtml(msg)}</span>
      ${metaHtml ? `<div class="prog-event-meta">${metaHtml}</div>` : ''}
    `;

    if (row) {
      row.innerHTML = contentHtml;
    } else {
      row = document.createElement('div');
      row.className = 'prog-event-item';
      if (eventKey) row.id = eventKey;
      row.innerHTML = contentHtml;
      eventsList.appendChild(row);
      eventsList.scrollTop = eventsList.scrollHeight;
    }
  }

  if (stage === 'completed' || stage === 'failed' || stage === 'cancelled' || stageStatus === 'failed') {
    onInvestigationFinished(event.job_id || activeJobId);
  }
}

async function onInvestigationFinished(jobId) {
  if (progressTimerInterval) {
    clearInterval(progressTimerInterval);
    progressTimerInterval = null;
  }

  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }

  const streamBadge = document.getElementById('progStreamBadge');
  if (streamBadge) {
    streamBadge.className = 'status-pill status-healthy';
    streamBadge.textContent = 'FINISHED';
  }

  const btnCancel = document.getElementById('btnCancelInvestigation');
  if (btnCancel) btnCancel.disabled = true;

  const btnRun = document.getElementById('btnRunInvestigation');
  if (btnRun) {
    btnRun.disabled = false;
    btnRun.innerHTML = '<span class="btn-icon">⚡</span> Run Autonomous Investigation';
  }

  localStorage.removeItem('agentops_active_job_id');

  // Fetch final RCA report
  const { ok, data } = await fetchJson(`/api/investigations/${jobId}/result`);
  if (ok && data) {
    renderIncidentReport(data);
    if (window.updateLifecycleStepper) {
      window.updateLifecycleStepper(9);
    }
  } else {
    // Check if error state
    const jobRes = await fetchJson(`/api/investigations/${jobId}`);
    if (jobRes.ok && jobRes.data) {
      if (jobRes.data.result) {
        renderIncidentReport(jobRes.data.result);
      } else {
        renderFailureReport(jobRes.data);
      }
    }
    if (window.updateLifecycleStepper) {
      window.updateLifecycleStepper(6, 6);
    }
  }

  // Refresh queue and telemetry
  if (window.loadInvestigationsQueue) window.loadInvestigationsQueue();
  if (window.fetchStatus) window.fetchStatus();
  if (window.fetchTelemetryPulse) window.fetchTelemetryPulse();
  if (window.fetchLLMHistory) window.fetchLLMHistory();
}

async function pollInvestigationStatus(jobId) {
  let isTerminal = false;
  while (!isTerminal && activeJobId === jobId) {
    await new Promise((r) => setTimeout(r, 2000));
    const { ok, data } = await fetchJson(`/api/investigations/${jobId}`);
    if (ok && data) {
      const stageBadge = document.getElementById('progCurrentStageBadge');
      if (stageBadge) {
        stageBadge.textContent = (data.stage || data.status).toUpperCase();
        stageBadge.className = `stage-badge stage-${data.stage}`;
      }

      if (['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(data.status)) {
        isTerminal = true;
        onInvestigationFinished(jobId);
        break;
      }
    }
  }
}

export async function cancelCurrentInvestigation() {
  if (!activeJobId) return;

  const btn = document.getElementById('btnCancelInvestigation');
  if (btn) btn.disabled = true;

  const { ok } = await fetchJson(`/api/investigations/${activeJobId}/cancel`, {
    method: 'POST',
  });

  if (ok) {
    handleProgressEvent({
      job_id: activeJobId,
      stage: 'cancelled',
      message: 'Operator requested cancellation.',
      timestamp: new Date().toISOString(),
    });
    onInvestigationFinished(activeJobId);
  }
}

export async function resumeActiveInvestigation() {
  const savedJobId = localStorage.getItem('agentops_active_job_id');
  if (!savedJobId) return;

  const { ok, data } = await fetchJson(`/api/investigations/${savedJobId}`);
  if (!ok || !data) {
    localStorage.removeItem('agentops_active_job_id');
    return;
  }

  if (['QUEUED', 'RUNNING'].includes(data.status)) {
    activeJobId = savedJobId;
    showProgressCard(data);
    attachStreamListener(activeJobId);
  } else if (data.status === 'SUCCEEDED' && data.result) {
    renderIncidentReport(data.result);
    localStorage.removeItem('agentops_active_job_id');
  }
}

export function renderIncidentReport(report) {
  currentIncident = report;

  const resultsCard = document.getElementById('investigationResultsCard');
  if (resultsCard) resultsCard.style.display = 'block';

  // Incident ID & Status Badges
  const idLabel = document.getElementById('invIncidentIdLabel');
  if (idLabel) idLabel.textContent = report.incident_id || 'inc-unknown';

  const stBadge = document.getElementById('invStatusBadge');
  if (stBadge) {
    stBadge.textContent = report.status;
    stBadge.className = report.status === 'RESOLVED'
      ? 'status-pill status-healthy'
      : (report.status === 'PENDING_APPROVAL' ? 'status-pill status-warning' : (report.status === 'FAILED' ? 'status-pill status-danger' : 'status-pill status-healthy'));
  }

  const valBadge = document.getElementById('invValidationBadge');
  if (valBadge) {
    const valid = report.validation_passed !== false;
    valBadge.textContent = valid ? 'VALIDATED GROUNDED' : 'VALIDATION FAILED';
    valBadge.className = valid ? 'status-pill status-healthy' : 'status-pill status-danger';
  }

  // Failure banner
  const failBanner = document.getElementById('invFailureBanner');
  const failReason = document.getElementById('invFailureReason');
  if (failBanner && failReason) {
    if (report.validation_passed === false || report.status === 'FAILED') {
      failBanner.style.display = 'block';
      failReason.textContent = report.root_cause || 'LLM output failed grounding or schema validation';
    } else {
      failBanner.style.display = 'none';
    }
  }

  // Missing signals alert
  const missingAlert = document.getElementById('invMissingSignalsAlert');
  const missingText = document.getElementById('invMissingSignalsText');
  if (missingAlert && missingText) {
    if (report.missing_signals && report.missing_signals.length > 0) {
      missingAlert.style.display = 'block';
      missingText.textContent = `The following signals were offline or missing: ${report.missing_signals.join(', ')}`;
    } else {
      missingAlert.style.display = 'none';
    }
  }

  // Diagnosis Block
  const diagType = document.getElementById('diagIncidentType');
  if (diagType) diagType.textContent = report.incident_type || 'Unknown';

  const diagSev = document.getElementById('diagSeverity');
  if (diagSev) diagSev.textContent = report.severity || report.risk_level || 'MEDIUM';

  const diagConf = document.getElementById('diagConfidence');
  if (diagConf) diagConf.textContent = `${Math.round((report.confidence || 0) * 100)}%`;

  const diagSrc = document.getElementById('diagSource');
  if (diagSrc) diagSrc.textContent = report.source || 'MANUAL';

  // RCA Text
  const rcaSummary = document.getElementById('rcaSummaryText');
  if (rcaSummary) rcaSummary.textContent = report.summary || '--';

  const rcaRoot = document.getElementById('rcaRootCauseText');
  if (rcaRoot) rcaRoot.textContent = report.root_cause || '--';

  // Grounded Evidence Pills
  const pillsContainer = document.getElementById('rcaEvidencePills');
  if (pillsContainer) {
    pillsContainer.innerHTML = '';
    const items = report.evidence_items || [];
    if (items.length === 0) {
      pillsContainer.innerHTML = '<span class="text-muted text-sm">No evidence items referenced.</span>';
    } else {
      items.forEach((item) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'evidence-pill';
        btn.innerHTML = `<strong>${escapeHtml(item.id)}</strong> <small>(${escapeHtml(item.source)})</small>`;
        btn.title = `Click to inspect ${escapeHtml(item.id)} in Evidence Explorer`;
        btn.onclick = () => {
          if (window.navigateToEvidence) window.navigateToEvidence(item.id);
        };
        pillsContainer.appendChild(btn);
      });
    }
  }

  // Remediation & Policy Governance
  const polBadge = document.getElementById('policyDecisionBadge');
  if (polBadge) {
    polBadge.textContent = report.policy_decision || 'NOT_EVALUATED';
    polBadge.className = report.policy_decision === 'ALLOW'
      ? 'status-pill status-healthy'
      : (report.policy_decision === 'REQUIRE_APPROVAL' ? 'status-pill status-warning' : 'status-pill status-danger');
  }

  const recAction = document.getElementById('recActionText');
  if (recAction) recAction.textContent = report.recommended_action || report.recommended_remediation || 'none';

  const recAppr = document.getElementById('recApprovalRequiredText');
  if (recAppr) recAppr.textContent = report.approval_required ? 'REQUIRED (Single-Use Token)' : 'NOT REQUIRED';

  const recRisk = document.getElementById('recRiskLevelText');
  if (recRisk) recRisk.textContent = report.risk_level || 'UNKNOWN';

  const recReason = document.getElementById('recPolicyReasonText');
  if (recReason) recReason.textContent = report.policy_reason || '';

  // Inline Approval Action Box
  const apprBox = document.getElementById('inlineApprovalActionBox');
  const apprIdEl = document.getElementById('inlineApprovalId');
  if (apprBox && apprIdEl) {
    if (report.approval_required && report.approval_id && (report.status === 'PENDING_APPROVAL' || !report.status || report.status === 'SUCCEEDED' || report.status === 'DRY_RUN_EVALUATED')) {
      apprBox.style.display = 'block';
      apprIdEl.textContent = report.approval_id;
      if (window.setCurrentApprovalId) window.setCurrentApprovalId(report.approval_id);
    } else {
      apprBox.style.display = 'none';
    }
  }

  // Section 4: LLM Observability Metrics
  renderLLMTelemetry(report);

  // Section 5: Evidence Explorer Cards
  renderEvidenceExplorer(report.evidence_items || []);
}

export function renderFailureReport(jobData) {
  const card = document.getElementById('investigationResultsCard');
  if (!card) return;
  card.style.display = 'block';

  const idLabel = document.getElementById('invIncidentIdLabel');
  if (idLabel) idLabel.textContent = jobData.incident_id || jobData.job_id || '--';

  const diagType = document.getElementById('diagIncidentType');
  if (diagType) diagType.textContent = 'FAILED';

  const diagConf = document.getElementById('diagConfidence');
  if (diagConf) diagConf.textContent = '0%';

  const rcaSum = document.getElementById('rcaSummaryText');
  if (rcaSum) rcaSum.textContent = 'Investigation execution encountered a fatal error.';

  const rcaRoot = document.getElementById('rcaRootCauseText');
  if (rcaRoot) rcaRoot.textContent = jobData.error_json?.error || 'Unknown runtime error.';

  const failBanner = document.getElementById('invFailureBanner');
  const failReason = document.getElementById('invFailureReason');
  if (failBanner && failReason) {
    failBanner.style.display = 'block';
    failReason.textContent = jobData.error_json?.error || 'Investigation failed';
  }
}

export function renderLLMTelemetry(report) {
  const rt = report.llm_runtime || {};
  const modelEl = document.getElementById('llmActiveModel');
  if (modelEl) modelEl.textContent = rt.model ? `${rt.model} (${rt.provider || 'ollama'})` : '--';

  const modeEl = document.getElementById('llmActiveMode');
  if (modeEl) modeEl.textContent = (rt.mode || 'local').toUpperCase();

  const latEl = document.getElementById('llmLatency');
  if (latEl) latEl.textContent = rt.latency_seconds !== undefined ? `${rt.latency_seconds}s` : '--';

  const speedEl = document.getElementById('llmTokenSpeed');
  if (speedEl) speedEl.textContent = rt.tokens_per_second !== undefined ? `${rt.tokens_per_second} tok/s` : 'N/A';

  const pTokens = document.getElementById('llmPromptTokens');
  if (pTokens) pTokens.textContent = rt.prompt_tokens ?? '--';

  const cTokens = document.getElementById('llmCompletionTokens');
  if (cTokens) cTokens.textContent = rt.completion_tokens ?? '--';

  const valText = document.getElementById('llmValidationText');
  if (valText) {
    const valid = report.validation_passed !== false;
    valText.textContent = valid ? 'PASSED (100%)' : 'FAILED REJECTED';
    valText.className = valid ? 'meter-value text-sm text-success' : 'meter-value text-sm text-danger';
  }
}

export function renderEvidenceExplorer(items) {
  const countBadge = document.getElementById('evidenceCountBadge');
  if (countBadge) countBadge.textContent = `${items.length} Items`;

  const container = document.getElementById('evidenceListContainer');
  if (!container) return;

  if (items.length === 0) {
    container.innerHTML = `<p class="text-muted text-center py-4">No investigation evidence loaded. Run an investigation to view multi-signal evidence.</p>`;
    return;
  }

  container.innerHTML = '';
  items.forEach((item) => {
    const card = document.createElement('div');
    card.id = `evidence-card-${item.id}`;
    card.className = 'evidence-item-card';

    let srcBadgeClass = 'badge-neutral';
    if (item.source === 'kubernetes') srcBadgeClass = 'badge-info';
    else if (item.source === 'prometheus') srcBadgeClass = 'badge-warning';
    else if (item.source === 'loki') srcBadgeClass = 'badge-danger';

    let sevBadgeClass = 'badge-neutral';
    if (item.severity === 'CRITICAL') sevBadgeClass = 'badge-danger';
    else if (item.severity === 'WARNING') sevBadgeClass = 'badge-warning';

    card.innerHTML = `
      <div class="evidence-item-header">
        <div style="display:flex; gap:0.5rem; align-items:center;">
          <strong class="mono text-accent">${escapeHtml(item.id)}</strong>
          <span class="badge badge-sm ${srcBadgeClass}">${escapeHtml((item.source || '').toUpperCase())}</span>
          <span class="mono text-xs text-muted">${escapeHtml(item.resource || '')}</span>
        </div>
        <span class="badge badge-sm ${sevBadgeClass}">${escapeHtml(item.severity || 'INFO')}</span>
      </div>
      <div class="evidence-obs mt-2">${escapeHtml(item.observation)}</div>
      <div class="evidence-query mono text-xs mt-2">${escapeHtml(item.metric_or_query || '')}</div>
    `;
    container.appendChild(card);
  });
}

export function renderRolloutVerification(summary) {
  const card = document.getElementById('rolloutVerificationCard');
  if (!card) return;
  card.style.display = 'block';

  const idLabel = document.getElementById('execIdLabel');
  if (idLabel) idLabel.textContent = summary.execution_id || 'exec-done';

  const resBadge = document.getElementById('execResolutionBadge');
  if (resBadge) {
    resBadge.textContent = summary.resolution_status || 'RESOLVED';
    resBadge.className = summary.resolution_status === 'RESOLVED' ? 'status-pill status-healthy' : 'status-pill status-danger';
  }

  const mutStatus = document.getElementById('execMutationStatus');
  if (mutStatus) mutStatus.textContent = summary.mutation_status || 'SUCCESS';

  const rollStatus = document.getElementById('execRolloutStatus');
  if (rollStatus) rollStatus.textContent = summary.rollout_status || 'HEALTHY';

  const repVerif = document.getElementById('execReplicasVerified');
  if (repVerif) repVerif.textContent = `${summary.ready_replicas ?? '--'} / ${summary.desired_replicas ?? '--'}`;

  const jsonBox = document.getElementById('execVerificationJson');
  if (jsonBox) {
    jsonBox.textContent = JSON.stringify(summary.verification || summary, null, 2);
  }
}
