/**
 * AgentOps SRE - Cluster & Workload Management Module
 */

import { fetchJson, escapeHtml } from './api.js';

export async function loadClusterOverview() {
  try {
    const { ok, data: resData } = await fetchJson('/api/cluster/overview');
    if (!ok || !resData) return;
    const data = resData.cluster || resData;

    const tbody = document.getElementById('nodesTableBody');
    if (tbody) {
      if (!data.connected || !data.nodes || data.nodes.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No cluster nodes reported or cluster offline.</td></tr>`;
      } else {
        tbody.innerHTML = '';
        data.nodes.forEach((node) => {
          const tr = document.createElement('tr');
          const isReady = node.ready === true || node.status === 'Ready';
          const statusText = node.status || (isReady ? 'Ready' : 'NotReady');
          const condText = node.condition_reason || node.condition || 'Ready';
          const archText = node.architecture || node.arch || '--';
          tr.innerHTML = `
            <td class="mono font-bold">${escapeHtml(node.name)}</td>
            <td><span class="status-pill ${isReady ? 'status-healthy' : 'status-danger'}">${escapeHtml(statusText)}</span></td>
            <td>${escapeHtml(condText)}</td>
            <td class="mono text-xs">${escapeHtml(node.kubelet_version || '--')}</td>
            <td class="text-xs">${escapeHtml(node.os_image || '--')}</td>
            <td class="text-xs">${escapeHtml(archText)}</td>
          `;
          tbody.appendChild(tr);
        });
      }
    }

    const readyEl = document.getElementById('overviewNodesReady');
    if (readyEl) readyEl.textContent = `${data.nodes_ready ?? 0} / ${data.nodes_count ?? data.node_count ?? 0}`;

    const ctxEl = document.getElementById('overviewContextName');
    if (ctxEl) ctxEl.textContent = data.current_context || '--';

    const authEl = document.getElementById('overviewAuthMode');
    if (authEl) authEl.textContent = data.auth_mode || 'kubeconfig';

    const nsCountEl = document.getElementById('overviewNsCount');
    if (nsCountEl) nsCountEl.textContent = data.namespaces_count ?? data.namespace_count ?? '--';
  } catch (err) {
    console.error('Failed to load cluster overview:', err);
  }
}

export async function fetchNamespaces() {
  try {
    const { ok, data } = await fetchJson('/api/cluster/namespaces');
    if (!ok || !data) return;
    const namespaces = data.namespaces || ['demo', 'default'];

    const populateNsSelect = (selectId) => {
      const sel = document.getElementById(selectId);
      if (!sel) return;
      const currentVal = sel.value;
      sel.innerHTML = '';
      namespaces.forEach((ns) => {
        const opt = document.createElement('option');
        opt.value = ns;
        opt.textContent = ns;
        if (ns === currentVal || (!currentVal && ns === 'demo')) {
          opt.selected = true;
        }
        sel.appendChild(opt);
      });
    };

    populateNsSelect('invNamespaceSelect');
    populateNsSelect('clusterNsSelect');
    populateNsSelect('realNamespaceSelect');

    await fetchWorkloadsForSelect('invNamespaceSelect', 'invWorkloadSelect');
    await fetchWorkloadsForSelect('clusterNsSelect', 'clusterWlSelect');
  } catch (err) {
    console.error('Failed to fetch namespaces:', err);
  }
}

export async function fetchWorkloadsForSelect(nsSelectId, wlSelectId) {
  const nsEl = document.getElementById(nsSelectId);
  const wlEl = document.getElementById(wlSelectId);
  if (!nsEl || !wlEl) return;
  const ns = nsEl.value || 'demo';

  try {
    const { ok, data } = await fetchJson(`/api/cluster/workloads?namespace=${encodeURIComponent(ns)}`);
    if (!ok || !data) return;
    const currentVal = wlEl.value;

    wlEl.innerHTML = '';
    const workloads = data.workloads || [];
    if (workloads.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = '(No deployments found)';
      wlEl.appendChild(opt);
    } else {
      workloads.forEach((wl) => {
        const opt = document.createElement('option');
        opt.value = wl;
        opt.textContent = wl;
        if (wl === currentVal || (!currentVal && wl === 'demo-app')) {
          opt.selected = true;
        }
        wlEl.appendChild(opt);
      });
    }
  } catch (err) {
    console.error(`Failed to fetch workloads for ${ns}:`, err);
  }
}

export function onInvNamespaceChange() {
  fetchWorkloadsForSelect('invNamespaceSelect', 'invWorkloadSelect');
}

export function onClusterNamespaceChange() {
  fetchWorkloadsForSelect('clusterNsSelect', 'clusterWlSelect').then(() => {
    loadClusterWorkloadData();
  });
}

export function onClusterWorkloadChange() {
  loadClusterWorkloadData();
}

export async function loadClusterWorkloadData() {
  const nsEl = document.getElementById('clusterNsSelect');
  const wlEl = document.getElementById('clusterWlSelect');
  if (!nsEl || !wlEl) return;
  const ns = nsEl.value || 'demo';
  const wl = wlEl.value || 'demo-app';

  try {
    const [podsRes, eventsRes] = await Promise.all([
      fetchJson(`/api/cluster/pods?namespace=${encodeURIComponent(ns)}&workload=${encodeURIComponent(wl)}`),
      fetchJson(`/api/cluster/events?namespace=${encodeURIComponent(ns)}&workload=${encodeURIComponent(wl)}`),
    ]);

    const podsBody = document.getElementById('workloadPodsBody');
    if (podsBody && podsRes.ok && podsRes.data) {
      const pods = podsRes.data.pods || [];
      if (pods.length === 0) {
        podsBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No pods found for ${escapeHtml(ns)}/${escapeHtml(wl)}</td></tr>`;
      } else {
        podsBody.innerHTML = '';
        pods.forEach((p) => {
          const tr = document.createElement('tr');
          const podName = p.pod_name || p.name || '--';
          const isReady = p.is_ready !== undefined ? p.is_ready : (p.ready !== undefined ? p.ready : false);
          const stateReason = p.current_state_reason || p.state_reason || '--';
          const termReason = p.last_termination_reason || p.termination_reason || '--';
          tr.innerHTML = `
            <td class="mono font-bold">${escapeHtml(podName)}</td>
            <td><span class="status-pill ${p.phase === 'Running' ? 'status-healthy' : 'status-danger'}">${escapeHtml(p.phase)}</span></td>
            <td>${isReady ? '✓ Ready' : '✗ Not Ready'}</td>
            <td><strong class="${p.restart_count > 0 ? 'text-danger' : ''}">${p.restart_count ?? 0}</strong></td>
            <td class="mono text-xs">${escapeHtml(stateReason)}</td>
            <td class="text-xs text-muted">${escapeHtml(termReason)}</td>
          `;
          podsBody.appendChild(tr);
        });
      }
    }

    const eventsBox = document.getElementById('workloadEventsStream');
    if (eventsBox && eventsRes.ok && eventsRes.data) {
      const events = eventsRes.data.events || [];
      if (events.length === 0) {
        eventsBox.innerHTML = `<p class="text-muted text-sm">No recent warning events detected for this workload.</p>`;
      } else {
        eventsBox.innerHTML = '';
        events.forEach((ev) => {
          const div = document.createElement('div');
          div.className = 'event-entry';
          div.innerHTML = `
            <div style="display:flex; justify-content:space-between; margin-bottom:2px;">
              <strong class="text-danger">${escapeHtml(ev.reason || 'Warning')}</strong>
              <span class="text-muted text-xs">${escapeHtml(ev.last_timestamp || 'recent')} (x${ev.count || 1})</span>
            </div>
            <div style="color:#cbd5e1;">${escapeHtml(ev.message || '')}</div>
          `;
          eventsBox.appendChild(div);
        });
      }
    }
  } catch (err) {
    console.error('Failed to load workload data:', err);
  }
}

