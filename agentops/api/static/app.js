// AgentOps SRE Real Operator Console Client (v0.7.1)

let currentIncident = null;
let currentApprovalId = null;
let currentMode = "real"; // "real" or "demo"
let pulsePollingTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

async function initApp() {
  await fetchStatus();
  await fetchEvalSummary();
  await fetchLLMModels();
  await fetchNamespaces();

  // Periodic polling for cluster health & active incident updates
  setInterval(fetchStatus, 5000);
  setInterval(pollTelemetryPulse, 10000);
}

// ==================== MODE SWITCHING ====================
function switchMode(mode) {
  currentMode = mode;
  const tabReal = document.getElementById("tabRealMode");
  const tabDemo = document.getElementById("tabDemoMode");
  const viewReal = document.getElementById("realOperationsView");
  const viewDemo = document.getElementById("demoPlaygroundView");
  const hint = document.getElementById("modeHintText");

  if (mode === "real") {
    tabReal.classList.add("active");
    tabDemo.classList.remove("active");
    viewReal.classList.remove("hidden");
    viewDemo.classList.add("hidden");
    hint.textContent = "Direct cluster observability & autonomous diagnostic for real Kubernetes workloads.";
    pollTelemetryPulse();
  } else {
    tabDemo.classList.add("active");
    tabReal.classList.remove("active");
    viewDemo.classList.remove("hidden");
    viewReal.classList.add("hidden");
    hint.textContent = "Synthetic chaos playground strictly isolated to sandbox target demo/demo-app.";
  }
}

// ==================== STATUS & DISCOVERY ====================
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    const comps = data.components || {};

    // 1. Kubernetes
    const k8sBadge = document.getElementById("k8sBadge");
    if (comps.kubernetes && comps.kubernetes.connected) {
      k8sBadge.className = "badge badge-success";
      k8sBadge.innerHTML = `<span class="dot"></span> K8s: Connected (${comps.kubernetes.namespace_count} ns)`;
    } else {
      k8sBadge.className = "badge badge-danger";
      k8sBadge.innerHTML = '<span class="dot"></span> K8s: Offline';
    }

    // 2. Prometheus
    const promBadge = document.getElementById("promBadge");
    if (comps.prometheus && comps.prometheus.connected) {
      promBadge.className = "badge badge-success";
      promBadge.innerHTML = '<span class="dot"></span> Prom: Active';
    } else {
      promBadge.className = "badge badge-neutral";
      promBadge.innerHTML = '<span class="dot"></span> Prom: Down';
    }

    // 3. Loki
    const lokiBadge = document.getElementById("lokiBadge");
    if (comps.loki && comps.loki.connected) {
      lokiBadge.className = "badge badge-success";
      lokiBadge.innerHTML = '<span class="dot"></span> Loki: Active';
    } else {
      lokiBadge.className = "badge badge-neutral";
      lokiBadge.innerHTML = '<span class="dot"></span> Loki: Down';
    }

    // 4. Ollama (Local AI)
    const ollamaBadge = document.getElementById("ollamaBadge");
    if (comps.ollama && comps.ollama.connected) {
      ollamaBadge.className = "badge badge-info";
      ollamaBadge.innerHTML = `<span class="badge-icon">🦙</span> Ollama: ${comps.ollama.model_count} model(s)`;
    } else {
      ollamaBadge.className = "badge badge-neutral";
      ollamaBadge.innerHTML = '<span class="badge-icon">🦙</span> Ollama: Offline';
    }

    // 5. Active Incident Status
    const incBadge = document.getElementById("incidentBadge");
    if (data.active_incident) {
      const st = data.active_incident.status;
      incBadge.className = st === "RESOLVED" ? "badge badge-success" : (st === "PENDING_APPROVAL" ? "badge badge-warning" : "badge badge-danger");
      incBadge.innerHTML = `<span class="dot"></span> ${st}`;
    } else {
      incBadge.className = "badge badge-idle";
      incBadge.innerHTML = '<span class="dot"></span> Standby';
    }

    // 6. Update Pending Approvals Drawer
    updateApprovalsList(data.pending_approvals || []);

    // If active incident exists and not currently rendered, display it
    if (data.active_incident && !currentIncident) {
      renderIncidentReport(data.active_incident);
    }
  } catch (err) {
    console.debug("Status polling failed:", err);
  }
}

