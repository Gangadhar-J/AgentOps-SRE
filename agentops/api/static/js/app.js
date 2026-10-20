/**
 * AgentOps SRE - Native ES Module Coordinator (v0.8.0)
 * Mounts modules, binds window handlers for HTML onclick attributes,
 * and initializes SSE progress and dashboards.
 */

import { fetchJson } from './api.js';
import {
  initDashboards,
  selectDashboard,
  reloadDashboardFrame,
  updateDashboardFrame,
} from './dashboards.js';
import { loadAlertsHistory, sendTestAlert } from './alerts.js';
import {
  startInvestigation,
  cancelCurrentInvestigation,
  resumeActiveInvestigation,
  getActiveJobId,
} from './investigation.js';

// Bind to window for HTML event attributes
window.initDashboards = initDashboards;
window.selectDashboard = selectDashboard;
window.reloadDashboardFrame = reloadDashboardFrame;
window.updateDashboardFrame = updateDashboardFrame;
window.loadAlertsHistory = loadAlertsHistory;
window.sendTestAlert = sendTestAlert;
window.startInvestigation = startInvestigation;
window.cancelCurrentInvestigation = cancelCurrentInvestigation;
window.resumeActiveInvestigation = resumeActiveInvestigation;
window.getActiveJobId = getActiveJobId;

window.viewInvestigationJob = async function (jobId) {
  if (!jobId) return;
  window.switchSection('investigation');
  const { ok, data } = await fetchJson(`/api/investigations/${jobId}`);
  if (ok && data) {
    if (['QUEUED', 'RUNNING'].includes(data.status)) {
      import('./investigation.js').then((m) => {
        m.attachStreamListener(jobId);
      });
    } else if (data.result) {
      import('./investigation.js').then((m) => {
        m.renderIncidentReport(data.result);
      });
    }
  }
};

document.addEventListener('DOMContentLoaded', async () => {
  console.log('AgentOps SRE v0.8.0 ES Modules loaded.');
  // Initialize dashboards and alerts history
  try {
    await initDashboards();
  } catch (e) {
    console.debug('Dashboard init error:', e);
  }

  try {
    await loadAlertsHistory();
  } catch (e) {
    console.debug('Alerts history load error:', e);
  }

  try {
    await resumeActiveInvestigation();
  } catch (e) {
    console.debug('Investigation resume error:', e);
  }
});
