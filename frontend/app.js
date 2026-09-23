// Thin client for the real FastAPI backend (app/main.py). No mock data, no
// fake responses -- every state below reflects what the API actually
// returned. Override the backend URL with ?api=http://host:port in the
// address bar, or by setting window.API_BASE before this script loads.
const API_BASE = new URLSearchParams(location.search).get("api") || window.API_BASE || "http://localhost:8000";

const els = {
  status: document.getElementById("apiStatus"),
  apiLabel: document.getElementById("apiBaseLabel"),
  input: document.getElementById("queryInput"),
  submitBtn: document.getElementById("submitBtn"),
  submitLabel: document.getElementById("submitLabel"),
  examples: document.getElementById("examples"),
  result: document.getElementById("resultArea"),
};

els.apiLabel.textContent = API_BASE;

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`, { method: "GET" });
    const data = await res.json();
    if (res.ok && data.status === "ok") {
      els.status.textContent = "backend connected";
      els.status.className = "topbar-sub ok";
    } else {
      throw new Error("not ready");
    }
  } catch (e) {
    els.status.textContent = "backend not reachable — start it with: uvicorn app.main:app --reload";
    els.status.className = "topbar-sub down";
  }
}

function renderLoading() {
  els.result.hidden = false;
  els.result.innerHTML = `
    <div class="state-block">
      <h2>Working on it…</h2>
      <p>Matching your description against Samsung reference data and the Settings deeplink catalog.</p>
    </div>`;
}

function renderError(message) {
  els.result.hidden = false;
  els.result.innerHTML = `
    <div class="state-block error">
      <h2>Couldn't reach the engine</h2>
      <p>${escapeHtml(message)}</p>
    </div>`;
}

function renderEmpty(fallback) {
  const reason = fallback === "no_siis_context"
    ? "This description doesn't match anything in the pre-loaded reference data yet, and no siis_response was supplied for a fresh lookup. Try one of the sample scenarios above — those are backed by real Samsung reference text."
    : "No troubleshooting steps could be grounded in the supplied reference text for this query.";
  els.result.hidden = false;
  els.result.innerHTML = `
    <div class="state-block">
      <h2>No grounded match yet</h2>
      <p>${escapeHtml(reason)}</p>
    </div>`;
}

function categoryLabel(cat) {
  return { auto: "One-tap setting", critical: "Disruptive — do last", manual: "Manual / no deeplink" }[cat] || cat;
}

function renderResults(payload, query) {
  const { response, meta } = payload;
  const contexts = response.contexts || [];
  if (contexts.length === 0) {
    renderEmpty(meta.fallback);
    return;
  }

  let stepCounter = 0;
  const goalsHtml = contexts.map(goal => {
    const actionsHtml = goal.actions.map(action => {
      stepCounter += 1;
      const group = action.stepGroups[0] || { steps: [], actionableDeeplink: null };
      const stepsHtml = group.steps.map(s => `<li>${escapeHtml(s)}</li>`).join("");
      const deeplinkHtml = group.actionableDeeplink
        ? `<div class="deeplink-btn" title="${escapeHtml(group.actionableDeeplink.deeplink)}">
             <span class="dot"></span>${escapeHtml(group.actionableDeeplink.message || "Open setting")}
           </div>`
        : `<div class="no-deeplink">No deeplink — ${action.category === "manual" ? "physical step, opens no screen" : "not in the settings catalog"}</div>`;

      return `
        <div class="action-card">
          <div class="action-head">
            <div class="step-num">${stepCounter}</div>
            <div class="action-name">${escapeHtml(action.actionName)}</div>
            <div class="category-badge ${action.category}">${categoryLabel(action.category)}</div>
          </div>
          <p class="action-desc">${escapeHtml(action.description)}</p>
          <ol class="steps-list">${stepsHtml}</ol>
          ${deeplinkHtml}
          <div class="action-feedback">
            <button class="step-feedback" data-action="${escapeHtml(action.actionName)}" data-feedback="solved">Worked</button>
            <button class="step-feedback" data-action="${escapeHtml(action.actionName)}" data-feedback="not_solved">Didn't work</button>
          </div>
        </div>`;
    }).join("");

    return `<div class="goal-title">${escapeHtml(goal.title)}</div>${actionsHtml}`;
  }).join("");

  const cacheNote = meta.cache_hit
    ? `cache hit${meta.cache_exact === false ? " (semantic)" : " (exact)"}`
    : "computed fresh";

  els.result.hidden = false;
  els.result.innerHTML = `
    <div class="meta-row">
      <span><b>${meta.latency_ms}ms</b> · ${cacheNote}</span>
      <span>model: <b>${escapeHtml(meta.model)}</b></span>
    </div>
    <div id="aiGuidance" class="ai-guidance">
      <div class="ai-title">AI guide</div>
      <div class="ai-body">Using your grounded troubleshooting steps…</div>
    </div>
    ${goalsHtml}
    <div class="experience-panel">
      <div class="experience-title">Teach the assistant from your experience</div>
      <p>Did these steps solve your problem? Your feedback is stored locally and can help with similar future complaints.</p>
      <textarea id="feedbackNote" rows="2" placeholder="Optional: tell us what happened…"></textarea>
      <div class="feedback-actions">
        <button class="feedback-btn solved" data-feedback="solved">✓ It solved my issue</button>
        <button class="feedback-btn not-solved" data-feedback="not_solved">✕ It did not solve it</button>
      </div>
      <div id="feedbackStatus" class="feedback-status"></div>
    </div>
  `;
  loadAiGuidance(query, payload.response);
}

async function submitQuery() {
  const query = els.input.value.trim();
  if (!query) {
    els.input.focus();
    return;
  }
  els.submitBtn.disabled = true;
  els.submitLabel.textContent = "Working…";
  renderLoading();

  try {
    const res = await fetch(`${API_BASE}/v1/troubleshoot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    renderResults(data, query);
  } catch (e) {
    renderError(e.message || "Network error — is the backend running?");
  } finally {
    els.submitBtn.disabled = false;
    els.submitLabel.textContent = "Get guided steps";
  }
}

