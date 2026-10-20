/**
 * AgentOps SRE - Grafana Dashboards Integration Module
 */

import { fetchJson } from './api.js';

let currentDashboardId = 'cluster-overview';
let grafanaBaseUrl = 'http://localhost:30300';

export async function initDashboards() {
  const { ok, data } = await fetchJson('/api/grafana/dashboards');
  if (ok && data) {
    grafanaBaseUrl = data.grafana_url || grafanaBaseUrl;
    const connBadge = document.getElementById('grafanaConnBadge');
    if (connBadge) {
      connBadge.className = data.connected ? 'status-pill status-healthy' : 'status-pill status-danger';
      connBadge.textContent = data.connected ? 'CONNECTED' : 'UNREACHABLE';
    }

    const extLink = document.getElementById('grafanaExternalLink');
    if (extLink) {
      extLink.href = grafanaBaseUrl;
    }
  }

  // Load active dashboard
  await updateDashboardFrame();
}

export async function selectDashboard(dashId) {
  currentDashboardId = dashId;

  // Update active button state
  document.querySelectorAll('.btn-dash').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-dash-id') === dashId);
  });

  await updateDashboardFrame();
}

export async function updateDashboardFrame() {
  const ns = document.getElementById('invNamespaceSelect')?.value || 'demo';
  const wl = document.getElementById('invWorkloadSelect')?.value || 'demo-app';
  const timeRange = document.getElementById('dashTimeRangeSelect')?.value || 'now-1h';

  const params = new URLSearchParams({
    dashboard_id: currentDashboardId,
    namespace: ns,
    workload: wl,
    from: timeRange,
    to: 'now',
  });

  const { ok, data } = await fetchJson(`/api/grafana/url?${params.toString()}`);
  if (ok && data) {
    const frame = document.getElementById('grafanaFrame');
    const directLink = document.getElementById('dashDirectLink');
    const fallbackNotice = document.getElementById('dashFallbackNotice');

    if (frame) {
      frame.src = data.embed_url;
    }

    if (directLink) {
      directLink.href = data.direct_url;
    }

    if (fallbackNotice) {
      fallbackNotice.style.display = 'block';
    }
  }
}

export function reloadDashboardFrame() {
  const frame = document.getElementById('grafanaFrame');
  if (frame && frame.src) {
    frame.src = frame.src; // Reloads iframe
  }
}
