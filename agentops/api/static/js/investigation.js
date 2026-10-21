/**
 * AgentOps SRE - Asynchronous Investigation & SSE Progress Streaming Module
 */

import { fetchJson, connectSSE } from './api.js';

let activeJobId = null;
let activeEventSource = null;
let progressTimerInterval = null;
let jobStartTime = null;
let lastReceivedEventId = null;

export function getActiveJobId() {
  return activeJobId;
}

export async function startInvestigation() {
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
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm"></span> Submitting Job...';
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
    return;
  }

  activeJobId = data.job_id;
  localStorage.setItem('agentops_active_job_id', activeJobId);

  // Switch to progress view
  showProgressCard(data);
  attachStreamListener(activeJobId);
}

function showProgressCard(jobData) {
  const progCard = document.getElementById('investigationProgressCard');
  const resultsCard = document.getElementById('investigationResultsCard');
  if (resultsCard) resultsCard.style.display = 'none';
  if (!progCard) return;

  progCard.style.display = 'block';
  document.getElementById('progJobId').textContent = jobData.job_id;
  document.getElementById('progCurrentStageBadge').textContent = (jobData.stage || 'QUEUED').toUpperCase();
  document.getElementById('progCurrentStageBadge').className = 'stage-badge stage-queued';
  document.getElementById('progCurrentMessage').textContent = 'Investigation enqueued into durable SQLite store...';

  const eventsList = document.getElementById('progEventsList');
  if (eventsList) {
    eventsList.innerHTML = `<div class="prog-event-item">
      <span class="prog-event-time">${new Date().toLocaleTimeString()}</span>
      <span class="prog-event-stage stage-queued">QUEUED</span>
      <span class="prog-event-msg">Investigation accepted (Job: ${jobData.job_id})</span>
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
    onComplete: (donePayload) => {
      onInvestigationFinished(jobId);
    },
  });
}

function handleProgressEvent(event) {
  const stage = event.stage || 'progress';
  const msg = event.message || '';

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

  // Append to ordered events stream
  const eventsList = document.getElementById('progEventsList');
  if (eventsList) {
    const row = document.createElement('div');
    row.className = 'prog-event-item';
    row.innerHTML = `
      <span class="prog-event-time">${formatTime(event.timestamp)}</span>
      <span class="prog-event-stage stage-${stage}">${stage.toUpperCase()}</span>
      <span class="prog-event-msg">${escapeHtml(msg)}</span>
    `;
    eventsList.appendChild(row);
    eventsList.scrollTop = eventsList.scrollHeight;
  }

  if (stage === 'completed' || stage === 'failed' || stage === 'cancelled') {
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
  } else {
    // Check if error state
    const jobRes = await fetchJson(`/api/investigations/${jobId}`);
    if (jobRes.ok && jobRes.data?.error_json) {
      renderFailureReport(jobRes.data);
    }
  }
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

  const { ok, data } = await fetchJson(`/api/investigations/${activeJobId}/cancel`, {
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
  const card = document.getElementById('investigationResultsCard');
  if (!card) return;
  card.style.display = 'block';

  document.getElementById('invIncidentIdLabel').textContent = report.incident_id || '--';
  document.getElementById('diagIncidentType').textContent = report.incident_type || 'Unknown';
  document.getElementById('diagConfidence').textContent = `${Math.round((report.confidence || 0) * 100)}%`;
  document.getElementById('diagSeverity').textContent = report.risk_level || 'MEDIUM';
  document.getElementById('diagSource').textContent = report.source || 'MANUAL';

  document.getElementById('rcaSummaryText').textContent = report.summary || '--';
  document.getElementById('rcaRootCauseText').textContent = report.root_cause || '--';

  // Status badges
  const statusBadge = document.getElementById('invStatusBadge');
  if (statusBadge) {
    statusBadge.textContent = report.status;
    statusBadge.className = report.status === 'FAILED' ? 'status-pill status-danger' : 'status-pill status-healthy';
  }

  const valBadge = document.getElementById('invValidationBadge');
  if (valBadge) {
    valBadge.textContent = report.validation_passed ? 'VALIDATED' : 'UNVALIDATED';
    valBadge.className = report.validation_passed ? 'status-pill status-info' : 'status-pill status-danger';
  }

  // Remediation
  document.getElementById('recActionText').textContent = report.recommended_action || 'none';
  document.getElementById('recApprovalRequiredText').textContent = report.approval_required ? 'REQUIRED' : 'NONE';
  document.getElementById('recRiskLevelText').textContent = report.risk_level || 'NONE';
  document.getElementById('recPolicyReasonText').textContent = report.policy_reason || '--';

  // Policy decision pill
  const polBadge = document.getElementById('policyDecisionBadge');
  if (polBadge) {
    polBadge.textContent = report.policy_decision || 'NOT_EVALUATED';
    polBadge.className = report.policy_decision === 'REQUIRE_APPROVAL'
      ? 'status-pill status-warning'
      : (report.policy_decision === 'ALLOW' ? 'status-pill status-healthy' : 'status-pill status-danger');
  }

  // Inline approval card if pending
  const inlineBox = document.getElementById('inlineApprovalActionBox');
  if (inlineBox) {
    if (report.approval_required && report.approval_id) {
      inlineBox.style.display = 'block';
      const label = document.getElementById('inlineApprovalIdLabel');
      if (label) label.textContent = report.approval_id;
    } else {
      inlineBox.style.display = 'none';
    }
  }

  // Update LLM Runtime Observability if runtime metrics present
  if (report.llm_runtime) {
    renderLLMRuntimeObservability(report.llm_runtime);
  }
}

function renderFailureReport(jobData) {
  const card = document.getElementById('investigationResultsCard');
  if (!card) return;
  card.style.display = 'block';

  document.getElementById('invIncidentIdLabel').textContent = jobData.incident_id || '--';
  document.getElementById('diagIncidentType').textContent = 'FAILED';
  document.getElementById('diagConfidence').textContent = '0%';
  document.getElementById('rcaSummaryText').textContent = 'Investigation execution encountered a fatal error.';
  document.getElementById('rcaRootCauseText').textContent = jobData.error_json?.error || 'Unknown runtime error.';

  const failBanner = document.getElementById('invFailureBanner');
  if (failBanner) {
    failBanner.style.display = 'block';
    document.getElementById('invFailureReason').textContent = jobData.error_json?.error || 'Investigation failed';
  }
}

function renderLLMRuntimeObservability(llm) {
  const modelEl = document.getElementById('llmObservabilityModel');
  if (modelEl) modelEl.textContent = `${llm.model} (${llm.provider})`;

  const latencyEl = document.getElementById('llmObservabilityLatency');
  if (latencyEl) latencyEl.textContent = `${llm.latency_seconds}s`;

  const tokensEl = document.getElementById('llmObservabilityTokens');
  if (tokensEl) tokensEl.textContent = `${llm.prompt_tokens || 0} / ${llm.completion_tokens || 0} / ${llm.total_tokens || 0}`;

  const tpsEl = document.getElementById('llmObservabilityTPS');
  if (tpsEl) tpsEl.textContent = llm.tokens_per_second ? `${llm.tokens_per_second} tok/s` : '--';
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatTime(isoStr) {
  if (!isoStr) return '';
  try {
    return new Date(isoStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch (e) {
    return isoStr;
  }
}