async function fetchEvalSummary() {
  try {
    const res = await fetch("/api/eval/summary");
    if (!res.ok) return;
    const data = await res.json();
    const evalBadge = document.getElementById("evalBadge");
    if (data.status === "ok") {
      const scorePct = Math.round(data.overall_score * 100);
      evalBadge.className = data.passing ? "badge badge-success" : "badge badge-danger";
      evalBadge.innerHTML = `<span class="badge-icon">📊</span> Eval: ${scorePct}%`;
      evalBadge.title = `Benchmark Score: ${scorePct}% (${data.passing ? "PASSED" : "FAILED"})`;
    }
  } catch (err) {
    console.debug("Eval summary fetch failed:", err);
  }
}

async function fetchNamespaces() {
  try {
    const res = await fetch("/api/cluster/namespaces");
    if (!res.ok) return;
    const data = await res.json();
    const sel = document.getElementById("realNamespaceSelect");
    const currentVal = sel.value;

    sel.innerHTML = "";
    const namespaces = data.namespaces || ["demo", "default"];
    namespaces.forEach((ns) => {
      const opt = document.createElement("option");
      opt.value = ns;
      opt.textContent = ns;
      if (ns === currentVal || (!currentVal && ns === "demo")) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });

    await fetchWorkloads();
  } catch (err) {
    console.error("Failed to discover namespaces:", err);
  }
}

async function fetchWorkloads() {
  const ns = document.getElementById("realNamespaceSelect").value || "demo";
  try {
    const res = await fetch(`/api/cluster/workloads?namespace=${encodeURIComponent(ns)}`);
    if (!res.ok) return;
    const data = await res.json();
    const sel = document.getElementById("realWorkloadSelect");
    const currentVal = sel.value;

    sel.innerHTML = "";
    const workloads = data.workloads || [];
    if (workloads.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(No deployments found)";
      sel.appendChild(opt);
    } else {
      workloads.forEach((wl) => {
        const opt = document.createElement("option");
        opt.value = wl;
        opt.textContent = wl;
        if (wl === currentVal || (!currentVal && wl === "demo-app")) {
          opt.selected = true;
        }
        sel.appendChild(opt);
      });
    }

    pollTelemetryPulse();
  } catch (err) {
    console.error(`Failed to discover workloads in ${ns}:`, err);
  }
}

function onNamespaceChange() {
  fetchWorkloads();
}

function onWorkloadChange() {
  pollTelemetryPulse();
}

