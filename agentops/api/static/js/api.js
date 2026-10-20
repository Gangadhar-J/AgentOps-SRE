/**
 * AgentOps SRE - Core API Client & SSE Stream Utilities
 */

export async function fetchJson(url, options = {}) {
  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });

    const contentType = res.headers.get('content-type') || '';
    let data = null;
    if (contentType.includes('application/json')) {
      data = await res.json();
    } else {
      const text = await res.text();
      data = { raw: text };
    }

    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    console.error(`API request failed for ${url}:`, err);
    return { ok: false, status: 0, error: err.message || 'Network error' };
  }
}

export function connectSSE(url, { onEvent, onError, onComplete, lastEventId = null }) {
  let streamUrl = url;
  if (lastEventId) {
    const separator = streamUrl.includes('?') ? '&' : '?';
    streamUrl += `${separator}after=${encodeURIComponent(lastEventId)}`;
  }

  const eventSource = new EventSource(streamUrl);

  eventSource.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      if (onEvent) onEvent(parsed, event.lastEventId);
    } catch (e) {
      console.debug('SSE raw message:', event.data);
    }
  };

  eventSource.addEventListener('done', (event) => {
    try {
      const parsed = JSON.parse(event.data);
      if (onComplete) onComplete(parsed);
    } catch (e) {
      if (onComplete) onComplete({});
    }
    eventSource.close();
  });

  // Listen to standard custom event types emitted by AgentOps
  const standardEvents = [
    'investigation_queued',
    'investigation_started',
    'collecting_kubernetes',
    'querying_prometheus',
    'querying_loki',
    'evidence_collection_completed',
    'llm_inference_started',
    'llm_inference_completed',
    'validating_rca',
    'evaluating_policy',
    'investigation_completed',
    'investigation_failed',
    'investigation_cancelled',
  ];

  standardEvents.forEach((eventType) => {
    eventSource.addEventListener(eventType, (event) => {
      try {
        const parsed = JSON.parse(event.data);
        if (onEvent) onEvent(parsed, event.lastEventId);
      } catch (e) {
        console.debug(`SSE event ${eventType}:`, event.data);
      }
    });
  });

  eventSource.onerror = (err) => {
    if (onError) onError(err);
  };

  return eventSource;
}
