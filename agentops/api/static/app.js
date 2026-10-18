// AgentOps SRE Unified Operator & Observability Console (v0.7.2)
// Pure vanilla JavaScript client - zero npm or Node.js dependencies

let currentIncident = null;
let currentApprovalId = null;
let selectedNamespace = "demo";
let selectedWorkload = "demo-app";

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

async function initApp() {
  await fetchStatus();
  await fetchEvalSummary();
  await fetchLLMModels();
  await fetchNamespaces();
  await loadClusterOverview();
  await loadClusterWorkloadData();
  await fetchLLMHistory();

  // Periodic background telemetry & status polling
  setInterval(fetchStatus, 5000);
  setInterval(fetchTelemetryPulse, 10000);
}

// ==================== 1. UNIFIED 8-SECTION NAVIGATION ====================
const sectionMap = {
  overview: { tab: "navTabOverview", sec: "sectionOverview" },
  cluster: { tab: "navTabCluster", sec: "sectionCluster" },
  investigation: { tab: "navTabInvestigation", sec: "sectionInvestigation" },
  llm: { tab: "navTabLLM", sec: "sectionLLM" },
  evidence: { tab: "navTabEvidence", sec: "sectionEvidence" },
  approvals: { tab: "navTabApprovals", sec: "sectionApprovals" },
  evaluation: { tab: "navTabEvaluation", sec: "sectionEvaluation" },
  diagnostics: { tab: "navTabDiagnostics", sec: "sectionDiagnostics" },
};

function switchSection(sectionId) {
  if (!sectionMap[sectionId]) return;

  Object.keys(sectionMap).forEach((key) => {
    const tabEl = document.getElementById(sectionMap[key].tab);
    const secEl = document.getElementById(sectionMap[key].sec);
    if (tabEl) tabEl.classList.remove("active");
    if (secEl) {
      secEl.classList.remove("active");
      secEl.style.display = "none";
    }
  });

  const activeTab = document.getElementById(sectionMap[sectionId].tab);
  const activeSec = document.getElementById(sectionMap[sectionId].sec);
  if (activeTab) activeTab.classList.add("active");
  if (activeSec) {
    activeSec.classList.add("active");
    activeSec.style.display = "block";
  }

  // Lifecycle updates on section switch
  if (sectionId === "overview") {
    fetchTelemetryPulse();
  } else if (sectionId === "cluster") {
    loadClusterOverview();
    loadClusterWorkloadData();
  } else if (sectionId === "llm") {
    fetchLLMHistory();
  } else if (sectionId === "approvals") {
    fetchApprovals();
  } else if (sectionId === "diagnostics") {
    fetchStatus();
  }
}

function navigateToEvidence(evidenceId) {
  switchSection("evidence");
  setTimeout(() => {
    const targetCard = document.getElementById(`evidence-card-${evidenceId}`);
    if (targetCard) {
      targetCard.scrollIntoView({ behavior: "smooth", block: "center" });
      targetCard.classList.add("highlight-pulse");
      setTimeout(() => targetCard.classList.remove("highlight-pulse"), 2500);
    }
  }, 100);
}

// Backward compatibility alias
function switchMode(mode) {
  if (mode === "demo") {
    toggleChaosDrawer();
  } else {
    switchSection("investigation");
  }
}

// ==================== 2. STATUS & HEALTH POLLING ====================
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    const comps = data.components || {};

    // Header Badges
    const k8sBadge = document.getElementById("k8sBadge");
    if (k8sBadge) {
      if (comps.kubernetes && comps.kubernetes.connected) {
        k8sBadge.className = "badge badge-success";
        k8sBadge.innerHTML = `<span class="dot"></span> K8s: Connected (${comps.kubernetes.namespace_count} ns)`;
      } else {
        k8sBadge.className = "badge badge-danger";
        k8sBadge.innerHTML = '<span class="dot"></span> K8s: Offline';
      }
    }

    const promBadge = document.getElementById("promBadge");
    if (promBadge) {
      if (comps.prometheus && comps.prometheus.connected) {
        promBadge.className = "badge badge-success";
        promBadge.innerHTML = '<span class="dot"></span> Prom: Active';
      } else {
        promBadge.className = "badge badge-neutral";
        promBadge.innerHTML = '<span class="dot"></span> Prom: Down';
      }
    }

    const lokiBadge = document.getElementById("lokiBadge");
    if (lokiBadge) {
      if (comps.loki && comps.loki.connected) {
        lokiBadge.className = "badge badge-success";
        lokiBadge.innerHTML = '<span class="dot"></span> Loki: Active';
      } else {
        lokiBadge.className = "badge badge-neutral";
        lokiBadge.innerHTML = '<span class="dot"></span> Loki: Down';
      }
    }

    const ollamaBadge = document.getElementById("ollamaBadge");
    if (ollamaBadge) {
      if (comps.ollama && comps.ollama.connected) {
        ollamaBadge.className = "badge badge-info";
        ollamaBadge.innerHTML = `<span class="badge-icon">🦙</span> Ollama: ${comps.ollama.model_count} model(s)`;
      } else {
        ollamaBadge.className = "badge badge-neutral";
        ollamaBadge.innerHTML = '<span class="badge-icon">🦙</span> Ollama: Offline';
      }
    }

    const incBadge = document.getElementById("incidentBadge");
    if (incBadge) {
      if (data.active_incident) {
        const st = data.active_incident.status;
        incBadge.className = st === "RESOLVED" ? "badge badge-success" : (st === "PENDING_APPROVAL" ? "badge badge-warning" : "badge badge-danger");
        incBadge.innerHTML = `<span class="dot"></span> ${st}`;
      } else {
        incBadge.className = "badge badge-idle";
        incBadge.innerHTML = '<span class="dot"></span> Standby';
      }
    }

    // Section 1 Overview Elements
    const ovK8s = document.getElementById("overviewK8sStatus");
    if (ovK8s && comps.kubernetes) {
      ovK8s.textContent = comps.kubernetes.connected ? "CONNECTED" : "OFFLINE";
      ovK8s.className = comps.kubernetes.connected ? "status-pill status-healthy" : "status-pill status-danger";
    }
    const ovNs = document.getElementById("overviewNsCount");
    if (ovNs && comps.kubernetes) ovNs.textContent = comps.kubernetes.namespace_count ?? "--";

    const ovProm = document.getElementById("overviewPromStatus");
    if (ovProm && comps.prometheus) ovProm.textContent = comps.prometheus.connected ? "Active" : "Down";

    const ovLoki = document.getElementById("overviewLokiStatus");
    if (ovLoki && comps.loki) ovLoki.textContent = comps.loki.connected ? "Active" : "Down";

    const ovGraf = document.getElementById("overviewGrafanaStatus");
    if (ovGraf && comps.grafana) ovGraf.textContent = comps.grafana.connected ? "Active" : "Down";

    const ovOll = document.getElementById("overviewOllamaCount");
    if (ovOll && comps.ollama) ovOll.textContent = comps.ollama.connected ? `${comps.ollama.model_count} model(s)` : "Offline";

    // Section 8 Diagnostics Elements
    updateDiagnosticsMatrix(comps, data.cluster);

    // Pending Approvals List and Notification Pill
    const pendingApps = data.pending_approvals || [];
    const pill = document.getElementById("pendingApprovalsPill");
    if (pill) {
      if (pendingApps.length > 0) {
        pill.style.display = "inline-block";
        pill.textContent = pendingApps.length;
      } else {
        pill.style.display = "none";
      }
    }
    updateApprovalsList(pendingApps);

    // Active Incident in Section 1
    updateOverviewActiveIncident(data.active_incident);

    // If active incident exists and not rendered yet
    if (data.active_incident && !currentIncident) {
      renderIncidentReport(data.active_incident);
    }
  } catch (err) {
    console.debug("Status polling failed:", err);
  }
}