async function fetchLLMModels() {
  try {
    const res = await fetch("/api/llm/models");
    if (!res.ok) return;
    const data = await res.json();

    const realSel = document.getElementById("realModelSelect");
    const demoSel = document.getElementById("demoModelSelect");

    const populateSelect = (sel) => {
      sel.innerHTML = "";

      // 1. Ollama local models group
      if (data.ollama && data.ollama.available && data.ollama.models.length > 0) {
        const optGroup = document.createElement("optgroup");
        optGroup.label = "Local Ollama Models";
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

      // 2. Cloud Models
      if (data.cloud && data.cloud.available) {
        const optGroup = document.createElement("optgroup");
        optGroup.label = "Cloud Models (Configured)";
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

      // 3. Mock / Rule-Based engine
      const mockGroup = document.createElement("optgroup");
      mockGroup.label = "Deterministic / Fast Evaluation";
      const mockOpt = document.createElement("option");
      mockOpt.value = "mock:deterministic-evaluator";
      mockOpt.textContent = "⚡ Fast Rule-Based Diagnostic Engine";
      if (!data.ollama || !data.ollama.available) {
        mockOpt.selected = true;
      }
      mockGroup.appendChild(mockOpt);
      sel.appendChild(mockGroup);
    };

    populateSelect(realSel);
    populateSelect(demoSel);
  } catch (err) {
    console.error("Failed to discover LLM models:", err);
  }
}

// ==================== LIVE TELEMETRY PULSE ====================
async function pollTelemetryPulse() {
  const ns = document.getElementById("realNamespaceSelect").value || "demo";
  const wl = document.getElementById("realWorkloadSelect").value;
  if (!wl) return;

  document.getElementById("pulseTargetLabel").textContent = `${ns}/${wl}`;

  try {
    const res = await fetch(`/api/telemetry/pulse?namespace=${encodeURIComponent(ns)}&workload=${encodeURIComponent(wl)}`);
    if (!res.ok) return;
    const data = await res.json();

    // Pulse Status Badge
    const statusBadge = document.getElementById("pulseStatusBadge");
    const st = (data.pulse_status || "unknown").toUpperCase();
    if (st === "HEALTHY") {
      statusBadge.className = "badge badge-success";
      statusBadge.textContent = "HEALTHY";
    } else if (st === "DEGRADED") {
      statusBadge.className = "badge badge-warning";
      statusBadge.textContent = "DEGRADED";
    } else if (st === "CRITICAL") {
      statusBadge.className = "badge badge-danger";
      statusBadge.textContent = "CRITICAL";
    } else {
      statusBadge.className = "badge badge-neutral";
      statusBadge.textContent = "UNKNOWN";
    }

    // Pulse Metrics
    const k8s = data.k8s || {};
    const prom = data.prometheus || {};

    document.getElementById("pulseReadyPods").textContent = `${k8s.ready_pods ?? "--"} / ${k8s.desired_replicas ?? "--"}`;
    document.getElementById("pulseRestarts").textContent = k8s.total_restarts ?? "--";

    const errRate = prom.error_rate_pct;
    document.getElementById("pulseErrorRate").textContent = errRate !== null && errRate !== undefined ? `${errRate.toFixed(1)}%` : "--";

    const latency = prom.p95_latency_s;
    document.getElementById("pulseLatency").textContent = latency !== null && latency !== undefined ? `${latency.toFixed(3)}s` : "--";

    const mem = prom.memory_mb;
    document.getElementById("pulseMemory").textContent = mem !== null && mem !== undefined ? `${mem.toFixed(1)} MB` : "--";

    document.getElementById("pulseWarnings").textContent = k8s.warnings_count ?? 0;

    // Pulse Warning Banner
    const warningBanner = document.getElementById("pulseWarningBanner");
    const warningText = document.getElementById("pulseWarningText");
    if (data.reasons && data.reasons.length > 0) {
      warningBanner.classList.remove("hidden");
      warningText.textContent = data.reasons.join(" • ");
    } else if (k8s.recent_warnings && k8s.recent_warnings.length > 0) {
      warningBanner.classList.remove("hidden");
      warningText.textContent = k8s.recent_warnings[0];
    } else {
      warningBanner.classList.add("hidden");
    }

    // Deep Links
    if (data.deep_links) {
      if (data.deep_links.prometheus) {
        document.getElementById("promDeepLink").href = data.deep_links.prometheus;
      }
      if (data.deep_links.grafana) {
        document.getElementById("grafanaDeepLink").href = data.deep_links.grafana;
      }
    }
  } catch (err) {
    console.debug("Telemetry pulse fetch failed:", err);
  }
}

// ==================== INVESTIGATIONS ====================
function parseProviderAndModel(compoundVal) {
  if (!compoundVal) return { provider: "mock", model: undefined };
  const idx = compoundVal.indexOf(":");
  if (idx === -1) {
    return {
      provider: compoundVal || "mock",
      model: undefined,
    };
  }
  return {
    provider: compoundVal.slice(0, idx) || "mock",
    model: compoundVal.slice(idx + 1) || undefined,
  };
}

async function startRealInvestigation() {
  const ns = document.getElementById("realNamespaceSelect").value || "demo";
  const wl = document.getElementById("realWorkloadSelect").value || "demo-app";
  const modelChoice = document.getElementById("realModelSelect").value;
  const dryRun = document.getElementById("realDryRunCheck").checked;
  const { provider, model } = parseProviderAndModel(modelChoice);

  const btn = document.getElementById("realInvestigateBtn");
  const spinner = document.getElementById("realInvestigateSpinner");
  const btnText = document.getElementById("realInvestigateBtnText");
  const feedback = document.getElementById("investigateFeedback");

  btn.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Correlating Telemetry...";
  feedback.className = "feedback-banner feedback-info";
  feedback.textContent = `Querying Kubernetes pod health, Prometheus metrics, and Loki logs for real workload ${ns}/${wl} using ${provider}...`;
  feedback.classList.remove("hidden");

  try {
    const res = await fetch("/api/incidents/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        namespace: ns,
        workload: wl,
        provider,
        model,
        dry_run: dryRun,
        source: "MANUAL",
      }),
    });

    const report = await res.json();
    if (res.ok) {
      renderIncidentReport(report);
      feedback.classList.add("hidden");
    } else {
      feedback.className = "feedback-banner feedback-error";
      feedback.textContent = `Investigation failed: ${report.error || "Unknown error"}`;
    }
  } catch (err) {
    feedback.className = "feedback-banner feedback-error";
    feedback.textContent = `Network error during investigation: ${err.message}`;
  } finally {
    btn.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "🔍 Investigate Real Workload";
    pollTelemetryPulse();
  }
}

