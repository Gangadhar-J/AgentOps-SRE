/**
 * AgentOps SRE - Authoritative ES Module Coordinator (v0.9.0)
 * Mounts modular subsystems, binds window handlers for HTML event compatibility,
 * and orchestrates startup initialization and background telemetry intervals.
 */

import { fetchJson, escapeHtml, formatTime } from './api.js';
import { switchSection, navigateToEvidence, switchMode } from './navigation.js';
import {
  loadClusterOverview,
  fetchNamespaces,
  fetchWorkloadsForSelect,
  onInvNamespaceChange,
  onClusterNamespaceChange,
  onClusterWorkloadChange,
  loadClusterWorkloadData,
  fetchTelemetryPulse,
  pollTelemetryPulse,
} from './cluster.js';
import {
  fetchStatus,
  updateDiagnosticsMatrix,
  updateOverviewActiveIncident,
  fetchEvalSummary,
  toggleChaosDrawer,
  triggerChaosScenario,
  triggerScenario,
} from './status.js';
import {
  fetchLLMModels,
  parseProviderAndModel,
  updateLifecycleStepper,
  fetchLLMHistory,
} from './models.js';
import {
  updateApprovalsList,
  fetchApprovals,
  approveCurrentIncident,
  rejectCurrentIncident,
  approveSpecificId,
  rejectSpecificId,
  submitApproval,
  submitRejection,
  setCurrentApprovalId,
  getCurrentApprovalId,
} from './approvals.js';
import { loadInvestigationsQueue } from './queue.js';
import {
  startInvestigation,
  cancelCurrentInvestigation,
  resumeActiveInvestigation,
  getActiveJobId,
  getCurrentIncident,
  attachStreamListener,
  showProgressCard,
  renderIncidentReport,
  renderFailureReport,
  renderEvidenceExplorer,
  renderRolloutVerification,
} from './investigation.js';
import {
  initDashboards,
  selectDashboard,
  reloadDashboardFrame,
  updateDashboardFrame,
} from './dashboards.js';
import { loadAlertsHistory, sendTestAlert } from './alerts.js';

// ==================== BIND TO WINDOW FOR HTML EVENT ATTRIBUTES ====================
// Navigation
window.switchSection = switchSection;
window.navigateToEvidence = navigateToEvidence;
window.switchMode = switchMode;

// Cluster & Telemetry
window.loadClusterOverview = loadClusterOverview;
window.fetchNamespaces = fetchNamespaces;
window.fetchWorkloadsForSelect = fetchWorkloadsForSelect;
window.onInvNamespaceChange = onInvNamespaceChange;
window.onClusterNamespaceChange = onClusterNamespaceChange;
window.onClusterWorkloadChange = onClusterWorkloadChange;
window.loadClusterWorkloadData = loadClusterWorkloadData;
window.fetchTelemetryPulse = fetchTelemetryPulse;
window.pollTelemetryPulse = pollTelemetryPulse;

// Status, Diagnostics & Chaos
window.fetchStatus = fetchStatus;
window.updateDiagnosticsMatrix = updateDiagnosticsMatrix;
window.updateOverviewActiveIncident = updateOverviewActiveIncident;
window.fetchEvalSummary = fetchEvalSummary;
window.toggleChaosDrawer = toggleChaosDrawer;
window.triggerChaosScenario = triggerChaosScenario;
window.triggerScenario = triggerScenario;

// Models & Execution History
window.fetchLLMModels = fetchLLMModels;
window.parseProviderAndModel = parseProviderAndModel;
window.updateLifecycleStepper = updateLifecycleStepper;
window.fetchLLMHistory = fetchLLMHistory;

// Approvals & Remediation
window.updateApprovalsList = updateApprovalsList;
window.fetchApprovals = fetchApprovals;
window.approveCurrentIncident = approveCurrentIncident;
window.rejectCurrentIncident = rejectCurrentIncident;
window.approveSpecificId = approveSpecificId;
window.rejectSpecificId = rejectSpecificId;
window.submitApproval = submitApproval;
window.submitRejection = submitRejection;
window.setCurrentApprovalId = setCurrentApprovalId;
window.getCurrentApprovalId = getCurrentApprovalId;

