/**
 * AgentOps SRE - Approval Management & Remediation Mutation Module
 */

import { fetchJson, escapeHtml } from './api.js';

let currentApprovalId = null;
let isProcessingApproval = false;

export function setCurrentApprovalId(appId) {
  currentApprovalId = appId;
}

export function getCurrentApprovalId() {
  return currentApprovalId;
}

export function updateApprovalsList(approvals) {
  const container = document.getElementById('pendingApprovalsList');
  if (!container) return;

  if (approvals.length === 0) {
    container.innerHTML = `<p class="text-muted text-center py-4">No pending approvals found. All systems within policy constraints.</p>`;
    return;
  }

  container.innerHTML = '';
  approvals.forEach((app) => {
    const card = document.createElement('div');
    card.className = 'approval-card';
    const req = app.action_request || {};
    const target = req.target || {};

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="mono font-bold text-accent">${escapeHtml(app.approval_id)}</span>
        <span class="status-pill status-warning">PENDING AUTHORIZATION</span>
      </div>
      <div style="margin: 0.5rem 0; font-size: 0.9rem;">
        <div><strong>Action:</strong> <code class="mono">${escapeHtml(req.action || 'unknown')}</code></div>
        <div><strong>Target:</strong> <code class="mono">${escapeHtml(target.namespace || '')}/${escapeHtml(target.resource_name || '')}</code></div>
        <div class="text-xs text-muted" style="margin-top:0.25rem;">Created: ${escapeHtml(app.created_at || 'recently')}</div>
      </div>
      <div style="display:flex; gap:0.5rem; justify-content:flex-end;">
        <button class="btn-sm btn-success btn-approval-action" onclick="approveSpecificId('${app.approval_id}')">Approve &amp; Execute</button>
        <button class="btn-sm btn-danger btn-approval-action" onclick="rejectSpecificId('${app.approval_id}')">Reject</button>
      </div>
    `;
    container.appendChild(card);
  });
}

export async function fetchApprovals() {
  if (window.fetchStatus) {
    await window.fetchStatus();
  }
}

export async function approveCurrentIncident() {
  if (isProcessingApproval) return;
  if (!currentApprovalId) {
    alert('No actionable approval token currently active.');
    return;
  }

  const approveBtn = document.getElementById('btnInlineApprove');
  const allActionBtns = document.querySelectorAll('.btn-approval-action');

  isProcessingApproval = true;
  if (approveBtn) {
    approveBtn.disabled = true;
    approveBtn.innerHTML = '<span class="spinner-sm"></span> Executing Mutation...';
  }
  allActionBtns.forEach((b) => { b.disabled = true; });

  try {
    const { ok, data: summary } = await fetchJson(`/api/approvals/${currentApprovalId}/approve`, {
      method: 'POST',
      body: JSON.stringify({
        operator: 'sre-oncall',
        reason: 'Authorized via Unified Operator Console (v0.9.0)',
      }),
    });

    if (ok && summary) {
      if (window.renderRolloutVerification) {
        window.renderRolloutVerification(summary);
      }
      if (window.switchSection) {
        window.switchSection('approvals');
      }
      const apprBox = document.getElementById('inlineApprovalActionBox');
      if (apprBox) apprBox.style.display = 'none';

      const stBadge = document.getElementById('invStatusBadge');
      if (stBadge) {
        stBadge.textContent = summary.resolution_status || 'RESOLVED';
        stBadge.className = 'status-pill status-healthy';
      }
    } else {
      alert(`Approval execution failed: ${summary?.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Network error during remediation execution: ${err.message}`);
  } finally {
    isProcessingApproval = false;
    if (approveBtn) {
      approveBtn.disabled = false;
      approveBtn.innerHTML = '✓ Authorize &amp; Execute';
    }
    allActionBtns.forEach((b) => { b.disabled = false; });
    if (window.fetchStatus) window.fetchStatus();
    if (window.fetchTelemetryPulse) window.fetchTelemetryPulse();
  }
}

export async function rejectCurrentIncident() {
  if (isProcessingApproval) return;
  if (!currentApprovalId) return;

  const rejectBtn = document.getElementById('btnInlineReject');
  const allActionBtns = document.querySelectorAll('.btn-approval-action');

  isProcessingApproval = true;
  if (rejectBtn) {
    rejectBtn.disabled = true;
    rejectBtn.innerHTML = '<span class="spinner-sm"></span> Rejecting...';
  }
  allActionBtns.forEach((b) => { b.disabled = true; });

  try {
    const { ok, data } = await fetchJson(`/api/approvals/${currentApprovalId}/reject`, {
      method: 'POST',
      body: JSON.stringify({
        operator: 'sre-oncall',
        reason: 'Rejected by SRE operator via Console',
      }),
    });

    if (ok) {
      const apprBox = document.getElementById('inlineApprovalActionBox');
      if (apprBox) apprBox.style.display = 'none';

      const stBadge = document.getElementById('invStatusBadge');
      if (stBadge) {
        stBadge.textContent = 'REJECTED';
        stBadge.className = 'status-pill status-neutral';
      }
      alert(`Approval ${currentApprovalId} rejected.`);
    } else {
      alert(`Rejection failed: ${data?.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Network error: ${err.message}`);
  } finally {
    isProcessingApproval = false;
    if (rejectBtn) {
      rejectBtn.disabled = false;
      rejectBtn.innerHTML = '✕ Reject';
    }
    allActionBtns.forEach((b) => { b.disabled = false; });
    if (window.fetchStatus) window.fetchStatus();
  }
}

export async function approveSpecificId(approvalId) {
  currentApprovalId = approvalId;
  await approveCurrentIncident();
}

export async function rejectSpecificId(approvalId) {
  currentApprovalId = approvalId;
  await rejectCurrentIncident();
}

// Backward compatibility aliases
export const submitApproval = approveCurrentIncident;
export const submitRejection = rejectCurrentIncident;