async function startDemoInvestigation() {
  const modelChoice = document.getElementById("demoModelSelect").value;
  const { provider, model } = parseProviderAndModel(modelChoice);

  const btn = document.getElementById("demoInvestigateBtn");
  const spinner = document.getElementById("demoInvestigateSpinner");
  const btnText = document.getElementById("demoInvestigateBtnText");
  const feedback = document.getElementById("investigateFeedback");

  btn.disabled = true;
  spinner.classList.remove("hidden");
  btnText.textContent = "Investigating Chaos...";
  feedback.className = "feedback-banner feedback-info";
  feedback.textContent = `Investigating demo/demo-app failure with ${provider}...`;
  feedback.classList.remove("hidden");

  try {
    const res = await fetch("/api/incidents/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        namespace: "demo",
        workload: "demo-app",
        provider,
        model,
        dry_run: false,
        source: "DEMO",
      }),
    });

    const report = await res.json();
    if (res.ok) {
      renderIncidentReport(report);
      feedback.classList.add("hidden");
    } else {
      feedback.className = "feedback-banner feedback-error";
      feedback.textContent = `Demo investigation failed: ${report.error || "Unknown error"}`;
    }
  } catch (err) {
    feedback.className = "feedback-banner feedback-error";
    feedback.textContent = `Network error: ${err.message}`;
  } finally {
    btn.disabled = false;
    spinner.classList.add("hidden");
    btnText.textContent = "⚡ Investigate Demo Incident";
  }
}