export async function fetchTelemetryPulse() {
  const nsEl = document.getElementById('invNamespaceSelect') || document.getElementById('clusterNsSelect');
  const wlEl = document.getElementById('invWorkloadSelect') || document.getElementById('clusterWlSelect');
  const ns = nsEl?.value || 'demo';
  const wl = wlEl?.value || 'demo-app';

  const targetLabel = document.getElementById('pulseTargetLabel');
  if (targetLabel) targetLabel.textContent = `${ns}/${wl}`;

  try {
    const { ok, data } = await fetchJson(`/api/telemetry/pulse?namespace=${encodeURIComponent(ns)}&workload=${encodeURIComponent(wl)}`);
    if (!ok || !data) return;

    const badge = document.getElementById('pulseBadge');
    if (badge) {
      const st = (data.pulse_status || 'UNKNOWN').toUpperCase();
      badge.textContent = st;
      badge.className = st === 'HEALTHY' ? 'pulse-badge pulse-healthy' : (st === 'DEGRADED' ? 'pulse-badge pulse-warning' : 'pulse-badge pulse-danger');
    }

    const k8s = data.k8s || {};
    const prom = data.prometheus || {};

    const readyPods = document.getElementById('pulseReadyPods');
    if (readyPods) readyPods.textContent = `${k8s.ready_pods ?? '--'} / ${k8s.desired_replicas ?? '--'}`;

    const restarts = document.getElementById('pulseRestarts');
    if (restarts) restarts.textContent = k8s.total_restarts ?? '--';

    const errRate = document.getElementById('pulseErrorRate');
    if (errRate) errRate.textContent = prom.error_rate_pct !== null && prom.error_rate_pct !== undefined ? `${prom.error_rate_pct.toFixed(1)}%` : '--';

    const latency = document.getElementById('pulseLatency');
    if (latency) latency.textContent = prom.p95_latency_s !== null && prom.p95_latency_s !== undefined ? `${prom.p95_latency_s.toFixed(3)}s` : '--';

    const memory = document.getElementById('pulseMemory');
    if (memory) memory.textContent = prom.memory_mb !== null && prom.memory_mb !== undefined ? `${prom.memory_mb.toFixed(1)} MB` : '--';

    const warnings = document.getElementById('pulseWarnings');
    if (warnings) warnings.textContent = k8s.warnings_count ?? 0;
  } catch (err) {
    console.debug('Telemetry pulse fetch failed:', err);
  }
}

// Backward compatibility alias
export const pollTelemetryPulse = fetchTelemetryPulse;
