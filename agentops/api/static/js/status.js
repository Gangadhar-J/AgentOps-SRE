/**
 * AgentOps SRE - System Status, Health Polling & Chaos Sandbox Module
 */

import { fetchJson, escapeHtml } from './api.js';

export async function fetchStatus() {
  try {
    const { ok, data } = await fetchJson('/api/status');
    if (!ok || !data) return;
    const comps = data.components || {};

    // Header Badges
    const k8sBadge = document.getElementById('k8sBadge');
    if (k8sBadge) {
      if (comps.kubernetes && comps.kubernetes.connected) {
        k8sBadge.className = 'badge badge-success';
        k8sBadge.innerHTML = `<span class="dot"></span> K8s: Connected (${comps.kubernetes.namespace_count} ns)`;
      } else {
        k8sBadge.className = 'badge badge-danger';
        k8sBadge.innerHTML = '<span class="dot"></span> K8s: Offline';
      }
    }

    const promBadge = document.getElementById('promBadge');
    if (promBadge) {
      if (comps.prometheus && comps.prometheus.connected) {
        promBadge.className = 'badge badge-success';
        promBadge.innerHTML = '<span class="dot"></span> Prom: Active';
      } else {
        promBadge.className = 'badge badge-neutral';
        promBadge.innerHTML = '<span class="dot"></span> Prom: Down';
      }
    }

    const lokiBadge = document.getElementById('lokiBadge');
    if (lokiBadge) {
      if (comps.loki && comps.loki.connected) {
        lokiBadge.className = 'badge badge-success';
        lokiBadge.innerHTML = '<span class="dot"></span> Loki: Active';
      } else {
        lokiBadge.className = 'badge badge-neutral';
        lokiBadge.innerHTML = '<span class="dot"></span> Loki: Down';
      }
    }

    const ollamaBadge = document.getElementById('ollamaBadge');
    if (ollamaBadge) {
      if (comps.ollama && comps.ollama.connected) {
        ollamaBadge.className = 'badge badge-info';
        ollamaBadge.innerHTML = `<span class="badge-icon">🦙</span> Ollama: ${comps.ollama.model_count} model(s)`;
      } else {
        ollamaBadge.className = 'badge badge-neutral';
        ollamaBadge.innerHTML = '<span class="badge-icon">🦙</span> Ollama: Offline';
      }
    }

    const incBadge = document.getElementById('incidentBadge');
    if (incBadge) {
      if (data.active_incident) {
        const st = data.active_incident.status;
        incBadge.className = st === 'RESOLVED' ? 'badge badge-success' : (st === 'PENDING_APPROVAL' ? 'badge badge-warning' : 'badge badge-danger');
        incBadge.innerHTML = `<span class="dot"></span> ${st}`;
      } else {
        incBadge.className = 'badge badge-idle';
        incBadge.innerHTML = '<span class="dot"></span> Standby';
      }
    }

    // Section 1 Overview Elements
    const ovK8s = document.getElementById('overviewK8sStatus');
    if (ovK8s && comps.kubernetes) {
      ovK8s.textContent = comps.kubernetes.connected ? 'CONNECTED' : 'OFFLINE';
      ovK8s.className = comps.kubernetes.connected ? 'status-pill status-healthy' : 'status-pill status-danger';
    }
    const ovNs = document.getElementById('overviewNsCount');
    if (ovNs && comps.kubernetes) ovNs.textContent = comps.kubernetes.namespace_count ?? '--';

    const ovProm = document.getElementById('overviewPromStatus');
    if (ovProm && comps.prometheus) ovProm.textContent = comps.prometheus.connected ? 'Active' : 'Down';

    const ovLoki = document.getElementById('overviewLokiStatus');
    if (ovLoki && comps.loki) ovLoki.textContent = comps.loki.connected ? 'Active' : 'Down';

    const ovGraf = document.getElementById('overviewGrafanaStatus');
    if (ovGraf && comps.grafana) ovGraf.textContent = comps.grafana.connected ? 'Active' : 'Down';

    const ovOll = document.getElementById('overviewOllamaCount');
    if (ovOll && comps.ollama) ovOll.textContent = comps.ollama.connected ? `${comps.ollama.model_count} model(s)` : 'Offline';

    // Section 8 Diagnostics Elements
    updateDiagnosticsMatrix(comps, data.cluster);

    // Pending Approvals List and Notification Pill
    const pendingApps = data.pending_approvals || [];
    const pill = document.getElementById('pendingApprovalsPill');
    if (pill) {
      if (pendingApps.length > 0) {
        pill.style.display = 'inline-block';
        pill.textContent = pendingApps.length;
      } else {
        pill.style.display = 'none';
      }
    }
    if (window.updateApprovalsList) {
      window.updateApprovalsList(pendingApps);
    }

    // Active Incident in Section 1
    updateOverviewActiveIncident(data.active_incident);
  } catch (err) {
    console.debug('Status polling failed:', err);
  }
}

