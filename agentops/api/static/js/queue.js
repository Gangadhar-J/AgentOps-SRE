/**
 * AgentOps SRE - Active & Recent Investigations Queue Module
 */

import { fetchJson, escapeHtml, formatTime } from './api.js';

let isQueueLoading = false;

export async function loadInvestigationsQueue(statusFilter = null) {
  if (isQueueLoading) return;
  isQueueLoading = true;

  const tbody = document.getElementById('investigationsQueueBody');
  const countBadge = document.getElementById('investigationsQueueCount');

  let url = '/api/investigations?limit=25';
  if (statusFilter) {
    url += `&status=${encodeURIComponent(statusFilter)}`;
  }

  try {
    const { ok, data } = await fetchJson(url);
    if (!ok || !data) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-3">Failed to load investigations queue.</td></tr>`;
      }
      return;
    }

    const jobs = data.jobs || [];
    if (countBadge) {
      countBadge.textContent = `${jobs.length} / ${data.count ?? jobs.length}`;
    }

    if (!tbody) return;

    if (jobs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">No automated investigations recorded yet. Start an investigation in the Incident Investigation section.</td></tr>`;
      return;
    }

    tbody.innerHTML = '';
    jobs.forEach((job) => {
      const tr = document.createElement('tr');
      tr.className = `queue-row queue-${(job.status || '').toLowerCase()}`;

      // Status pill styling
      let statusClass = 'status-neutral';
      if (job.status === 'SUCCEEDED') statusClass = 'status-healthy';
      else if (job.status === 'RUNNING') statusClass = 'status-info';
      else if (job.status === 'QUEUED') statusClass = 'status-warning';
      else if (job.status === 'FAILED') statusClass = 'status-danger';

      // Duration calculation
      const durationStr = calculateDuration(job.created_at, job.completed_at, job.status);

      // Action button
      let actionBtn = '';
      if (['QUEUED', 'RUNNING'].includes(job.status)) {
        actionBtn = `<button class="btn-sm btn-primary" onclick="viewInvestigationJob('${job.job_id}')" title="Resume live event stream">⚡ Live Stream</button>`;
      } else if (job.status === 'SUCCEEDED') {
        actionBtn = `<button class="btn-sm btn-secondary" onclick="viewInvestigationJob('${job.job_id}')" title="Reopen Root Cause Analysis report">🔍 View RCA</button>`;
      } else if (job.status === 'FAILED') {
        actionBtn = `<button class="btn-sm btn-secondary" onclick="viewInvestigationJob('${job.job_id}')" title="Inspect failure error report">⚠️ Inspect</button>`;
      } else {
        actionBtn = `<button class="btn-sm btn-secondary" onclick="viewInvestigationJob('${job.job_id}')" title="View job summary">View</button>`;
      }

      tr.innerHTML = `
        <td class="mono font-bold">
          <a href="javascript:void(0)" onclick="viewInvestigationJob('${job.job_id}')" class="text-accent" title="Click to view details">${escapeHtml(job.job_id)}</a>
        </td>
        <td class="text-xs">
          <span title="${escapeHtml(job.created_at || '')}">${formatRelativeTime(job.created_at)}</span>
          ${durationStr ? `<div class="text-muted mono text-xxs mt-1">${durationStr}</div>` : ''}
        </td>
        <td class="mono text-xs">${escapeHtml(job.namespace || '--')}/${escapeHtml(job.workload || '--')}</td>
        <td class="text-xs">
          <span class="badge badge-sm badge-info">${escapeHtml(job.provider || 'ollama')}</span>
          <span class="mono text-xs">${escapeHtml(job.model || '--')}</span>
        </td>
        <td class="text-xs text-muted">${escapeHtml(job.trigger_source || 'MANUAL')}</td>
        <td><span class="status-pill ${statusClass}">${escapeHtml(job.status || 'UNKNOWN')}</span></td>
        <td><span class="stage-badge stage-${(job.stage || 'queued').toLowerCase()}">${escapeHtml((job.stage || 'queued').toUpperCase())}</span></td>
        <td style="text-align: right;">${actionBtn}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load investigations queue:', err);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-3">Error loading queue: ${escapeHtml(err.message)}</td></tr>`;
    }
  } finally {
    isQueueLoading = false;
  }
}

function calculateDuration(createdIso, completedIso, status) {
  if (!createdIso) return '';
  const start = new Date(createdIso).getTime();
  const end = completedIso ? new Date(completedIso).getTime() : Date.now();
  if (isNaN(start) || isNaN(end)) return '';

  const diffMs = Math.max(0, end - start);
  const diffSec = (diffMs / 1000).toFixed(1);
  if (status === 'RUNNING' || status === 'QUEUED') {
    return `running ${diffSec}s`;
  }
  return `took ${diffSec}s`;
}

function formatRelativeTime(isoStr) {
  if (!isoStr) return '--';
  try {
    const date = new Date(isoStr);
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (diffSec < 10) return 'just now';
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHour = Math.floor(diffMin / 60);
    if (diffHour < 24) return `${diffHour}h ago`;
    return formatTime(isoStr);
  } catch (e) {
    return isoStr;
  }
}