// ==================== REPORT RENDERING ====================
function renderIncidentReport(report) {
  currentIncident = report;
  currentApprovalId = report.approval_id;

  // Show report container, hide empty state
  document.getElementById("emptyResultsState").classList.add("hidden");
  document.getElementById("reportContainer").classList.remove("hidden");

  // Navigation badge & Report badge
  const navBadge = document.getElementById("incidentBadge");
  const reportBadge = document.getElementById("reportStatusBadge");
  const incidentTypeBadge = document.getElementById("reportIncidentType");
  const sourceBadge = document.getElementById("reportSourceBadge");

  navBadge.className = report.status === "RESOLVED" ? "badge badge-success" : (report.status === "PENDING_APPROVAL" ? "badge badge-warning" : "badge badge-info");
  navBadge.innerHTML = `<span class="dot"></span> ${report.status}`;

  reportBadge.className = navBadge.className;
  reportBadge.textContent = report.status;

  incidentTypeBadge.textContent = report.incident_type;
  document.getElementById("reportIncidentId").textContent = report.incident_id;
  sourceBadge.textContent = `SOURCE: ${report.source || "MANUAL"}`;
  sourceBadge.className = report.source === "DEMO" ? "badge badge-warning" : "badge badge-info";

  document.getElementById("reportConfidence").textContent = `${Math.round(report.confidence * 100)}%`;
  document.getElementById("reportSummaryTitle").textContent = report.summary;
  document.getElementById("reportRootCause").textContent = report.root_cause;

  // AI Runtime Card (Provider-neutral local/cloud/mock telemetry)
  const runtimeCard = document.getElementById("llmRuntimeCard");
  if (report.llm_runtime) {
    const rt = report.llm_runtime;
    runtimeCard.classList.remove("hidden");
    const isFallback = (rt.status && rt.status.startsWith("FALLBACK")) || (rt.mode && rt.mode.includes("fallback"));
    if (isFallback) {
      document.getElementById("runtimeModeBadge").textContent = "FALLBACK TO RULE ENGINE";
      document.getElementById("runtimeModeBadge").className = "badge badge-danger";
    } else {
      document.getElementById("runtimeModeBadge").textContent = (rt.mode || "unknown").toUpperCase();
      document.getElementById("runtimeModeBadge").className = rt.mode === "local" ? "badge badge-info" : (rt.mode === "cloud" ? "badge badge-warning" : "badge badge-neutral");
    }

    document.getElementById("runtimeModelName").textContent = `${rt.model} (${rt.provider})`;
    document.getElementById("runtimeLatency").textContent = `${rt.latency_seconds}s`;
    document.getElementById("runtimeSpeed").textContent = rt.tokens_per_second ? `${rt.tokens_per_second} tok/s` : "N/A";

    const promptTokens = rt.prompt_tokens !== null && rt.prompt_tokens !== undefined ? rt.prompt_tokens : "N/A";
    const complTokens = rt.completion_tokens !== null && rt.completion_tokens !== undefined ? rt.completion_tokens : "N/A";
    const totalTokens = rt.total_tokens !== null && rt.total_tokens !== undefined ? rt.total_tokens : "N/A";
    document.getElementById("runtimeTokens").textContent = `${promptTokens} / ${complTokens} / ${totalTokens}`;
  } else {
    runtimeCard.classList.add("hidden");
  }

  // Telemetry Pills
  document.getElementById("pillK8sCount").textContent = (report.evidence_summary && report.evidence_summary.kubernetes) || 0;
  document.getElementById("pillPromCount").textContent = (report.evidence_summary && report.evidence_summary.prometheus) || 0;
  document.getElementById("pillLokiCount").textContent = (report.evidence_summary && report.evidence_summary.loki) || 0;
  document.getElementById("pillDuration").textContent = `${report.duration_seconds}s`;

  // Remediation Card
  document.getElementById("reportRemediationText").textContent = report.recommended_remediation || "No action recommended";
  document.getElementById("reportRiskBadge").textContent = `Risk: ${report.risk_level || "UNKNOWN"}`;
  document.getElementById("reportPolicyBadge").textContent = report.policy_decision || "EVALUATED";
  document.getElementById("reportPolicyReason").textContent = report.policy_reason || "";

  // Human Approval Action Bar
  const approvalBlock = document.getElementById("approvalActionBlock");
  if (report.approval_required && report.status === "PENDING_APPROVAL" && report.approval_id) {
    approvalBlock.classList.remove("hidden");
  } else {
    approvalBlock.classList.add("hidden");
  }

  // Evidence Items List
  const evidenceList = document.getElementById("evidenceList");
  evidenceList.innerHTML = "";
  const items = report.evidence_items || [];
  document.getElementById("evidenceItemCount").textContent = items.length;

  items.forEach((item) => {
    const card = document.createElement("div");
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
        <div style="display:flex;gap:0.4rem;align-items:center;">
          <span class="badge badge-sm ${srcBadgeClass}">${(item.source || "").toUpperCase()}</span>
          <span class="mono text-xs">${item.resource || ""}</span>
        </div>
        <span class="badge badge-sm ${sevBadgeClass}">${item.severity || "INFO"}</span>
      </div>
      <div class="evidence-obs">${item.observation}</div>
      <div class="evidence-query">${item.metric_or_query || ""}</div>
    `;
    evidenceList.appendChild(card);
  });
}

// ==================== APPROVAL MUTATION EXECUTION ====================
async function submitApproval() {
  if (!currentApprovalId) return;
  const operator = document.getElementById("operatorNameInput").value.trim() || "sre-oncall";
  const approveBtn = document.getElementById("approveBtn");
  const rejectBtn = document.getElementById("rejectBtn");

  approveBtn.disabled = true;
  rejectBtn.disabled = true;
  approveBtn.textContent = "Executing Mutation...";

  try {
    const res = await fetch(`/api/approvals/${currentApprovalId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator,
        reason: "Authorized via SRE Operator Console",
      }),
    });

    const summary = await res.json();
    if (res.ok) {
      renderExecutionSummary(summary);
      document.getElementById("approvalActionBlock").classList.add("hidden");
      document.getElementById("reportStatusBadge").className = "badge badge-success";
      document.getElementById("reportStatusBadge").textContent = summary.resolution_status;
      document.getElementById("incidentBadge").className = "badge badge-success";
      document.getElementById("incidentBadge").innerHTML = `<span class="dot"></span> ${summary.resolution_status}`;
    } else {
      alert(`Approval execution failed: ${summary.error || "Unknown error"}`);
    }
  } catch (err) {
    alert(`Network error: ${err.message}`);
  } finally {
    approveBtn.disabled = false;
    rejectBtn.disabled = false;
    approveBtn.textContent = "✅ Approve & Execute";
    fetchStatus();
    pollTelemetryPulse();
  }
}