export function updateDiagnosticsMatrix(comps, cluster) {
  const k8sBadge = document.getElementById('diagK8sBadge');
  const k8sText = document.getElementById('diagK8sDetails');
  if (k8sBadge && k8sText && comps.kubernetes) {
    k8sBadge.textContent = comps.kubernetes.connected ? 'CONNECTED' : 'OFFLINE';
    k8sBadge.className = comps.kubernetes.connected ? 'status-pill status-healthy' : 'status-pill status-danger';
    k8sText.textContent = comps.kubernetes.connected
      ? `Cluster context: ${cluster?.context || 'discovered'}, Namespaces: ${comps.kubernetes.namespace_count}`
      : `Disconnected: ${comps.kubernetes.error || 'kubectl cluster-info returned non-zero'}`;
  }

  const promBadge = document.getElementById('diagPromBadge');
  const promText = document.getElementById('diagPromDetails');
  if (promBadge && promText && comps.prometheus) {
    promBadge.textContent = comps.prometheus.connected ? 'CONNECTED' : 'OFFLINE';
    promBadge.className = comps.prometheus.connected ? 'status-pill status-healthy' : 'status-pill status-neutral';
    promText.textContent = comps.prometheus.connected ? 'Prometheus TSDB reachable via MCP' : 'Endpoint unreachable';
  }

  const grafBadge = document.getElementById('diagGrafanaBadge');
  const grafText = document.getElementById('diagGrafanaDetails');
  if (grafBadge && grafText && comps.grafana) {
    grafBadge.textContent = comps.grafana.connected ? 'CONNECTED' : 'OFFLINE';
    grafBadge.className = comps.grafana.connected ? 'status-pill status-healthy' : 'status-pill status-neutral';
    grafText.textContent = comps.grafana.connected ? 'Grafana HTTP endpoint reachable' : 'Endpoint unreachable';
  }

  const lokiBadge = document.getElementById('diagLokiBadge');
  const lokiText = document.getElementById('diagLokiDetails');
  if (lokiBadge && lokiText && comps.loki) {
    lokiBadge.textContent = comps.loki.connected ? 'CONNECTED' : 'OFFLINE';
    lokiBadge.className = comps.loki.connected ? 'status-pill status-healthy' : 'status-pill status-neutral';
    lokiText.textContent = comps.loki.connected ? 'Grafana Loki log aggregator reachable' : 'Endpoint unreachable';
  }

  const ollamaBadge = document.getElementById('diagOllamaBadge');
  const ollamaText = document.getElementById('diagOllamaDetails');
  if (ollamaBadge && ollamaText && comps.ollama) {
    ollamaBadge.textContent = comps.ollama.connected ? 'CONNECTED' : 'OFFLINE';
    ollamaBadge.className = comps.ollama.connected ? 'status-pill status-healthy' : 'status-pill status-neutral';
    ollamaText.textContent = comps.ollama.connected
      ? `Ollama API active with ${comps.ollama.model_count} local model(s)`
      : 'Ollama server offline or unreachable on configured host';
  }
}