// Investigations & Streaming
window.startInvestigation = startInvestigation;
window.cancelCurrentInvestigation = cancelCurrentInvestigation;
window.resumeActiveInvestigation = resumeActiveInvestigation;
window.getActiveJobId = getActiveJobId;
window.getCurrentIncident = getCurrentIncident;
window.attachStreamListener = attachStreamListener;
window.showProgressCard = showProgressCard;
window.renderIncidentReport = renderIncidentReport;
window.renderFailureReport = renderFailureReport;
window.renderEvidenceExplorer = renderEvidenceExplorer;
window.renderRolloutVerification = renderRolloutVerification;

// Investigations Queue
window.loadInvestigationsQueue = loadInvestigationsQueue;

// Dashboards & Alerts
window.initDashboards = initDashboards;
window.selectDashboard = selectDashboard;
window.reloadDashboardFrame = reloadDashboardFrame;
window.updateDashboardFrame = updateDashboardFrame;
window.loadAlertsHistory = loadAlertsHistory;
window.sendTestAlert = sendTestAlert;

// Global Utilities
window.escapeHtml = escapeHtml;
window.formatTime = formatTime;

/**
 * Reopen or view any investigation job from the queue or direct link.
 */
window.viewInvestigationJob = async function (jobId) {
  if (!jobId) return;
  window.switchSection('investigation');

  const { ok, data } = await fetchJson(`/api/investigations/${jobId}`);
  if (!ok || !data) {
    alert(`Could not load investigation ${jobId}`);
    return;
  }

  if (['QUEUED', 'RUNNING'].includes(data.status)) {
    showProgressCard(data);
    attachStreamListener(jobId);
  } else if (data.result) {
    const progCard = document.getElementById('investigationProgressCard');
    if (progCard) progCard.style.display = 'none';
    renderIncidentReport(data.result);
  } else if (data.status === 'SUCCEEDED') {
    const { ok: rOk, data: rData } = await fetchJson(`/api/investigations/${jobId}/result`);
    const progCard = document.getElementById('investigationProgressCard');
    if (progCard) progCard.style.display = 'none';
    if (rOk && rData) {
      renderIncidentReport(rData);
    }
  } else if (data.status === 'FAILED' || data.error_json) {
    const progCard = document.getElementById('investigationProgressCard');
    if (progCard) progCard.style.display = 'none';
    renderFailureReport(data);
  }
};

/**
 * Single authoritative application bootstrap.
 */
async function initApp() {
  console.log('AgentOps SRE v0.9.0 authoritative ES Modules initialized.');

  // Core status and initial queues
  try { await fetchStatus(); } catch (e) { console.debug('fetchStatus error:', e); }
  try { await fetchTelemetryPulse(); } catch (e) { console.debug('fetchTelemetryPulse error:', e); }
  try { await loadInvestigationsQueue(); } catch (e) { console.debug('loadInvestigationsQueue error:', e); }
  try { await fetchEvalSummary(); } catch (e) { console.debug('fetchEvalSummary error:', e); }

  // Discovery & cluster inventory
  try { await fetchLLMModels(); } catch (e) { console.debug('fetchLLMModels error:', e); }
  try { await fetchNamespaces(); } catch (e) { console.debug('fetchNamespaces error:', e); }
  try { await loadClusterOverview(); } catch (e) { console.debug('loadClusterOverview error:', e); }
  try { await loadClusterWorkloadData(); } catch (e) { console.debug('loadClusterWorkloadData error:', e); }

  // Section auxiliary loads
  try { await fetchLLMHistory(); } catch (e) { console.debug('fetchLLMHistory error:', e); }
  try { await initDashboards(); } catch (e) { console.debug('initDashboards error:', e); }
  try { await loadAlertsHistory(); } catch (e) { console.debug('loadAlertsHistory error:', e); }

  // Check and resume any running investigation
  try { await resumeActiveInvestigation(); } catch (e) { console.debug('resumeActiveInvestigation error:', e); }

  // Establish background polling intervals
  setInterval(() => {
    fetchStatus();
  }, 5000);

  setInterval(() => {
    fetchTelemetryPulse();
  }, 10000);

  setInterval(() => {
    loadInvestigationsQueue();
  }, 10000);
}

document.addEventListener('DOMContentLoaded', initApp);
