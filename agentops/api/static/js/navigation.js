/**
 * AgentOps SRE - Navigation & Section Switching Module
 */

const sectionMap = {
  overview: { tab: 'navTabOverview', sec: 'sectionOverview' },
  cluster: { tab: 'navTabCluster', sec: 'sectionCluster' },
  investigation: { tab: 'navTabInvestigation', sec: 'sectionInvestigation' },
  llm: { tab: 'navTabLLM', sec: 'sectionLLM' },
  evidence: { tab: 'navTabEvidence', sec: 'sectionEvidence' },
  approvals: { tab: 'navTabApprovals', sec: 'sectionApprovals' },
  dashboards: { tab: 'navTabDashboards', sec: 'sectionDashboards' },
  alerts: { tab: 'navTabAlerts', sec: 'sectionAlerts' },
  evaluation: { tab: 'navTabEvaluation', sec: 'sectionEvaluation' },
  diagnostics: { tab: 'navTabDiagnostics', sec: 'sectionDiagnostics' },
};

export function switchSection(sectionId) {
  if (!sectionMap[sectionId]) return;

  Object.keys(sectionMap).forEach((key) => {
    const tabEl = document.getElementById(sectionMap[key].tab);
    const secEl = document.getElementById(sectionMap[key].sec);
    if (tabEl) tabEl.classList.remove('active');
    if (secEl) {
      secEl.classList.remove('active');
      secEl.style.display = 'none';
    }
  });

  const activeTab = document.getElementById(sectionMap[sectionId].tab);
  const activeSec = document.getElementById(sectionMap[sectionId].sec);
  if (activeTab) activeTab.classList.add('active');
  if (activeSec) {
    activeSec.classList.add('active');
    activeSec.style.display = 'block';
  }

  // Trigger lifecycle updates on section switch
  if (sectionId === 'overview') {
    if (window.fetchTelemetryPulse) window.fetchTelemetryPulse();
    if (window.loadInvestigationsQueue) window.loadInvestigationsQueue();
  } else if (sectionId === 'cluster') {
    if (window.loadClusterOverview) window.loadClusterOverview();
    if (window.loadClusterWorkloadData) window.loadClusterWorkloadData();
  } else if (sectionId === 'llm') {
    if (window.fetchLLMHistory) window.fetchLLMHistory();
  } else if (sectionId === 'approvals') {
    if (window.fetchApprovals) window.fetchApprovals();
  } else if (sectionId === 'dashboards') {
    if (window.initDashboards) window.initDashboards();
  } else if (sectionId === 'alerts') {
    if (window.loadAlertsHistory) window.loadAlertsHistory();
  } else if (sectionId === 'diagnostics') {
    if (window.fetchStatus) window.fetchStatus();
  }
}

export function navigateToEvidence(evidenceId) {
  switchSection('evidence');
  setTimeout(() => {
    const targetCard = document.getElementById(`evidence-card-${evidenceId}`);
    if (targetCard) {
      targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      targetCard.classList.add('highlight-pulse');
      setTimeout(() => targetCard.classList.remove('highlight-pulse'), 2500);
    }
  }, 100);
}

// Backward compatibility alias
export function switchMode(mode) {
  if (mode === 'demo') {
    if (window.toggleChaosDrawer) window.toggleChaosDrawer();
  } else {
    switchSection('investigation');
  }
}