function updateDiagnosticsMatrix(comps, cluster) {
  const k8sBadge = document.getElementById("diagK8sBadge");
  const k8sText = document.getElementById("diagK8sDetails");
  if (k8sBadge && k8sText && comps.kubernetes) {
    k8sBadge.textContent = comps.kubernetes.connected ? "CONNECTED" : "OFFLINE";
    k8sBadge.className = comps.kubernetes.connected ? "status-pill status-healthy" : "status-pill status-danger";
    k8sText.textContent = comps.kubernetes.connected
      ? `Cluster context: ${cluster?.context || "discovered"}, Namespaces: ${comps.kubernetes.namespace_count}`
      : `Disconnected: ${comps.kubernetes.error || "kubectl cluster-info returned non-zero"}`;
  }

  const promBadge = document.getElementById("diagPromBadge");
  const promText = document.getElementById("diagPromDetails");
  if (promBadge && promText && comps.prometheus) {
    promBadge.textContent = comps.prometheus.connected ? "CONNECTED" : "OFFLINE";
    promBadge.className = comps.prometheus.connected ? "status-pill status-healthy" : "status-pill status-neutral";
    promText.textContent = comps.prometheus.connected ? "Prometheus TSDB reachable via MCP" : "Endpoint unreachable";
  }

  const grafBadge = document.getElementById("diagGrafanaBadge");
  const grafText = document.getElementById("diagGrafanaDetails");
  if (grafBadge && grafText && comps.grafana) {
    grafBadge.textContent = comps.grafana.connected ? "CONNECTED" : "OFFLINE";
    grafBadge.className = comps.grafana.connected ? "status-pill status-healthy" : "status-pill status-neutral";
    grafText.textContent = comps.grafana.connected ? "Grafana HTTP endpoint reachable" : "Endpoint unreachable";
  }

  const lokiBadge = document.getElementById("diagLokiBadge");
  const lokiText = document.getElementById("diagLokiDetails");
  if (lokiBadge && lokiText && comps.loki) {
    lokiBadge.textContent = comps.loki.connected ? "CONNECTED" : "OFFLINE";
    lokiBadge.className = comps.loki.connected ? "status-pill status-healthy" : "status-pill status-neutral";
    lokiText.textContent = comps.loki.connected ? "Grafana Loki log aggregator reachable" : "Endpoint unreachable";
  }

  const ollamaBadge = document.getElementById("diagOllamaBadge");
  const ollamaText = document.getElementById("diagOllamaDetails");
  if (ollamaBadge && ollamaText && comps.ollama) {
    ollamaBadge.textContent = comps.ollama.connected ? "CONNECTED" : "OFFLINE";
    ollamaBadge.className = comps.ollama.connected ? "status-pill status-healthy" : "status-pill status-neutral";
    ollamaText.textContent = comps.ollama.connected
      ? `Ollama API active with ${comps.ollama.model_count} local model(s)`
      : "Ollama server offline or unreachable on configured host";
  }
}