export function updateOverviewActiveIncident(inc) {
  const statusEl = document.getElementById('overviewActiveStatus');
  const bodyEl = document.getElementById('overviewActiveBody');
  if (!statusEl || !bodyEl) return;

  if (!inc) {
    statusEl.textContent = 'STANDBY';
    statusEl.className = 'status-pill status-neutral';
    bodyEl.innerHTML = `<p class="text-muted">No active incident under investigation. Navigate to <strong>Incident Investigation</strong> to run an autonomous analysis.</p>`;
    return;
  }

  statusEl.textContent = inc.status;
  statusEl.className = inc.status === 'RESOLVED' ? 'status-pill status-healthy' : (inc.status === 'PENDING_APPROVAL' ? 'status-pill status-warning' : 'status-pill status-danger');

  bodyEl.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.75rem;">
      <div>
        <div class="mono font-bold text-accent">${escapeHtml(inc.incident_id)}</div>
        <div style="font-weight:700; margin-top:0.25rem;">${escapeHtml(inc.summary || 'Incident Diagnostic')}</div>
      </div>
      <button class="btn-sm btn-primary" onclick="switchSection('investigation')">View RCA &amp; Details →</button>
    </div>
    <div style="font-size:0.85rem; color:#cbd5e1; margin-bottom:0.5rem;">${escapeHtml(inc.root_cause || 'Analyzing incident telemetry...')}</div>
    <div style="display:flex; gap:0.5rem; align-items:center;">
      <span class="badge badge-sm badge-info">Type: ${escapeHtml(inc.incident_type || 'Unknown')}</span>
      <span class="badge badge-sm badge-warning">Confidence: ${Math.round((inc.confidence || 0) * 100)}%</span>
      <span class="badge badge-sm badge-neutral">Model: ${escapeHtml(inc.llm_runtime?.model || 'ollama')}</span>
    </div>
  `;
}

export async function fetchEvalSummary() {
  try {
    const { ok, data } = await fetchJson('/api/eval/summary');
    if (!ok || !data) return;

    const evalBadge = document.getElementById('evalBadge');
    const evalOverallScore = document.getElementById('evalOverallScore');
    const evalGateStatusBadge = document.getElementById('evalGateStatusBadge');

    if (data.status === 'ok') {
      const scorePct = Math.round(data.overall_score * 100);
      if (evalBadge) {
        evalBadge.className = data.passing ? 'badge badge-success' : 'badge badge-danger';
        evalBadge.innerHTML = `<span class="badge-icon">📊</span> Eval: ${scorePct}%`;
        evalBadge.title = `Deterministic Quality Gate: ${scorePct}% (${data.passing ? 'PASSED' : 'FAILED'})`;
      }
      if (evalOverallScore) evalOverallScore.textContent = `${scorePct}%`;
      if (evalGateStatusBadge) {
        evalGateStatusBadge.textContent = data.passing ? 'QUALITY GATE PASSED' : 'QUALITY GATE FAILED';
        evalGateStatusBadge.className = data.passing ? 'status-pill status-healthy' : 'status-pill status-danger';
      }
    }
  } catch (err) {
    console.debug('Eval summary fetch failed:', err);
  }
}

export function toggleChaosDrawer() {
  const drawer = document.getElementById('chaosDrawer');
  if (!drawer) return;
  drawer.style.display = drawer.style.display === 'none' ? 'flex' : 'none';
}

export async function triggerChaosScenario(scenario) {
  const box = document.getElementById('chaosFeedbackBox');
  if (box) {
    box.style.display = 'block';
    box.className = 'alert-box alert-warning';
    box.textContent = `⚡ Triggering controlled sandbox scenario '${scenario}' on demo/demo-app...`;
  }

  try {
    const { ok, status, data } = await fetchJson('/api/demo/trigger', {
      method: 'POST',
      body: JSON.stringify({
        scenario,
        namespace: 'demo',
        workload: 'demo-app',
      }),
    });

    if (ok) {
      if (box) {
        box.className = 'alert-box alert-success';
        box.textContent = `✓ Sandbox scenario '${scenario}' applied to Kubernetes demo/demo-app!`;
      }
      setTimeout(() => {
        if (window.fetchTelemetryPulse) window.fetchTelemetryPulse();
        if (window.loadClusterWorkloadData) window.loadClusterWorkloadData();
      }, 1500);
    } else {
      if (box) {
        box.className = 'alert-box alert-danger';
        box.textContent = `Scenario trigger failed (${status}): ${data?.error || 'Unknown error'}`;
      }
    }
  } catch (err) {
    if (box) {
      box.className = 'alert-box alert-danger';
      box.textContent = `Network error triggering scenario: ${err.message}`;
    }
  }
}

// Backward compatibility alias
export const triggerScenario = triggerChaosScenario;
