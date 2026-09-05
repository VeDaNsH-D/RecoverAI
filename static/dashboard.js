/**
 * RecoverAI — Merchant Recovery Command Center
 * Razorpay Enterprise Recovery Console (Track 03)
 * 
 * Strict Invariants:
 * 1. Observability and control surface ONLY.
 * 2. 64-bit integer paise financial handling via formatPaiseINR().
 * 3. Privacy-protected masked customer IDs (cust_••••XXXX).
 * 4. Zero external UI dependencies (Pure HTML5, SVG, ES6).
 */

(function () {
  "use strict";

  // =========================================================================
  // APPLICATION STATE
  // =========================================================================

  const state = {
    activeView: "view-pipeline",
    overview: null,
    cases: [],
    selectedCase: null,
    selectedCaseCandidates: null,
    queue: {
      page: 0,
      limit: 15,
      totalCount: 0,
      search: "",
      state: "",
      action: "",
      failureType: "",
      isSubscription: "",
    },
    autoRefreshInterval: 10000,
  };

  // =========================================================================
  // FORMATTING & DATA UTILITIES
  // =========================================================================

  function formatPaiseINR(paise) {
    if (paise === null || paise === undefined || isNaN(paise)) return "₹0.00";
    const inr = Number(paise) / 100.0;
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(inr);
  }

  function formatPercent(rate) {
    if (rate === null || rate === undefined || isNaN(rate)) return "0.0%";
    return (Number(rate) * 100).toFixed(1) + "%";
  }

  function maskCustomerId(id) {
    if (!id) return "cust_••••";
    if (id.length <= 8) return id;
    return `${id.substring(0, 5)}••••${id.substring(id.length - 4)}`;
  }

  function formatTimestamp(isoStr) {
    if (!isoStr) return "-";
    try {
      return new Date(isoStr).toLocaleString("en-IN", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return isoStr;
    }
  }

  function escapeHTML(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /** Formats raw paise in descriptions to Indian Rupees (e.g. "600000 paise" -> "₹6,000.00") */
  function formatDescriptionRupees(desc) {
    if (!desc) return "";
    return desc.replace(/(\d+)\s*paise/gi, (match, paise) => {
      return formatPaiseINR(parseInt(paise, 10));
    });
  }

  // =========================================================================
  // API CLIENT
  // =========================================================================

  async function fetchAPI(url, options = {}) {
    try {
      const res = await fetch(url, {
        headers: { "Content-Type": "application/json", ...options.headers },
        ...options,
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const j = await res.json();
          detail = j.detail || j.error?.message || detail;
        } catch (_) {}
        throw new Error(detail);
      }
      return await res.json();
    } catch (err) {
      console.error(`Fetch error ${url}:`, err);
      throw err;
    }
  }

  // =========================================================================
  // VIEW SWITCHER & NAVIGATION
  // =========================================================================

  function switchView(viewId) {
    state.activeView = viewId;

    document.querySelectorAll(".nav-tab-btn[data-view]").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view-panel").forEach((p) => p.classList.remove("active"));

    const targetBtn = document.querySelector(`.nav-tab-btn[data-view="${viewId}"]`);
    const targetPanel = document.getElementById(viewId);

    if (targetBtn) targetBtn.classList.add("active");
    if (targetPanel) targetPanel.classList.add("active");

    if (viewId === "view-pipeline") {
      renderPipelineView();
    } else if (viewId === "view-queue") {
      loadCasesQueue();
    } else if (viewId === "view-analytics") {
      renderFunnel();
      loadTrends();
    }
  }

  // =========================================================================
  // VIEW 1: RECOVERY PIPELINE OVERVIEW
  // =========================================================================

  function renderPipelineView() {
    if (!state.overview) return;
    const data = state.overview;
    const funnel = data.funnel || {};

    // Update pipeline stage counts
    const elRisk = document.getElementById("pipeAtRisk");
    if (elRisk) elRisk.textContent = funnel.cases_at_risk || data.total_cases || 0;

    const elDecided = document.getElementById("pipeDecided");
    if (elDecided) elDecided.textContent = funnel.decisions_evaluated || data.decisions_made || 0;

    const elActioned = document.getElementById("pipeActioned");
    if (elActioned) elActioned.textContent = funnel.interventions_dispatched || data.actions_attempted || 0;

    const elSettled = document.getElementById("pipeSettled");
    if (elSettled) elSettled.textContent = funnel.successful_executions || data.actions_executed || 0;

    const elRecovered = document.getElementById("pipeRecovered");
    if (elRecovered) elRecovered.textContent = funnel.recovered_outcomes || data.recovered_cases || 0;

    // Update financial summary
    const elRiskAmt = document.getElementById("pipeRevenueAtRisk");
    if (elRiskAmt) elRiskAmt.textContent = formatPaiseINR(data.total_amount_at_risk_paise);

    const elNet = document.getElementById("pipeNetRecovered");
    if (elNet) elNet.textContent = formatPaiseINR(data.recoverai_net_recovered_paise);

    const elRate = document.getElementById("pipeRecoveryRate");
    if (elRate) elRate.textContent = formatPercent(data.recovery_rate);

    const elCosts = document.getElementById("pipeActionCosts");
    if (elCosts) elCosts.textContent = formatPaiseINR(data.total_action_cost_paise);

    // Render recent activity feed from cases
    renderActivityFeed();
  }

  function renderActivityFeed() {
    const feed = document.getElementById("pipelineActivityFeed");
    if (!feed || !state.cases || state.cases.length === 0) return;

    // Sort cases by created_at descending, take top 8
    const recentCases = [...state.cases]
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
      .slice(0, 8);

    let html = "";
    recentCases.forEach((c) => {
      const stateColor = c.current_state === "RECOVERED" ? "#34d399"
        : c.current_state === "DECIDED" ? "#38bdf8"
        : c.current_state === "ACTION_EXECUTED" ? "#a78bfa"
        : c.current_state === "EXECUTION_FAILED" ? "#fb7185"
        : c.current_state === "NOT_RECOVERED" ? "#fb7185"
        : "#fbbf24";
      const stateLabel = c.current_state === "RECOVERED" ? "Recovered"
        : c.current_state === "DECIDED" ? "Decision Made"
        : c.current_state === "ACTION_EXECUTED" ? "Action Executed"
        : c.current_state === "EXECUTION_FAILED" ? "Execution Failed"
        : c.current_state === "NOT_RECOVERED" ? "Not Recovered"
        : "Pending";
      const amountColor = c.current_state === "RECOVERED" ? "text-emerald" : "text-amber";

      html += `
        <div class="activity-event" onclick="window.inspectCase('${escapeHTML(c.case_id)}')">
          <div class="activity-dot" style="background:${stateColor};box-shadow:0 0 8px ${stateColor};"></div>
          <div class="activity-info">
            <div>
              <div class="activity-title">${stateLabel} — ${escapeHTML(c.recommended_action)}</div>
              <div class="activity-meta">${escapeHTML(c.case_id)} • ${maskCustomerId(c.customer_id)} • ${c.is_subscription ? 'Subscription' : 'One-Off'}</div>
            </div>
            <div class="activity-amount ${amountColor}">${formatPaiseINR(c.amount_paise)}</div>
          </div>
        </div>
      `;
    });
    feed.innerHTML = html;
  }

  // =========================================================================
  // VIEW 2: HIGH-DENSITY RECOVERY QUEUE
  // =========================================================================

  async function loadCasesQueue() {
    const tbody = document.getElementById("casesTableBody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="10" class="text-center text-dim mono" style="padding:2.5rem;">[FETCHING RECOVERY QUEUE TELEMETRY...]</td></tr>`;

    const params = new URLSearchParams();
    params.set("limit", state.queue.limit);
    params.set("offset", state.queue.page * state.queue.limit);
    if (state.queue.search) params.set("search", state.queue.search);
    if (state.queue.state) params.set("state", state.queue.state);
    if (state.queue.action) params.set("action", state.queue.action);
    if (state.queue.failureType) params.set("failure_type", state.queue.failureType);
    if (state.queue.isSubscription !== "") params.set("is_subscription", state.queue.isSubscription);

    try {
      const data = await fetchAPI(`/api/v1/recovery/cases?${params.toString()}`);
      state.queue.totalCount = data.total_count;
      
      const badge = document.getElementById("queueBadgeCount");
      if (badge) badge.textContent = data.total_count;

      const totalPages = Math.ceil(data.total_count / state.queue.limit) || 1;
      const currentPage = state.queue.page + 1;
      
      const infoEl = document.getElementById("paginationInfo");
      if (infoEl) infoEl.textContent = `Showing ${data.items.length} of ${data.total_count} cases`;
      
      const pageEl = document.getElementById("pageIndicator");
      if (pageEl) pageEl.textContent = `Page ${currentPage} of ${totalPages}`;
      
      const prevBtn = document.getElementById("prevPageBtn");
      if (prevBtn) prevBtn.disabled = state.queue.page <= 0;
      
      const nextBtn = document.getElementById("nextPageBtn");
      if (nextBtn) nextBtn.disabled = currentPage >= totalPages;

      if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="text-center text-dim mono" style="padding:2.5rem;">No cases match active filter criteria.</td></tr>`;
        return;
      }

      let rows = "";
      data.items.forEach((c) => {
        const stateColorClass = c.current_state === 'RECOVERED' ? 'text-emerald' : (c.current_state === 'DECIDED' ? 'text-cyan' : 'text-amber');
        rows += `
          <tr>
            <td class="mono font-bold text-bright">${escapeHTML(c.case_id)}</td>
            <td class="mono text-dim">${escapeHTML(maskCustomerId(c.customer_id))}</td>
            <td class="mono font-bold text-bright">${formatPaiseINR(c.amount_paise)}</td>
            <td><span class="mono text-xs font-bold ${stateColorClass}">${escapeHTML(c.current_state)}</span></td>
            <td><span class="mono text-xs text-cyan font-bold">${escapeHTML(c.recommended_action)}</span></td>
            <td class="mono text-dim text-xs">${escapeHTML(c.failure_type || "temporary")}</td>
            <td class="mono text-center">${c.retry_count}</td>
            <td class="text-xs text-dim">${c.is_subscription ? 'Subscription' : 'One-Off'}</td>
            <td class="text-xs text-dim mono">${formatTimestamp(c.created_at)}</td>
            <td>
              <button class="btn-pill" style="padding:0.25rem 0.65rem;font-size:0.75rem;" onclick="window.inspectCase('${escapeHTML(c.case_id)}')">
                Inspect
              </button>
            </td>
          </tr>
        `;
      });
      tbody.innerHTML = rows;
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="10" class="text-center text-rose mono" style="padding:2.5rem;">Error loading queue: ${escapeHTML(err.message)}</td></tr>`;
    }
  }

  // =========================================================================
  // VIEW 3: ANALYTICS & RECOVERY FUNNEL
  // =========================================================================

  function renderFunnel() {
    const container = document.getElementById("funnelContainer");
    if (!container || !state.overview) return;

    const data = state.overview;
    const funnel = data.funnel || {
      cases_at_risk: data.total_cases,
      decisions_evaluated: data.decisions_made,
      interventions_dispatched: data.actions_attempted,
      successful_executions: data.actions_executed,
      recovered_outcomes: data.recovered_cases,
    };

    const baseCount = Math.max(funnel.cases_at_risk, 1);
    const stages = [
      {
        num: "01",
        name: "AT RISK",
        desc: "Total Detected Failures",
        count: funnel.cases_at_risk,
        amount: data.total_amount_at_risk_paise,
        pct: 100,
        gradient: "linear-gradient(90deg, #d97706 0%, #f59e0b 50%, #fbbf24 100%)",
        borderColor: "rgba(245, 158, 11, 0.35)",
        textColor: "text-amber",
      },
      {
        num: "02",
        name: "DECIDED",
        desc: "ML Uplift Evaluated",
        count: funnel.decisions_evaluated,
        amount: null,
        pct: (funnel.decisions_evaluated / baseCount) * 100,
        gradient: "linear-gradient(90deg, #0284c7 0%, #06b6d4 50%, #38bdf8 100%)",
        borderColor: "rgba(6, 182, 212, 0.35)",
        textColor: "text-cyan",
      },
      {
        num: "03",
        name: "ACTIONED",
        desc: "Interventions Dispatched",
        count: funnel.interventions_dispatched,
        amount: null,
        pct: (funnel.interventions_dispatched / baseCount) * 100,
        gradient: "linear-gradient(90deg, #2563eb 0%, #3b82f6 50%, #60a5fa 100%)",
        borderColor: "rgba(59, 130, 246, 0.35)",
        textColor: "text-bright",
      },
      {
        num: "04",
        name: "SETTLED",
        desc: "Invoice Proof Verified",
        count: funnel.successful_executions,
        amount: null,
        pct: (funnel.successful_executions / baseCount) * 100,
        gradient: "linear-gradient(90deg, #7c3aed 0%, #8b5cf6 50%, #a78bfa 100%)",
        borderColor: "rgba(139, 92, 246, 0.35)",
        textColor: "text-violet",
      },
      {
        num: "05",
        name: "RECOVERED",
        desc: "Net Revenue Attributed",
        count: funnel.recovered_outcomes,
        amount: data.recoverai_gross_recovered_paise || data.gross_recovered_paise,
        pct: (funnel.recovered_outcomes / baseCount) * 100,
        gradient: "linear-gradient(90deg, #059669 0%, #10b981 50%, #34d399 100%)",
        borderColor: "rgba(16, 185, 129, 0.35)",
        textColor: "text-emerald",
      },
    ];

    let html = `<div class="funnel-rows-wrapper">`;
    stages.forEach((s) => {
      const widthPct = Math.max(8, Math.min(100, s.pct));
      const amountStr = s.amount !== null ? ` • ${formatPaiseINR(s.amount)}` : "";
      const retentionPct = s.pct.toFixed(1);

      html += `
        <div class="funnel-stage-row">
          <!-- Stage Identity -->
          <div class="funnel-stage-meta">
            <span class="funnel-stage-badge ${s.textColor}">${s.num}. ${s.name}</span>
            <span class="funnel-stage-desc">${s.desc}</span>
          </div>

          <!-- Progress Track -->
          <div class="funnel-bar-track">
            <div class="funnel-bar-fill" style="width:${widthPct}%;background:${s.gradient};box-shadow:0 0 15px ${s.borderColor};">
              <span class="funnel-bar-count-pill mono">${s.count} <span class="funnel-bar-pct">(${retentionPct}%)</span></span>
            </div>
          </div>

          <!-- Financial / Case Counts -->
          <div class="funnel-stage-metrics">
            <div class="funnel-metrics-primary mono">${s.count} cases${amountStr}</div>
            <div class="funnel-metrics-sub mono text-dim">${retentionPct}% retention</div>
          </div>
        </div>
      `;
    });
    html += `</div>`;
    container.innerHTML = html;
  }

  async function loadTrends() {
    const container = document.getElementById("trendChartContainer");
    if (!container) return;
    const interval = document.getElementById("trendIntervalSelect")?.value || "daily";

    try {
      const trends = await fetchAPI(`/api/v1/analytics/trends?interval=${interval}`);
      if (!trends || trends.length === 0) {
        container.innerHTML = `<div class="text-dim text-xs mono text-center" style="padding:3rem;">No trend data available</div>`;
        return;
      }

      const maxGross = Math.max(...trends.map((t) => t.gross_recovered_paise), 1);
      let chartHtml = `<div class="razor-bar-chart">`;
      trends.forEach((t) => {
        const heightPx = Math.max(12, Math.round((t.gross_recovered_paise / maxGross) * 125));
        chartHtml += `
          <div class="razor-bar-col">
            <div class="razor-bar-val text-emerald mono">${formatPaiseINR(t.gross_recovered_paise)}</div>
            <div class="razor-bar-track">
              <div class="razor-bar-fill" style="height:${heightPx}px;" title="Gross: ${formatPaiseINR(t.gross_recovered_paise)} | Net: ${formatPaiseINR(t.net_recovered_paise)}"></div>
            </div>
            <div class="razor-bar-date mono">${escapeHTML(t.time_bucket.slice(5))}</div>
            <div class="razor-bar-subinfo">Cost: ${formatPaiseINR(t.action_cost_paise)}</div>
          </div>
        `;
      });
      chartHtml += `</div>`;
      container.innerHTML = chartHtml;
    } catch (_) {}
  }

  // =========================================================================
  // RIGHT SLIDE-OUT DEEP INSPECTION DRAWER
  // =========================================================================

  async function inspectCase(caseId, openDrawer = true) {
    const drawer = document.getElementById("caseDetailModal");
    if (openDrawer && drawer) drawer.classList.add("open");

    try {
      const [detail, timelineData] = await Promise.all([
        fetchAPI(`/api/v1/recovery/cases/${encodeURIComponent(caseId)}`),
        fetchAPI(`/api/v1/recovery/cases/${encodeURIComponent(caseId)}/timeline`),
      ]);

      const c = detail.case;
      state.selectedCase = c;

      // Extract candidate actions from API response
      if (detail.decision_forecast && detail.decision_forecast.candidate_actions) {
        state.selectedCaseCandidates = detail.decision_forecast.candidate_actions.map(ca => ({
          name: ca.action || ca.recommended_action,
          prob: ca.recovery_probability,
          cost: ca.action_cost_paise,
          allowed: ca.allowed,
          disqualification_reason: ca.disqualification_reason,
        }));
      } else {
        state.selectedCaseCandidates = null;
      }

      // Update Header
      document.getElementById("modalCaseTitle").textContent = `Case ${c.case_id}`;
      document.getElementById("modalCaseSubtitle").textContent = `Customer: ${maskCustomerId(c.customer_id)} • Created: ${formatTimestamp(c.created_at)}`;
      document.getElementById("dtCategoryTag").textContent = c.is_subscription ? "SUBSCRIPTION BILLING CYCLE" : "ONE-OFF CHECKOUT";

      // Linked SaaS Subscription Details
      const subBox = document.getElementById("dtSubscriptionDetailsBox");
      if (subBox) {
        if (c.is_subscription || c.subscription_id) {
          subBox.style.display = "block";
          document.getElementById("dtSubId").textContent = c.subscription_id || "sub_active";
          document.getElementById("dtBillingCycleId").textContent = c.billing_cycle_id || "-";
        } else {
          subBox.style.display = "none";
        }
      }

      // Radial Recovery Probability Gauge
      const prob = detail.decision_forecast ? detail.decision_forecast.recovery_probability : 0;
      const probPct = Math.round(prob * 100);
      document.getElementById("dtGaugeScore").textContent = `${probPct}%`;

      const circle = document.getElementById("dtRadialCircleFill");
      if (circle) {
        const circumference = 2 * Math.PI * 28; // ~175.9
        const offset = circumference - (prob * circumference);
        circle.style.strokeDasharray = `${circumference}`;
        circle.style.strokeDashoffset = `${offset}`;
      }

      // Update 2x2 Metric Cards
      document.getElementById("dtAmount").textContent = formatPaiseINR(c.amount_paise);
      document.getElementById("dtDecCost").textContent = formatPaiseINR(detail.decision_forecast?.action_cost_paise || 0);
      document.getElementById("dtDecNet").textContent = formatPaiseINR(detail.decision_forecast?.expected_net_recovery_paise || 0);
      
      const outStatusEl = document.getElementById("dtOutStatus");
      if (outStatusEl) {
        outStatusEl.textContent = c.current_state;
        outStatusEl.className = `drawer-metric-val ${c.current_state === 'RECOVERED' ? 'text-emerald' : (c.current_state === 'DECIDED' ? 'text-cyan' : 'text-amber')}`;
      }

      // Show attribution source if available
      const attrEl = document.getElementById("dtAttribution");
      if (attrEl) {
        const source = c.resolution_source || (c.current_state === 'RECOVERED' ? 'recoverai_intervention' : '—');
        const sourceLabel = source === 'recoverai_intervention' ? 'RecoverAI Intervention'
          : source === 'provider_auto_retry' ? 'Provider Auto-Retry'
          : source;
        attrEl.textContent = sourceLabel;
        attrEl.className = `drawer-metric-val ${source === 'recoverai_intervention' ? 'text-emerald' : (source === 'provider_auto_retry' ? 'text-violet' : 'text-dim')}`;
      }

      // Show settlement evidence if outcome exists
      const evidenceEl = document.getElementById("dtSettlementEvidence");
      if (evidenceEl) {
        if (detail.outcome_settlement) {
          const out = detail.outcome_settlement;
          evidenceEl.textContent = out.provider_reference || '—';
          evidenceEl.style.display = 'block';
        } else {
          evidenceEl.style.display = 'none';
        }
      }

      // AI Policy Rationale
      if (detail.decision_forecast) {
        document.getElementById("dtDecAction").textContent = detail.decision_forecast.recommended_action.toUpperCase();
        document.getElementById("dtDecExplanation").textContent = formatDescriptionRupees(detail.decision_forecast.explanation);
      }

      // Candidate Matrix in Drawer
      renderCandidateMatrixTable(detail.decision_forecast, c);

      // Audit Timeline
      renderTimeline(timelineData.events);

    } catch (err) {
      console.warn("Error opening case detail:", err);
    }
  }

  function renderCandidateMatrixTable(decision, caseItem) {
    const tbody = document.getElementById("dtCandidateTableBody");
    if (!tbody) return;

    const actions = state.selectedCaseCandidates || [
      { name: decision?.recommended_action || caseItem.recommended_action, prob: decision?.recovery_probability || 0, cost: decision?.action_cost_paise || 0 },
    ];

    let html = "";
    actions.forEach((act) => {
      const isSelected = decision ? (act.name === decision.recommended_action) : (act.name === caseItem.recommended_action);
      const gross = Math.floor(act.prob * caseItem.amount_paise);
      const net = gross - act.cost;

      html += `
        <tr class="${isSelected ? 'selected' : ''}">
          <td class="mono font-bold">${act.name.toUpperCase()}</td>
          <td class="mono">${formatPercent(act.prob)}</td>
          <td class="mono text-rose">${formatPaiseINR(act.cost)}</td>
          <td class="mono font-bold ${net > 0 ? 'text-emerald' : 'text-dim'}">${formatPaiseINR(net)}</td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  }

  function renderTimeline(events) {
    const container = document.getElementById("timelineContainer");
    if (!container) return;

    if (!events || events.length === 0) {
      container.innerHTML = `<div class="text-dim text-xs mono">No timeline events recorded.</div>`;
      return;
    }

    let html = "";
    events.forEach((evt) => {
      html += `
        <div style="background:rgba(14,25,38,0.7);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:0.55rem 0.75rem;">
          <div class="flex-between">
            <span class="mono font-bold text-xs text-bright">${escapeHTML(evt.title)}</span>
            <span class="mono text-dim text-xs">${formatTimestamp(evt.timestamp)}</span>
          </div>
          <div class="text-xs text-muted" style="margin-top:0.2rem;">${escapeHTML(formatDescriptionRupees(evt.description))}</div>
        </div>
      `;
    });
    container.innerHTML = html;
  }

  // =========================================================================
  // DATA SYNC & BOOTSTRAP
  // =========================================================================

  async function loadAllData() {
    try {
      const [overviewData, casesData] = await Promise.all([
        fetchAPI("/api/v1/dashboard/overview"),
        fetchAPI("/api/v1/recovery/cases?limit=50"),
      ]);

      state.overview = overviewData;
      state.cases = casesData.items || [];

      // Update Toolbar Badges & Top Executive KPI Strip
      const queueBadge = document.getElementById("queueBadgeCount");
      if (queueBadge) queueBadge.textContent = overviewData.total_cases || 0;

      const kpiRate = document.getElementById("kpiRecoveryRate");
      if (kpiRate) kpiRate.textContent = formatPercent(overviewData.recovery_rate);

      const kpiRisk = document.getElementById("kpiRevenueAtRisk");
      if (kpiRisk) kpiRisk.textContent = formatPaiseINR(overviewData.total_amount_at_risk_paise);

      const kpiNet = document.getElementById("kpiNetRecovered");
      if (kpiNet) kpiNet.textContent = formatPaiseINR(overviewData.recoverai_net_recovered_paise);

      const kpiProv = document.getElementById("kpiProviderGross");
      if (kpiProv) kpiProv.textContent = formatPaiseINR(overviewData.provider_gross_recovered_paise);

      const kpiActive = document.getElementById("kpiActiveCases");
      if (kpiActive) kpiActive.textContent = overviewData.pending_cases;

      // Refresh active view
      if (state.activeView === "view-pipeline") {
        renderPipelineView();
      } else if (state.activeView === "view-queue") {
        loadCasesQueue();
      } else if (state.activeView === "view-analytics") {
        renderFunnel();
        loadTrends();
      }

    } catch (err) {
      console.warn("Failed loading live telemetry:", err);
    }
  }

  function filterByStage(stage) {
    switchView("view-queue");
    const filterStateEl = document.getElementById("filterState");
    if (!filterStateEl) return;
    if (stage === "at_risk") {
      filterStateEl.value = "";
    } else if (stage === "decided") {
      filterStateEl.value = "DECIDED";
    } else if (stage === "actioned") {
      filterStateEl.value = "ACTION_EXECUTED";
    } else if (stage === "settled" || stage === "recovered") {
      filterStateEl.value = "RECOVERED";
    }
    document.getElementById("applyFiltersBtn")?.click();
  }

  window.inspectCase = inspectCase;
  window.switchView = switchView;
  window.filterByStage = filterByStage;

  function init() {
    // 1. Navigation Tab View Switchers
    document.querySelectorAll(".nav-tab-btn[data-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const v = btn.getAttribute("data-view");
        switchView(v);
      });
    });

    // 1b. Pipeline Stage Cards (Quick-Filter to Queue)
    document.querySelectorAll(".pipeline-stage-card[data-stage]").forEach((card) => {
      card.addEventListener("click", () => {
        const stage = card.getAttribute("data-stage");
        filterByStage(stage);
      });
    });

    // 2. Drawer Close
    document.getElementById("modalCloseBtn")?.addEventListener("click", () => {
      document.getElementById("caseDetailModal")?.classList.remove("open");
    });

    // 3. Header Search Input Filter
    document.getElementById("aiQueryInput")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const query = e.target.value.trim().toLowerCase();
        if (query.includes("analytic") || query.includes("funnel") || query.includes("yield")) {
          switchView("view-analytics");
        } else if (query.includes("pipeline")) {
          switchView("view-pipeline");
        } else if (query) {
          state.queue.search = query;
          const sInput = document.getElementById("searchInput");
          if (sInput) sInput.value = query;
          switchView("view-queue");
          loadCasesQueue();
        }
      }
    });

    // 4. Manual Sync Trigger Button
    document.getElementById("btnTriggerSimulation")?.addEventListener("click", () => {
      loadAllData();
      if (state.activeView === "view-queue") loadCasesQueue();
      if (state.activeView === "view-analytics") { renderFunnel(); loadTrends(); }
    });

    // 5. Trend Interval Change Handler
    document.getElementById("trendIntervalSelect")?.addEventListener("change", () => {
      loadTrends();
    });

    // 6. Queue Filters & Pagination
    document.getElementById("applyFiltersBtn")?.addEventListener("click", () => {
      state.queue.search = document.getElementById("searchInput")?.value.trim() || "";
      state.queue.state = document.getElementById("filterState")?.value || "";
      state.queue.action = document.getElementById("filterAction")?.value || "";
      state.queue.failureType = document.getElementById("filterFailureType")?.value || "";
      state.queue.isSubscription = document.getElementById("filterSubscription")?.value || "";
      state.queue.page = 0;
      loadCasesQueue();
    });

    document.getElementById("resetFiltersBtn")?.addEventListener("click", () => {
      const sInput = document.getElementById("searchInput");
      if (sInput) sInput.value = "";
      document.getElementById("filterState").value = "";
      document.getElementById("filterAction").value = "";
      document.getElementById("filterFailureType").value = "";
      document.getElementById("filterSubscription").value = "";
      state.queue.search = "";
      state.queue.state = "";
      state.queue.action = "";
      state.queue.failureType = "";
      state.queue.isSubscription = "";
      state.queue.page = 0;
      loadCasesQueue();
    });

    document.getElementById("prevPageBtn")?.addEventListener("click", () => {
      if (state.queue.page > 0) {
        state.queue.page--;
        loadCasesQueue();
      }
    });
    document.getElementById("nextPageBtn")?.addEventListener("click", () => {
      state.queue.page++;
      loadCasesQueue();
    });

    // Initial Load & Auto-Refresh
    loadAllData();
    loadCasesQueue();
    renderFunnel();
    loadTrends();
    setInterval(loadAllData, state.autoRefreshInterval);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