function updateOverviewActiveIncident(inc) {
  const statusEl = document.getElementById("overviewActiveStatus");
  const bodyEl = document.getElementById("overviewActiveBody");
  if (!statusEl || !bodyEl) return;

  if (!inc) {
    statusEl.textContent = "STANDBY";
    statusEl.className = "status-pill status-neutral";
    bodyEl.innerHTML = `<p class="text-muted">No active incident under investigation. Navigate to <strong>Incident Investigation</strong> to run an autonomous analysis.</p>`;
    return;
  }

  statusEl.textContent = inc.status;
  statusEl.className = inc.status === "RESOLVED" ? "status-pill status-healthy" : (inc.status === "PENDING_APPROVAL" ? "status-pill status-warning" : "status-pill status-danger");

  bodyEl.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.75rem;">
      <div>
        <div class="mono font-bold text-accent">${inc.incident_id}</div>
        <div style="font-weight:700; margin-top:0.25rem;">${escapeHtml(inc.summary || "Incident Diagnostic")}</div>
      </div>
      <button class="btn-sm btn-primary" onclick="switchSection('investigation')">View RCA &amp; Details →</button>
    </div>
    <div style="font-size:0.85rem; color:#cbd5e1; margin-bottom:0.5rem;">${escapeHtml(inc.root_cause || "Analyzing incident telemetry...")}</div>
    <div style="display:flex; gap:0.5rem; align-items:center;">
      <span class="badge badge-sm badge-info">Type: ${escapeHtml(inc.incident_type || "Unknown")}</span>
      <span class="badge badge-sm badge-warning">Confidence: ${Math.round((inc.confidence || 0) * 100)}%</span>
      <span class="badge badge-sm badge-neutral">Model: ${escapeHtml(inc.llm_runtime?.model || "ollama")}</span>
    </div>
  `;
}

async function fetchEvalSummary() {
  try {
    const res = await fetch("/api/eval/summary");
    if (!res.ok) return;
    const data = await res.json();
    const evalBadge = document.getElementById("evalBadge");
    const evalOverallScore = document.getElementById("evalOverallScore");
    const evalGateStatusBadge = document.getElementById("evalGateStatusBadge");

    if (data.status === "ok") {
      const scorePct = Math.round(data.overall_score * 100);
      if (evalBadge) {
        evalBadge.className = data.passing ? "badge badge-success" : "badge badge-danger";
        evalBadge.innerHTML = `<span class="badge-icon">📊</span> Eval: ${scorePct}%`;
        evalBadge.title = `Deterministic Quality Gate: ${scorePct}% (${data.passing ? "PASSED" : "FAILED"})`;
      }
      if (evalOverallScore) evalOverallScore.textContent = `${scorePct}%`;
      if (evalGateStatusBadge) {
        evalGateStatusBadge.textContent = data.passing ? "QUALITY GATE PASSED" : "QUALITY GATE FAILED";
        evalGateStatusBadge.className = data.passing ? "status-pill status-healthy" : "status-pill status-danger";
      }
    }
  } catch (err) {
    console.debug("Eval summary fetch failed:", err);
  }
}

// ==================== 3. CLUSTER & WORKLOADS ====================
async function loadClusterOverview() {
  try {
    const res = await fetch("/api/cluster/overview");
    if (!res.ok) return;
    const data = await res.json();

    const tbody = document.getElementById("nodesTableBody");
    if (tbody) {
      if (!data.connected || !data.nodes || data.nodes.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No cluster nodes reported or cluster offline.</td></tr>`;
      } else {
        tbody.innerHTML = "";
        data.nodes.forEach((node) => {
          const tr = document.createElement("tr");
          const isReady = node.status === "Ready";
          tr.innerHTML = `
            <td class="mono font-bold">${escapeHtml(node.name)}</td>
            <td><span class="status-pill ${isReady ? "status-healthy" : "status-danger"}">${escapeHtml(node.status)}</span></td>
            <td>${escapeHtml(node.condition || "Ready")}</td>
            <td class="mono text-xs">${escapeHtml(node.kubelet_version || "--")}</td>
            <td class="text-xs">${escapeHtml(node.os_image || "--")}</td>
            <td class="text-xs">${escapeHtml(node.arch || "--")}</td>
          `;
          tbody.appendChild(tr);
        });
      }
    }

    const readyEl = document.getElementById("overviewNodesReady");
    if (readyEl) readyEl.textContent = `${data.nodes_ready ?? 0} / ${data.node_count ?? 0}`;

    const ctxEl = document.getElementById("overviewContextName");
    if (ctxEl) ctxEl.textContent = data.current_context || "--";

    const authEl = document.getElementById("overviewAuthMode");
    if (authEl) authEl.textContent = data.auth_mode || "kubeconfig";

    const nsCountEl = document.getElementById("overviewNsCount");
    if (nsCountEl) nsCountEl.textContent = data.namespace_count ?? "--";
  } catch (err) {
    console.error("Failed to load cluster overview:", err);
  }
}

async function fetchNamespaces() {
  try {
    const res = await fetch("/api/cluster/namespaces");
    if (!res.ok) return;
    const data = await res.json();
    const namespaces = data.namespaces || ["demo", "default"];

    const populateNsSelect = (selectId) => {
      const sel = document.getElementById(selectId);
      if (!sel) return;
      const currentVal = sel.value;
      sel.innerHTML = "";
      namespaces.forEach((ns) => {
        const opt = document.createElement("option");
        opt.value = ns;
        opt.textContent = ns;
        if (ns === currentVal || (!currentVal && ns === "demo")) {
          opt.selected = true;
        }
        sel.appendChild(opt);
      });
    };

    populateNsSelect("invNamespaceSelect");
    populateNsSelect("clusterNsSelect");
    populateNsSelect("realNamespaceSelect");

    await fetchWorkloadsForSelect("invNamespaceSelect", "invWorkloadSelect");
    await fetchWorkloadsForSelect("clusterNsSelect", "clusterWlSelect");
  } catch (err) {
    console.error("Failed to fetch namespaces:", err);
  }
}

