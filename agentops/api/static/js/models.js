/**
 * AgentOps SRE - LLM Discovery, Real AI Enforcement & Execution History Module
 */

import { fetchJson, escapeHtml } from './api.js';

export async function fetchLLMModels() {
  try {
    const { ok, data } = await fetchJson('/api/llm/models');
    if (!ok || !data) return;

    const sel = document.getElementById('invModelSelect');
    if (!sel) return;
    sel.innerHTML = '';

    // 1. Ollama local models
    if (data.ollama && data.ollama.available && data.ollama.models.length > 0) {
      const optGroup = document.createElement('optgroup');
      optGroup.label = 'Local Ollama Models (Real Local AI)';
      data.ollama.models.forEach((m) => {
        const opt = document.createElement('option');
        opt.value = `ollama:${m.name}`;
        const paramStr = m.parameter_size !== 'unknown' ? ` (${m.parameter_size})` : '';
        opt.textContent = `🦙 ${m.name}${paramStr}`;
        if (data.default && data.default.provider === 'ollama' && data.default.model === m.name) {
          opt.selected = true;
        }
        optGroup.appendChild(opt);
      });
      sel.appendChild(optGroup);
    }

    // 2. Cloud models
    if (data.cloud && data.cloud.available && data.cloud.providers.length > 0) {
      const optGroup = document.createElement('optgroup');
      optGroup.label = 'Configured Cloud Providers';
      data.cloud.providers.forEach((p) => {
        p.models.forEach((m) => {
          const opt = document.createElement('option');
          opt.value = `${p.provider}:${m}`;
          opt.textContent = `☁️ ${p.name}: ${m}`;
          optGroup.appendChild(opt);
        });
      });
      sel.appendChild(optGroup);
    }

    // If no real models available, prompt user
    if (sel.options.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = "No real LLM found. Start Ollama with 'ollama serve' & pull a model.";
      opt.disabled = true;
      opt.selected = true;
      sel.appendChild(opt);
    }
  } catch (err) {
    console.error('Failed to discover LLM models:', err);
  }
}

export function parseProviderAndModel(compoundVal) {
  if (!compoundVal) return { provider: 'ollama', model: undefined };
  const KNOWN_PROVIDERS = ['ollama', 'openai', 'gemini', 'mock', 'auto'];
  const idx = compoundVal.indexOf(':');
  if (idx !== -1) {
    const pref = compoundVal.slice(0, idx).toLowerCase();
    if (KNOWN_PROVIDERS.includes(pref)) {
      return {
        provider: pref,
        model: compoundVal.slice(idx + 1) || undefined,
      };
    }
  }
  return { provider: 'ollama', model: compoundVal };
}

// 9-Step Lifecycle Visual Stepper Helper
export function updateLifecycleStepper(activeStepIndex, errorStepIndex = null) {
  for (let i = 1; i <= 9; i++) {
    const node = document.getElementById(`step${i}`);
    if (!node) continue;
    node.className = 'step-node';
    if (errorStepIndex === i) {
      node.classList.add('error');
    } else if (i <= activeStepIndex) {
      node.classList.add('active');
    }
  }
}

export async function fetchLLMHistory() {
  try {
    const { ok, data } = await fetchJson('/api/llm/history');
    if (!ok || !data) return;
    const tbody = document.getElementById('llmHistoryTableBody');
    if (!tbody) return;

    const executions = data.history || [];
    if (executions.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted">No model executions recorded yet in this session.</td></tr>`;
      return;
    }

    tbody.innerHTML = '';
    executions.forEach((ex) => {
      const tr = document.createElement('tr');
      const valid = ex.validation_passed !== false;
      tr.innerHTML = `
        <td class="mono text-xs">${escapeHtml(ex.timestamp ? ex.timestamp.split('T')[1]?.slice(0, 8) : '--')}</td>
        <td class="mono text-xs">${escapeHtml(ex.target || '--')}</td>
        <td><span class="badge badge-sm badge-info">${escapeHtml(ex.provider || 'ollama')}</span></td>
        <td class="mono text-xs font-bold">${escapeHtml(ex.model || '--')}</td>
        <td>${ex.latency_seconds !== undefined ? `${ex.latency_seconds}s` : '--'}</td>
        <td class="text-xs">${ex.prompt_tokens ?? '--'} / ${ex.completion_tokens ?? '--'}</td>
        <td class="text-xs">${ex.tokens_per_second ? `${ex.tokens_per_second} tok/s` : '--'}</td>
        <td><span class="status-pill ${ex.status === 'SUCCESS' ? 'status-healthy' : 'status-danger'}">${escapeHtml(ex.status || 'OK')}</span></td>
        <td><span class="status-pill ${valid ? 'status-healthy' : 'status-danger'}">${valid ? 'VALID' : 'INVALID'}</span></td>
        <td class="mono text-xs text-accent">${escapeHtml(ex.incident_id || '--')}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.debug('Failed to fetch LLM history:', err);
  }
}