els.submitBtn.addEventListener("click", submitQuery);
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitQuery();
});
els.examples.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  els.input.value = chip.dataset.q;
  submitQuery();
});

checkHealth();


async function loadAiGuidance(query, groundedResponse) {
  const box = document.getElementById("aiGuidance");
  if (!box) return;
  try {
    const res = await fetch(`${API_BASE}/v1/guidance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, response: groundedResponse }),
    });
    if (!res.ok) throw new Error(`Guidance server returned ${res.status}`);
    const data = await res.json();
    const g = data.guidance || {};
    box.innerHTML = `
      <div class="ai-title">AI guide <span class="ai-model">${escapeHtml(data.model || "Groq")}</span></div>
      <div class="ai-body">${escapeHtml(g.message || "")}</div>
      ${g.experience_insight ? `<div class="ai-insight">From similar user experience: ${escapeHtml(g.experience_insight)}</div>` : ""}
      ${g.next_question ? `<div class="ai-question">${escapeHtml(g.next_question)}</div>` : ""}
    `;
  } catch (e) {
    box.innerHTML = `
      <div class="ai-title">AI guide</div>
      <div class="ai-body">The grounded troubleshooting steps are ready. AI guidance is temporarily unavailable.</div>
    `;
  }
}

async function sendFeedback(query, outcome, actionName = null, note = "") {
  const status = document.getElementById("feedbackStatus");
  try {
    const res = await fetch(`${API_BASE}/v1/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        outcome,
        action_name: actionName,
        note,
      }),
    });
    if (!res.ok) throw new Error(`Feedback server returned ${res.status}`);
    const data = await res.json();
    if (status) {
      status.textContent = `Saved ✓ — experience memory now has ${data.experience_memory_size} record(s).`;
    }
  } catch (e) {
    if (status) status.textContent = "Could not save feedback.";
  }
}

els.result.addEventListener("click", (e) => {
  const stepButton = e.target.closest(".step-feedback");
  if (stepButton) {
    const query = els.input.value.trim();
    sendFeedback(
      query,
      stepButton.dataset.feedback,
      stepButton.dataset.action,
      ""
    );
    stepButton.textContent = "Saved ✓";
    stepButton.disabled = true;
    return;
  }

  const overallButton = e.target.closest(".feedback-btn");
  if (overallButton) {
    const query = els.input.value.trim();
    const note = document.getElementById("feedbackNote")?.value || "";
    sendFeedback(query, overallButton.dataset.feedback, null, note);
    overallButton.textContent = "Saved ✓";
    overallButton.disabled = true;
  }
});