async function fetchWorkloadsForSelect(nsSelectId, wlSelectId) {
  const nsEl = document.getElementById(nsSelectId);
  const wlEl = document.getElementById(wlSelectId);
  if (!nsEl || !wlEl) return;
  const ns = nsEl.value || "demo";

  try {
    const res = await fetch(`/api/cluster/workloads?namespace=${encodeURIComponent(ns)}`);
    if (!res.ok) return;
    const data = await res.json();
    const currentVal = wlEl.value;

    wlEl.innerHTML = "";
    const workloads = data.workloads || [];
    if (workloads.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(No deployments found)";
      wlEl.appendChild(opt);
    } else {
      workloads.forEach((wl) => {
        const opt = document.createElement("option");
        opt.value = wl;
        opt.textContent = wl;
        if (wl === currentVal || (!currentVal && wl === "demo-app")) {
          opt.selected = true;
        }
        wlEl.appendChild(opt);
      });
    }
  } catch (err) {
    console.error(`Failed to fetch workloads for ${ns}:`, err);
  }
}

function onInvNamespaceChange() {
  fetchWorkloadsForSelect("invNamespaceSelect", "invWorkloadSelect");
}

function onClusterNamespaceChange() {
  fetchWorkloadsForSelect("clusterNsSelect", "clusterWlSelect").then(() => {
    loadClusterWorkloadData();
  });
}

function onClusterWorkloadChange() {
  loadClusterWorkloadData();
}

async function loadClusterWorkloadData() {
  const nsEl = document.getElementById("clusterNsSelect");
  const wlEl = document.getElementById("clusterWlSelect");
  if (!nsEl || !wlEl) return;
  const ns = nsEl.value || "demo";
  const wl = wlEl.value || "demo-app";

  try {
    const [podsRes, eventsRes] = await Promise.all([
      fetch(`/api/cluster/pods?namespace=${encodeURIComponent(ns)}&workload=${encodeURIComponent(wl)}`),
      fetch(`/api/cluster/events?namespace=${encodeURIComponent(ns)}&workload=${encodeURIComponent(wl)}`),
    ]);

    const podsBody = document.getElementById("workloadPodsBody");
    if (podsBody && podsRes.ok) {
      const podsData = await podsRes.json();
      const pods = podsData.pods || [];
      if (pods.length === 0) {
        podsBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No pods found for ${escapeHtml(ns)}/${escapeHtml(wl)}</td></tr>`;
      } else {
        podsBody.innerHTML = "";
        pods.forEach((p) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td class="mono font-bold">${escapeHtml(p.name)}</td>
            <td><span class="status-pill ${p.phase === "Running" ? "status-healthy" : "status-danger"}">${escapeHtml(p.phase)}</span></td>
            <td>${p.ready ? "✓ Ready" : "✗ Not Ready"}</td>
            <td><strong class="${p.restart_count > 0 ? "text-danger" : ""}">${p.restart_count ?? 0}</strong></td>
            <td class="mono text-xs">${escapeHtml(p.state_reason || "--")}</td>
            <td class="text-xs text-muted">${escapeHtml(p.termination_reason || "--")}</td>
          `;
          podsBody.appendChild(tr);
        });
      }
    }

    const eventsBox = document.getElementById("workloadEventsStream");
    if (eventsBox && eventsRes.ok) {
      const eventsData = await eventsRes.json();
      const events = eventsData.events || [];
      if (events.length === 0) {
        eventsBox.innerHTML = `<p class="text-muted text-sm">No recent warning events detected for this workload.</p>`;
      } else {
        eventsBox.innerHTML = "";
        events.forEach((ev) => {
          const div = document.createElement("div");
          div.className = "event-entry";
          div.innerHTML = `
            <div style="display:flex; justify-content:space-between; margin-bottom:2px;">
              <strong class="text-danger">${escapeHtml(ev.reason || "Warning")}</strong>
              <span class="text-muted text-xs">${escapeHtml(ev.last_timestamp || "recent")} (x${ev.count || 1})</span>
            </div>
            <div style="color:#cbd5e1;">${escapeHtml(ev.message || "")}</div>
          `;
          eventsBox.appendChild(div);
        });
      }
    }
  } catch (err) {
    console.error("Failed to load workload data:", err);
  }
}

// ==================== 4. LIVE TELEMETRY PULSE ====================
async function fetchTelemetryPulse() {
  const nsEl = document.getElementById("invNamespaceSelect") || document.getElementById("clusterNsSelect");
  const wlEl = document.getElementById("invWorkloadSelect") || document.getElementById("clusterWlSelect");
  const ns = nsEl?.value || "demo";
  const wl = wlEl?.value || "demo-app";

  const targetLabel = document.getElementById("pulseTargetLabel");
  if (targetLabel) targetLabel.textContent = `${ns}/${wl}`;

  try {
    const res = await fetch(`/api/telemetry/pulse?namespace=${encodeURIComponent(ns)}&workload=${encodeURIComponent(wl)}`);
    if (!res.ok) return;
    const data = await res.json();

    const badge = document.getElementById("pulseBadge");
    if (badge) {
      const st = (data.pulse_status || "UNKNOWN").toUpperCase();
      badge.textContent = st;
      badge.className = st === "HEALTHY" ? "pulse-badge pulse-healthy" : (st === "DEGRADED" ? "pulse-badge pulse-warning" : "pulse-badge pulse-danger");
    }

    const k8s = data.k8s || {};
    const prom = data.prometheus || {};

    const readyPods = document.getElementById("pulseReadyPods");
    if (readyPods) readyPods.textContent = `${k8s.ready_pods ?? "--"} / ${k8s.desired_replicas ?? "--"}`;

    const restarts = document.getElementById("pulseRestarts");
    if (restarts) restarts.textContent = k8s.total_restarts ?? "--";

    const errRate = document.getElementById("pulseErrorRate");
    if (errRate) errRate.textContent = prom.error_rate_pct !== null && prom.error_rate_pct !== undefined ? `${prom.error_rate_pct.toFixed(1)}%` : "--";

    const latency = document.getElementById("pulseLatency");
    if (latency) latency.textContent = prom.p95_latency_s !== null && prom.p95_latency_s !== undefined ? `${prom.p95_latency_s.toFixed(3)}s` : "--";

    const memory = document.getElementById("pulseMemory");
    if (memory) memory.textContent = prom.memory_mb !== null && prom.memory_mb !== undefined ? `${prom.memory_mb.toFixed(1)} MB` : "--";

    const warnings = document.getElementById("pulseWarnings");
    if (warnings) warnings.textContent = k8s.warnings_count ?? 0;
  } catch (err) {
    console.debug("Telemetry pulse fetch failed:", err);
  }
}

