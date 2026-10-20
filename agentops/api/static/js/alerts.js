/**
 * AgentOps SRE - Alertmanager Webhook & Events Module
 */

import { fetchJson } from './api.js';

export async function loadAlertsHistory() {
  const tbody = document.getElementById('alertsHistoryBody');
  if (!tbody) return;

  const { ok, data } = await fetchJson('/api/alerts/history?limit=25');
  if (!ok || !data || !data.alerts || data.alerts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No alert events recorded yet.</td></tr>`;
    const pill = document.getElementById('firingAlertsPill');
    if (pill) pill.style.display = 'none';
    return;
  }

  let firingCount = 0;
  tbody.innerHTML = data.alerts.map((a) => {
    const isFiring = a.last_status === 'firing';
    if (isFiring) firingCount++;

    const statusBadge = isFiring
      ? '<span class="status-pill status-danger">FIRING</span>'
      : '<span class="status-pill status-healthy">RESOLVED</span>';

    const linkedJob = a.job_id
      ? `<button class="btn-text-action mono" onclick="window.viewInvestigationJob('${a.job_id}')">${a.job_id}</button>`
      : '<span class="text-muted">None</span>';

    return `
      <tr>
        <td class="font-bold">${escapeHtml(a.alert_name)}</td>
        <td class="mono text-xs">${escapeHtml(a.namespace)}/${escapeHtml(a.workload)}</td>
        <td>${statusBadge}</td>
        <td class="mono">${a.count}</td>
        <td class="text-xs text-muted">${formatTimestamp(a.last_seen_at)}</td>
        <td>${linkedJob}</td>
      </tr>
    `;
  }).join('');

  const pill = document.getElementById('firingAlertsPill');
  if (pill) {
    pill.style.display = firingCount > 0 ? 'inline-block' : 'none';
    pill.textContent = firingCount;
  }
}

export async function sendTestAlert() {
  const alertName = document.getElementById('testAlertName')?.value || 'DemoAppCrashLoop';
  const workload = document.getElementById('testAlertWorkload')?.value || 'demo-app';
  const feedback = document.getElementById('testAlertFeedback');

  if (feedback) {
    feedback.style.display = 'block';
    feedback.className = 'mt-2 text-xs mono text-muted';
    feedback.textContent = 'Sending webhook to /api/v1/alerts...';
  }

  const payload = {
    version: '4',
    status: 'firing',
    receiver: 'agentops-webhook',
    groupLabels: { alertname: alertName, namespace: 'demo', app: workload },
    commonLabels: { alertname: alertName, namespace: 'demo', app: workload, severity: 'critical' },
    commonAnnotations: { summary: `Synthetic test alert ${alertName} triggered from console.` },
    alerts: [
      {
        status: 'firing',
        labels: { alertname: alertName, namespace: 'demo', app: workload, severity: 'critical' },
        annotations: { summary: `Synthetic test alert ${alertName} triggered from console.` },
        startsAt: new Date().toISOString(),
      },
    ],
  };

  const { ok, status, data } = await fetchJson('/api/v1/alerts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

  if (feedback) {
    if (ok) {
      feedback.className = 'mt-2 text-xs mono text-success';
      const result = data.results && data.results[0] ? data.results[0] : {};
      feedback.textContent = `✓ [${status}] Alert accepted: status=${result.status}, job=${result.job_id || 'deduplicated'}`;
      // Reload alerts table
      setTimeout(loadAlertsHistory, 800);
    } else {
      feedback.className = 'mt-2 text-xs mono text-danger';
      feedback.textContent = `✕ [${status}] Error: ${JSON.stringify(data || {})}`;
    }
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatTimestamp(isoStr) {
  if (!isoStr) return '--';
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch (e) {
    return isoStr;
  }
}