async function submitRejection() {
  if (!currentApprovalId) return;
  const operator = document.getElementById("operatorNameInput").value.trim() || "sre-oncall";

  try {
    const res = await fetch(`/api/approvals/${currentApprovalId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator,
        reason: "Operator rejected remediation via SRE Operator Console",
      }),
    });

    const data = await res.json();
    if (res.ok) {
      document.getElementById("approvalActionBlock").classList.add("hidden");
      document.getElementById("reportStatusBadge").className = "badge badge-danger";
      document.getElementById("reportStatusBadge").textContent = "REJECTED";
      document.getElementById("incidentBadge").className = "badge badge-neutral";
      document.getElementById("incidentBadge").innerHTML = '<span class="dot"></span> REJECTED';
      alert(`Approval ${currentApprovalId} rejected successfully.`);
    } else {
      alert(`Rejection failed: ${data.error || "Unknown error"}`);
    }
  } catch (err) {
    alert(`Network error: ${err.message}`);
  } finally {
    fetchStatus();
  }
}

function renderExecutionSummary(summary) {
  const card = document.getElementById("executionResultCard");
  card.classList.remove("hidden");

  const resBadge = document.getElementById("execResolutionBadge");
  resBadge.textContent = summary.resolution_status;
  resBadge.className = summary.resolution_status === "RESOLVED" ? "badge badge-success" : "badge badge-danger";

  document.getElementById("execRolloutStatus").textContent = summary.rollout_status;
  document.getElementById("execReplicas").textContent = `${summary.ready_replicas ?? "--"} / ${summary.desired_replicas ?? "--"}`;
  document.getElementById("execMutationStatus").textContent = summary.mutation_status;
  document.getElementById("execId").textContent = summary.execution_id;
}

function updateApprovalsList(approvals) {
  const countBadge = document.getElementById("pendingApprovalsCount");
  const container = document.getElementById("approvalsList");
  countBadge.textContent = approvals.length;

  if (approvals.length === 0) {
    container.innerHTML = '<div class="empty-state text-muted">No pending approvals required right now.</div>';
    return;
  }

  container.innerHTML = "";
  approvals.forEach((app) => {
    const card = document.createElement("div");
    card.className = "approval-card";
    const req = app.action_request || {};
    const target = req.target || {};

    card.innerHTML = `
      <div class="approval-card-header">
        <span class="mono text-xs"><strong>${app.approval_id}</strong></span>
        <span class="badge badge-sm badge-warning">PENDING</span>
      </div>
      <div class="approval-card-body">
        <div><strong>Action:</strong> <code>${req.action || "unknown"}</code></div>
        <div><strong>Target:</strong> <code>${target.namespace || ""}/${target.resource_name || ""}</code></div>
        <div class="text-xs text-muted">Created: ${app.created_at || "just now"}</div>
      </div>
    `;
    container.appendChild(card);
  });
}

// ==================== SYNTHETIC CHAOS TRIGGERS (MODE B) ====================
async function triggerScenario(scenario) {
  const feedback = document.getElementById("investigateFeedback");
  feedback.className = "feedback-banner feedback-info";
  feedback.textContent = `⚡ Triggering synthetic chaos scenario: ${scenario}...`;
  feedback.classList.remove("hidden");

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
      feedback.className = "feedback-banner feedback-success";
      feedback.textContent = `✓ Scenario '${scenario}' successfully initiated on Kubernetes demo/demo-app!`;
      setTimeout(() => feedback.classList.add("hidden"), 6000);
      setTimeout(pollTelemetryPulse, 2000);
    } else {
      feedback.className = "feedback-banner feedback-error";
      feedback.textContent = `Scenario trigger failed: ${data.error || "Unknown error"}`;
    }
  } catch (err) {
    feedback.className = "feedback-banner feedback-error";
    feedback.textContent = `Network error triggering scenario: ${err.message}`;
  }
}