// Backward compatibility alias
const pollTelemetryPulse = fetchTelemetryPulse;

// ==================== 5. LLM DISCOVERY & REAL AI ENFORCEMENT ====================
async function fetchLLMModels() {
  try {
    const res = await fetch("/api/llm/models");
    if (!res.ok) return;
    const data = await res.json();

    const sel = document.getElementById("invModelSelect");
    if (!sel) return;
    sel.innerHTML = "";

    // 1. Ollama local models
    if (data.ollama && data.ollama.available && data.ollama.models.length > 0) {
      const optGroup = document.createElement("optgroup");
      optGroup.label = "Local Ollama Models (Real Local AI)";
      data.ollama.models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = `ollama:${m.name}`;
        const paramStr = m.parameter_size !== "unknown" ? ` (${m.parameter_size})` : "";
        opt.textContent = `🦙 ${m.name}${paramStr}`;
        if (data.default && data.default.provider === "ollama" && data.default.model === m.name) {
          opt.selected = true;
        }
        optGroup.appendChild(opt);
      });
      sel.appendChild(optGroup);
    }

    // 2. Cloud models
    if (data.cloud && data.cloud.available && data.cloud.providers.length > 0) {
      const optGroup = document.createElement("optgroup");
      optGroup.label = "Configured Cloud Providers";
      data.cloud.providers.forEach((p) => {
        p.models.forEach((m) => {
          const opt = document.createElement("option");
          opt.value = `${p.provider}:${m}`;
          opt.textContent = `☁️ ${p.name}: ${m}`;
          optGroup.appendChild(opt);
        });
      });
      sel.appendChild(optGroup);
    }

    // If no real models available, prompt user
    if (sel.options.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No real LLM found. Start Ollama with 'ollama serve' & pull a model.";
      opt.disabled = true;
      opt.selected = true;
      sel.appendChild(opt);
    }
  } catch (err) {
    console.error("Failed to discover LLM models:", err);
  }
}

function parseProviderAndModel(compoundVal) {
  if (!compoundVal) return { provider: "ollama", model: undefined };
  const idx = compoundVal.indexOf(":");
  if (idx === -1) {
    return { provider: compoundVal || "ollama", model: undefined };
  }
  return {
    provider: compoundVal.slice(0, idx) || "ollama",
    model: compoundVal.slice(idx + 1) || undefined,
  };
}

// 9-Step Lifecycle Visual Stepper Helper
function updateLifecycleStepper(activeStepIndex, errorStepIndex = null) {
  for (let i = 1; i <= 9; i++) {
    const node = document.getElementById(`step${i}`);
    if (!node) continue;
    node.className = "step-node";
    if (errorStepIndex === i) {
      node.classList.add("error");
    } else if (i <= activeStepIndex) {
      node.classList.add("active");
    }
  }
}

// ==================== 6. AUTONOMOUS INVESTIGATION ====================
async function startInvestigation() {
  const ns = document.getElementById("invNamespaceSelect")?.value || "demo";
  const wl = document.getElementById("invWorkloadSelect")?.value || "demo-app";
  const modelCompound = document.getElementById("invModelSelect")?.value;
  const description = document.getElementById("invDescriptionInput")?.value || "";
  const dryRun = document.getElementById("invDryRunCheck")?.checked || false;

  const { provider, model } = parseProviderAndModel(modelCompound);

  const btn = document.getElementById("btnRunInvestigation");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-inline"></span> Correlating Cluster Telemetry...`;
  }

  // Visual Stepper Progression: Configured -> Reachable -> Discovered -> Selected -> Invoked
  updateLifecycleStepper(5);
  const runtimeBadge = document.getElementById("llmRuntimeStatusBadge");
  if (runtimeBadge) {
    runtimeBadge.textContent = "INFERENCE ACTIVE";
    runtimeBadge.className = "status-pill status-warning";
  }

  try {
    const res = await fetch("/api/incidents/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        namespace: ns,
        workload: wl,
        provider,
        model,
        description,
        dry_run: dryRun,
        source: "MANUAL",
      }),
    });

    const report = await res.json();
    if (res.ok) {
      updateLifecycleStepper(9);
      if (runtimeBadge) {
        runtimeBadge.textContent = "INFERENCE COMPLETED";
        runtimeBadge.className = "status-pill status-healthy";
      }
      renderIncidentReport(report);
    } else {
      updateLifecycleStepper(6, 6);
      if (runtimeBadge) {
        runtimeBadge.textContent = "INFERENCE FAILED";
        runtimeBadge.className = "status-pill status-danger";
      }
      showInvestigationError(report.error || "Investigation request failed");
      if (report.incident_id) {
        renderIncidentReport(report);
      }
    }
  } catch (err) {
    updateLifecycleStepper(5, 5);
    showInvestigationError(`Network/Transport error: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<span class="btn-icon">⚡</span> Run Autonomous Investigation`;
    }
    fetchTelemetryPulse();
    fetchLLMHistory();
    fetchStatus();
  }
}

function showInvestigationError(msg) {
  const card = document.getElementById("investigationResultsCard");
  const banner = document.getElementById("invFailureBanner");
  const reason = document.getElementById("invFailureReason");
  if (card) card.style.display = "block";
  if (banner && reason) {
    banner.style.display = "block";
    reason.textContent = msg;
  }
}

// ==================== 7. REPORT & EVIDENCE RENDERING ====================
function renderIncidentReport(report) {
  currentIncident = report;
  currentApprovalId = report.approval_id;

  const resultsCard = document.getElementById("investigationResultsCard");
  if (resultsCard) resultsCard.style.display = "block";

  // Incident ID & Status Badges
  const idLabel = document.getElementById("invIncidentIdLabel");
  if (idLabel) idLabel.textContent = report.incident_id || "inc-unknown";

  const stBadge = document.getElementById("invStatusBadge");
  if (stBadge) {
    stBadge.textContent = report.status;
    stBadge.className = report.status === "RESOLVED" ? "status-pill status-healthy" : (report.status === "PENDING_APPROVAL" ? "status-pill status-warning" : "status-pill status-danger");
  }

  const valBadge = document.getElementById("invValidationBadge");
  if (valBadge) {
    const valid = report.validation_passed !== false;
    valBadge.textContent = valid ? "VALIDATED GROUNDED" : "VALIDATION FAILED";
    valBadge.className = valid ? "status-pill status-healthy" : "status-pill status-danger";
  }

  // Failure banner
  const failBanner = document.getElementById("invFailureBanner");
  const failReason = document.getElementById("invFailureReason");
  if (failBanner && failReason) {
    if (report.validation_passed === false || report.status === "FAILED") {
      failBanner.style.display = "block";
      failReason.textContent = report.root_cause || "LLM output failed grounding or schema validation";
    } else {
      failBanner.style.display = "none";
    }
  }

  // Missing signals alert
  const missingAlert = document.getElementById("invMissingSignalsAlert");
  const missingText = document.getElementById("invMissingSignalsText");
  if (missingAlert && missingText) {
    if (report.missing_signals && report.missing_signals.length > 0) {
      missingAlert.style.display = "block";
      missingText.textContent = `The following signals were offline or missing: ${report.missing_signals.join(", ")}`;
    } else {
      missingAlert.style.display = "none";
    }
  }

  // Diagnosis Block
  const diagType = document.getElementById("diagIncidentType");
  if (diagType) diagType.textContent = report.incident_type || "Unknown";

  const diagSev = document.getElementById("diagSeverity");
  if (diagSev) diagSev.textContent = report.severity || "MEDIUM";

  const diagConf = document.getElementById("diagConfidence");
  if (diagConf) diagConf.textContent = `${Math.round((report.confidence || 0) * 100)}%`;

  const diagSrc = document.getElementById("diagSource");
  if (diagSrc) diagSrc.textContent = report.source || "MANUAL";

  // RCA Text
  const rcaSummary = document.getElementById("rcaSummaryText");
  if (rcaSummary) rcaSummary.textContent = report.summary || "--";

  const rcaRoot = document.getElementById("rcaRootCauseText");
  if (rcaRoot) rcaRoot.textContent = report.root_cause || "--";

  // Grounded Evidence Pills
  const pillsContainer = document.getElementById("rcaEvidencePills");
  if (pillsContainer) {
    pillsContainer.innerHTML = "";
    const items = report.evidence_items || [];
    if (items.length === 0) {
      pillsContainer.innerHTML = '<span class="text-muted text-sm">No evidence items referenced.</span>';
    } else {
      items.forEach((item) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "evidence-pill";
        btn.innerHTML = `<strong>${escapeHtml(item.id)}</strong> <small>(${escapeHtml(item.source)})</small>`;
        btn.title = `Click to inspect ${escapeHtml(item.id)} in Evidence Explorer`;
        btn.onclick = () => navigateToEvidence(item.id);
        pillsContainer.appendChild(btn);
      });
    }
  }

  // Remediation & Policy Governance
  const polBadge = document.getElementById("policyDecisionBadge");
  if (polBadge) {
    polBadge.textContent = report.policy_decision || "EVALUATED";
    polBadge.className = report.policy_decision === "ALLOW" ? "status-pill status-healthy" : "status-pill status-warning";
  }

  const recAction = document.getElementById("recActionText");
  if (recAction) recAction.textContent = report.recommended_remediation || "none";

  const recAppr = document.getElementById("recApprovalRequiredText");
  if (recAppr) recAppr.textContent = report.approval_required ? "REQUIRED (Single-Use Token)" : "NOT REQUIRED";

  const recRisk = document.getElementById("recRiskLevelText");
  if (recRisk) recRisk.textContent = report.risk_level || "UNKNOWN";

  const recReason = document.getElementById("recPolicyReasonText");
  if (recReason) recReason.textContent = report.policy_reason || "";

  // Inline Approval Action Box
  const apprBox = document.getElementById("inlineApprovalActionBox");
  const apprIdEl = document.getElementById("inlineApprovalId");
  if (apprBox && apprIdEl) {
    if (report.approval_required && report.approval_id && report.status === "PENDING_APPROVAL") {
      apprBox.style.display = "block";
      apprIdEl.textContent = report.approval_id;
    } else {
      apprBox.style.display = "none";
    }
  }

  // Section 4: LLM Observability Metrics
  renderLLMTelemetry(report);

  // Section 5: Evidence Explorer Cards
  renderEvidenceExplorer(report.evidence_items || []);
}

function renderLLMTelemetry(report) {
  const rt = report.llm_runtime || {};
  const modelEl = document.getElementById("llmActiveModel");
  if (modelEl) modelEl.textContent = rt.model ? `${rt.model} (${rt.provider || "ollama"})` : "--";

  const modeEl = document.getElementById("llmActiveMode");
  if (modeEl) modeEl.textContent = (rt.mode || "local").toUpperCase();

  const latEl = document.getElementById("llmLatency");
  if (latEl) latEl.textContent = rt.latency_seconds !== undefined ? `${rt.latency_seconds}s` : "--";

  const speedEl = document.getElementById("llmTokenSpeed");
  if (speedEl) speedEl.textContent = rt.tokens_per_second !== undefined ? `${rt.tokens_per_second} tok/s` : "N/A";

  const pTokens = document.getElementById("llmPromptTokens");
  if (pTokens) pTokens.textContent = rt.prompt_tokens ?? "--";

  const cTokens = document.getElementById("llmCompletionTokens");
  if (cTokens) cTokens.textContent = rt.completion_tokens ?? "--";

  const valText = document.getElementById("llmValidationText");
  if (valText) {
    const valid = report.validation_passed !== false;
    valText.textContent = valid ? "PASSED (100%)" : "FAILED REJECTED";
    valText.className = valid ? "meter-value text-sm text-success" : "meter-value text-sm text-danger";
  }
}

function renderEvidenceExplorer(items) {
  const countBadge = document.getElementById("evidenceCountBadge");
  if (countBadge) countBadge.textContent = `${items.length} Items`;

  const container = document.getElementById("evidenceListContainer");
  if (!container) return;

  if (items.length === 0) {
    container.innerHTML = `<p class="text-muted text-center py-4">No investigation evidence loaded. Run an investigation to view multi-signal evidence.</p>`;
    return;
  }

  container.innerHTML = "";
  items.forEach((item) => {
    const card = document.createElement("div");
    card.id = `evidence-card-${item.id}`;
    card.className = "evidence-item-card";

    let srcBadgeClass = "badge-neutral";
    if (item.source === "kubernetes") srcBadgeClass = "badge-info";
    else if (item.source === "prometheus") srcBadgeClass = "badge-warning";
    else if (item.source === "loki") srcBadgeClass = "badge-danger";

    let sevBadgeClass = "badge-neutral";
    if (item.severity === "CRITICAL") sevBadgeClass = "badge-danger";
    else if (item.severity === "WARNING") sevBadgeClass = "badge-warning";

    card.innerHTML = `
      <div class="evidence-item-header">
        <div style="display:flex; gap:0.5rem; align-items:center;">
          <strong class="mono text-accent">${escapeHtml(item.id)}</strong>
          <span class="badge badge-sm ${srcBadgeClass}">${escapeHtml((item.source || "").toUpperCase())}</span>
          <span class="mono text-xs text-muted">${escapeHtml(item.resource || "")}</span>
        </div>
        <span class="badge badge-sm ${sevBadgeClass}">${escapeHtml(item.severity || "INFO")}</span>
      </div>
      <div class="evidence-obs mt-2">${escapeHtml(item.observation)}</div>
      <div class="evidence-query mono text-xs mt-2">${escapeHtml(item.metric_or_query || "")}</div>
    `;
    container.appendChild(card);
  });
}

// ==================== 8. APPROVAL & REMEDIATION MUTATION ====================
async function approveCurrentIncident() {
  if (!currentApprovalId) {
    alert("No actionable approval token currently active.");
    return;
  }

  const approveBtn = document.getElementById("btnInlineApprove");
  if (approveBtn) {
    approveBtn.disabled = true;
    approveBtn.textContent = "Executing Mutation...";
  }

  try {
    const res = await fetch(`/api/approvals/${currentApprovalId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator: "sre-oncall",
        reason: "Authorized via Unified Operator Console (v0.7.2)",
      }),
    });

    const summary = await res.json();
    if (res.ok) {
      renderRolloutVerification(summary);
      switchSection("approvals");
      const apprBox = document.getElementById("inlineApprovalActionBox");
      if (apprBox) apprBox.style.display = "none";
      const stBadge = document.getElementById("invStatusBadge");
      if (stBadge) {
        stBadge.textContent = summary.resolution_status || "RESOLVED";
        stBadge.className = "status-pill status-healthy";
      }
    } else {
      alert(`Approval execution failed: ${summary.error || "Unknown error"}`);
    }
  } catch (err) {
    alert(`Network error during remediation execution: ${err.message}`);
  } finally {
    if (approveBtn) {
      approveBtn.disabled = false;
      approveBtn.textContent = "✓ Authorize & Execute";
    }
    fetchStatus();
    fetchTelemetryPulse();
  }
}

async function rejectCurrentIncident() {
  if (!currentApprovalId) return;

  try {
    const res = await fetch(`/api/approvals/${currentApprovalId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator: "sre-oncall",
        reason: "Rejected by SRE operator via Console",
      }),
    });

    const data = await res.json();
    if (res.ok) {
      const apprBox = document.getElementById("inlineApprovalActionBox");
      if (apprBox) apprBox.style.display = "none";
      const stBadge = document.getElementById("invStatusBadge");
      if (stBadge) {
        stBadge.textContent = "REJECTED";
        stBadge.className = "status-pill status-neutral";
      }
      alert(`Approval ${currentApprovalId} rejected.`);
    } else {
      alert(`Rejection failed: ${data.error || "Unknown error"}`);
    }
  } catch (err) {
    alert(`Network error: ${err.message}`);
  } finally {
    fetchStatus();
  }
}

function renderRolloutVerification(summary) {
  const card = document.getElementById("rolloutVerificationCard");
  if (!card) return;
  card.style.display = "block";

  const idLabel = document.getElementById("execIdLabel");
  if (idLabel) idLabel.textContent = summary.execution_id || "exec-done";

  const resBadge = document.getElementById("execResolutionBadge");
  if (resBadge) {
    resBadge.textContent = summary.resolution_status || "RESOLVED";
    resBadge.className = summary.resolution_status === "RESOLVED" ? "status-pill status-healthy" : "status-pill status-danger";
  }

  const mutStatus = document.getElementById("execMutationStatus");
  if (mutStatus) mutStatus.textContent = summary.mutation_status || "SUCCESS";

  const rollStatus = document.getElementById("execRolloutStatus");
  if (rollStatus) rollStatus.textContent = summary.rollout_status || "HEALTHY";

  const repVerif = document.getElementById("execReplicasVerified");
  if (repVerif) repVerif.textContent = `${summary.ready_replicas ?? "--"} / ${summary.desired_replicas ?? "--"}`;

  const jsonBox = document.getElementById("execVerificationJson");
  if (jsonBox) {
    jsonBox.textContent = JSON.stringify(summary.verification || summary, null, 2);
  }
}

function updateApprovalsList(approvals) {
  const container = document.getElementById("pendingApprovalsList");
  if (!container) return;

  if (approvals.length === 0) {
    container.innerHTML = `<p class="text-muted text-center py-4">No pending approvals found. All systems within policy constraints.</p>`;
    return;
  }

  container.innerHTML = "";
  approvals.forEach((app) => {
    const card = document.createElement("div");
    card.className = "approval-card";
    const req = app.action_request || {};
    const target = req.target || {};

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="mono font-bold text-accent">${escapeHtml(app.approval_id)}</span>
        <span class="status-pill status-warning">PENDING AUTHORIZATION</span>
      </div>
      <div style="margin: 0.5rem 0; font-size: 0.9rem;">
        <div><strong>Action:</strong> <code class="mono">${escapeHtml(req.action || "unknown")}</code></div>
        <div><strong>Target:</strong> <code class="mono">${escapeHtml(target.namespace || "")}/${escapeHtml(target.resource_name || "")}</code></div>
        <div class="text-xs text-muted" style="margin-top:0.25rem;">Created: ${escapeHtml(app.created_at || "recently")}</div>
      </div>
      <div style="display:flex; gap:0.5rem; justify-content:flex-end;">
        <button class="btn-sm btn-success" onclick="approveSpecificId('${app.approval_id}')">Approve &amp; Execute</button>
        <button class="btn-sm btn-danger" onclick="rejectSpecificId('${app.approval_id}')">Reject</button>
      </div>
    `;
    container.appendChild(card);
  });
}

async function approveSpecificId(approvalId) {
  currentApprovalId = approvalId;
  await approveCurrentIncident();
}

async function rejectSpecificId(approvalId) {
  currentApprovalId = approvalId;
  await rejectCurrentIncident();
}

async function fetchApprovals() {
  await fetchStatus();
}

// Backward compatibility alias
const submitApproval = approveCurrentIncident;
const submitRejection = rejectCurrentIncident;

// ==================== 9. LLM EXECUTION HISTORY ====================
async function fetchLLMHistory() {
  try {
    const res = await fetch("/api/llm/history");
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById("llmHistoryTableBody");
    if (!tbody) return;

    const executions = data.history || [];
    if (executions.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted">No model executions recorded yet in this session.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    executions.forEach((ex) => {
      const tr = document.createElement("tr");
      const valid = ex.validation_passed !== false;
      tr.innerHTML = `
        <td class="mono text-xs">${escapeHtml(ex.timestamp ? ex.timestamp.split("T")[1]?.slice(0, 8) : "--")}</td>
        <td class="mono text-xs">${escapeHtml(ex.target || "--")}</td>
        <td><span class="badge badge-sm badge-info">${escapeHtml(ex.provider || "ollama")}</span></td>
        <td class="mono text-xs font-bold">${escapeHtml(ex.model || "--")}</td>
        <td>${ex.latency_seconds !== undefined ? `${ex.latency_seconds}s` : "--"}</td>
        <td class="text-xs">${ex.prompt_tokens ?? "--"} / ${ex.completion_tokens ?? "--"}</td>
        <td class="text-xs">${ex.tokens_per_second ? `${ex.tokens_per_second} tok/s` : "--"}</td>
        <td><span class="status-pill ${ex.status === "SUCCESS" ? "status-healthy" : "status-danger"}">${escapeHtml(ex.status || "OK")}</span></td>
        <td><span class="status-pill ${valid ? "status-healthy" : "status-danger"}">${valid ? "VALID" : "INVALID"}</span></td>
        <td class="mono text-xs text-accent">${escapeHtml(ex.incident_id || "--")}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.debug("Failed to fetch LLM history:", err);
  }
}

// ==================== 10. DEMO CHAOS PLAYGROUND (ISOLATED) ====================
function toggleChaosDrawer() {
  const drawer = document.getElementById("chaosDrawer");
  if (!drawer) return;
  drawer.style.display = drawer.style.display === "none" ? "flex" : "none";
}

async function triggerChaosScenario(scenario) {
  const box = document.getElementById("chaosFeedbackBox");
  if (box) {
    box.style.display = "block";
    box.className = "alert-box alert-warning";
    box.textContent = `⚡ Triggering controlled sandbox scenario '${scenario}' on demo/demo-app...`;
  }

  try {
    const res = await fetch("/api/demo/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scenario,
        namespace: "demo",
        workload: "demo-app",
      }),
    });

    const data = await res.json();
    if (res.ok) {
      if (box) {
        box.className = "alert-box alert-success";
        box.textContent = `✓ Sandbox scenario '${scenario}' applied to Kubernetes demo/demo-app!`;
      }
      setTimeout(() => {
        fetchTelemetryPulse();
        loadClusterWorkloadData();
      }, 1500);
    } else {
      if (box) {
        box.className = "alert-box alert-danger";
        box.textContent = `Scenario trigger failed: ${data.error || "Unknown error"}`;
      }
    }
  } catch (err) {
    if (box) {
      box.className = "alert-box alert-danger";
      box.textContent = `Network error triggering scenario: ${err.message}`;
    }
  }
}

// Backward compatibility alias
const triggerScenario = triggerChaosScenario;

// Helper to escape HTML characters safely
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
