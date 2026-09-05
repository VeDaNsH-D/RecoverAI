/**
 * RecoverAI — Merchant Recovery Command Center Controller (Milestone 9)
 * Zero external dependencies. Uses standard modern ES6, Fetch API, and SVG graphics.
 * Strict financial integer paise handling and privacy masking.
 */

(function () {
  "use strict";

  // Application State
  const state = {
    activeTab: "tab-overview",
    queue: {
      page: 0,
      limit: 20,
      totalCount: 0,
      search: "",
      state: "",
      action: "",
      failureType: "",
      isSubscription: "",
    },
    autoRefreshInterval: 10000,
    timerId: null,
    pendingSyncSubId: null,
  };

  // =========================================================================
  // Formatting & Utility Helpers
  // =========================================================================

  /** Formats 64-bit integer paise to Indian Rupee representation (e.g. 125000 -> ₹1,250.00) */
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

  /** Formats percentages (e.g. 0.452 -> 45.2%) */
  function formatPercent(rate) {
    if (rate === null || rate === undefined || isNaN(rate)) return "0.0%";
    return (Number(rate) * 100).toFixed(1) + "%";
  }

  /** Privacy protection: masks synthetic customer IDs (e.g. cust_12345678 -> cust_••••5678) */
  function maskCustomerId(id) {
    if (!id) return "cust_••••";
    if (id.length <= 8) return id;
    const prefix = id.substring(0, 5);
    const suffix = id.substring(id.length - 4);
    return `${prefix}••••${suffix}`;
  }

  /** Formats ISO 8601 timestamps */
  function formatTimestamp(isoStr) {
    if (!isoStr) return "-";
    try {
      const dt = new Date(isoStr);
      return dt.toLocaleString("en-IN", {
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

  /** Escapes HTML strings to prevent XSS injection */
  function escapeHTML(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /** Global alert / toast banner */
  function showAlert(message, type = "danger") {
    const container = document.getElementById("alertBannerContainer");
    if (!container) return;
    const alertDiv = document.createElement("div");
    alertDiv.className = `alert alert-${type}`;
    alertDiv.innerHTML = `
      <span>${escapeHTML(message)}</span>
      <button style="background:none;border:none;color:inherit;cursor:pointer;font-weight:bold;" onclick="this.parentElement.remove()">&times;</button>
    `;
    container.appendChild(alertDiv);
    setTimeout(() => {
      if (alertDiv.parentElement) alertDiv.remove();
    }, 6000);
  }

  // =========================================================================
  // API Fetch Clients
  // =========================================================================

  async function fetchAPI(url, options = {}) {
    try {
      const res = await fetch(url, {
        headers: { "Content-Type": "application/json", ...options.headers },
        ...options,
      });
      if (!res.ok) {
        let errDetail = `HTTP ${res.status}: ${res.statusText}`;
        try {
          const errJson = await res.json();
          errDetail = errJson.detail || errJson.error?.message || errDetail;
          if (typeof errDetail === "object") errDetail = JSON.stringify(errDetail);
        } catch (_) {}
        throw new Error(errDetail);
      }
      return await res.json();
    } catch (err) {
      console.error(`Fetch error on ${url}:`, err);
      throw err;
    }
  }

  // =========================================================================
  // View Renderers
  // =========================================================================

  /** 1. Overview Tab: KPIs, Conversion Funnel & Attribution */
  async function loadOverviewData() {
    try {
      const data = await fetchAPI("/api/v1/dashboard/overview");
      
      // Topline KPIs
      document.getElementById("kpiRevenueAtRisk").textContent = formatPaiseINR(data.total_amount_at_risk_paise);
      document.getElementById("kpiTotalCases").textContent = `${data.total_cases} incident${data.total_cases === 1 ? "" : "s"} at risk`;

      document.getElementById("kpiRecoverAINet").textContent = formatPaiseINR(data.recoverai_net_recovered_paise);
      document.getElementById("kpiRecoverAINetSub").textContent = `${formatPaiseINR(data.recoverai_gross_recovered_paise)} gross − ${formatPaiseINR(data.total_action_cost_paise)} cost`;

      document.getElementById("kpiProviderGross").textContent = formatPaiseINR(data.provider_gross_recovered_paise);
      document.getElementById("kpiGrossRecovered").textContent = formatPaiseINR(data.gross_recovered_paise);
      document.getElementById("kpiRecoveredCases").textContent = `${data.recovered_cases} of ${data.total_cases} recovered`;

      document.getElementById("kpiActionCost").textContent = formatPaiseINR(data.total_action_cost_paise);
      document.getElementById("kpiActionsExecuted").textContent = `${data.actions_executed} actions executed (${data.execution_failures} failed)`;

      document.getElementById("kpiRecoveryRate").textContent = formatPercent(data.recovery_rate);
      document.getElementById("kpiExecRate").textContent = `Exec success: ${formatPercent(data.execution_success_rate)}`;

      document.getElementById("kpiPendingCases").textContent = data.pending_cases;

      // Render 5-Stage Conversion Funnel
      renderFunnel(data);

      // Render Authoritative Attribution Donut
      renderAttribution(data);

      // Fetch Action and Failure breakdowns
      loadOverviewBreakdowns();

      updateTimestamp();
    } catch (err) {
      showAlert(`Failed to load overview data: ${err.message}`, "danger");
    }
  }

  /** Render 5-Stage Conversion Funnel */
  function renderFunnel(data) {
    const container = document.getElementById("funnelContainer");
    if (!container) return;

    const baseCount = Math.max(1, data.total_cases);
    const stages = [
      { name: "1. Cases at Risk", count: data.total_cases, color: "#6366f1" },
      { name: "2. Decisions Made", count: data.decisions_made, color: "#8b5cf6" },
      { name: "3. Actions Dispatched", count: data.actions_attempted, color: "#0ea5e9" },
      { name: "4. Executions Succeeded", count: data.actions_executed, color: "#06b6d4" },
      { name: "5. Recovered Outcomes", count: data.recovered_cases, color: "#10b981" },
    ];

    let html = "";
    stages.forEach((stage) => {
      const pct = Math.round((stage.count / baseCount) * 100);
      const widthPct = Math.max(8, pct);
      html += `
        <div class="funnel-stage">
          <div class="funnel-stage-header">
            <span>${escapeHTML(stage.name)}</span>
            <span class="mono">${stage.count} (${pct}%)</span>
          </div>
          <div class="funnel-bar-wrapper">
            <div class="funnel-bar" style="width: ${widthPct}%; background-color: ${stage.color};">
              ${stage.count}
            </div>
          </div>
        </div>
      `;
    });
    container.innerHTML = html;
  }

  /** Render Pure SVG Donut Attribution Chart */
  function renderAttribution(data) {
    const container = document.getElementById("attributionContainer");
    if (!container) return;

    const recAI = data.attribution?.recoverai_intervention_recovered_cases || 0;
    const provider = data.attribution?.provider_auto_retry_recovered_cases || 0;
    const unresolved = Math.max(0, data.total_cases - (recAI + provider));
    const total = recAI + provider + unresolved;

    if (total === 0) {
      container.innerHTML = `<div class="text-subdued text-xs text-center" style="padding: 2rem 0;">No settlement data available yet</div>`;
      return;
    }

    const recAIPct = (recAI / total) * 100;
    const providerPct = (provider / total) * 100;
    const unresolvedPct = (unresolved / total) * 100;

    // SVG Donut calculation (circumference = 2 * PI * r = 2 * PI * 40 ≈ 251.32)
    const C = 251.32;
    const dash1 = (recAI / total) * C;
    const dash2 = (provider / total) * C;
    const dash3 = (unresolved / total) * C;

    const offset1 = 0;
    const offset2 = -dash1;
    const offset3 = -(dash1 + dash2);

    container.innerHTML = `
      <div class="attribution-svg-wrapper">
        <svg viewBox="0 0 100 100" width="100%" height="100%">
          <circle cx="50" cy="50" r="40" fill="transparent" stroke="#1e293b" stroke-width="14"></circle>
          <!-- RecoverAI Interventions (Emerald) -->
          <circle cx="50" cy="50" r="40" fill="transparent" stroke="#10b981" stroke-width="14"
            stroke-dasharray="${dash1} ${C - dash1}" stroke-dashoffset="${offset1}" transform="rotate(-90 50 50)"></circle>
          <!-- Provider Auto-Retries (Sky Blue) -->
          <circle cx="50" cy="50" r="40" fill="transparent" stroke="#0ea5e9" stroke-width="14"
            stroke-dasharray="${dash2} ${C - dash2}" stroke-dashoffset="${offset2}" transform="rotate(-90 50 50)"></circle>
          <!-- Unresolved / In-Flight (Slate) -->
          <circle cx="50" cy="50" r="40" fill="transparent" stroke="#475569" stroke-width="14"
            stroke-dasharray="${dash3} ${C - dash3}" stroke-dashoffset="${offset3}" transform="rotate(-90 50 50)"></circle>
          <!-- Center Text -->
          <text x="50" y="47" text-anchor="middle" font-size="12" font-weight="bold" fill="#ffffff">${data.recovered_cases}</text>
          <text x="50" y="58" text-anchor="middle" font-size="6" fill="#94a3b8">RECOVERED</text>
        </svg>
      </div>

      <div class="attribution-legend">
        <div class="legend-item">
          <div><span class="legend-color-box" style="background:#10b981;"></span>RecoverAI Intervention</div>
          <div class="mono font-bold text-emerald">${recAI} (${recAIPct.toFixed(1)}%) • ${formatPaiseINR(data.recoverai_gross_recovered_paise)}</div>
        </div>
        <div class="legend-item">
          <div><span class="legend-color-box" style="background:#0ea5e9;"></span>Provider Auto-Retry</div>
          <div class="mono font-bold text-sky">${provider} (${providerPct.toFixed(1)}%) • ${formatPaiseINR(data.provider_gross_recovered_paise)}</div>
        </div>
        <div class="legend-item">
          <div><span class="legend-color-box" style="background:#475569;"></span>Unresolved / In-Flight</div>
          <div class="mono text-subdued">${unresolved} (${unresolvedPct.toFixed(1)}%)</div>
        </div>
      </div>
    `;
  }

  /** Load and render Action & Failure breakdowns */
  async function loadOverviewBreakdowns() {
    try {
      const [actionsData, failureData] = await Promise.all([
        fetchAPI("/api/v1/analytics/actions"),
        fetchAPI("/api/v1/analytics/failure-types"),
      ]);

      // Action Breakdown
      const actionContainer = document.getElementById("actionBreakdownList");
      if (actionContainer) {
        let actHtml = "";
        actionsData.forEach((item) => {
          const rr = (item.recovery_rate * 100).toFixed(1);
          actHtml += `
            <div class="breakdown-row">
              <div class="breakdown-header">
                <div>
                  <span class="pill pill-action">${escapeHTML(item.action)}</span>
                  <span class="text-subdued text-xs">(${item.decisions} decisions • ${item.successful_executions} executed)</span>
                </div>
                <div class="mono font-bold text-emerald">${formatPaiseINR(item.gross_recovered_paise)} <span class="text-xs text-subdued">(${rr}% RR)</span></div>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${Math.min(100, Math.max(4, item.recovery_rate * 100))}%; background-color: #6366f1;"></div>
              </div>
            </div>
          `;
        });
        actionContainer.innerHTML = actHtml || `<div class="text-subdued text-xs">No action records</div>`;
      }

      // Failure Type Breakdown
      const failureContainer = document.getElementById("failureBreakdownList");
      if (failureContainer) {
        let ftHtml = "";
        failureData.forEach((item) => {
          const rr = (item.recovery_rate * 100).toFixed(1);
          ftHtml += `
            <div class="breakdown-row">
              <div class="breakdown-header">
                <div>
                  <span class="font-bold text-xs">${escapeHTML(item.failure_type)}</span>
                  <span class="text-subdued text-xs">(${item.cases} cases)</span>
                </div>
                <div class="mono font-bold text-emerald">${formatPaiseINR(item.gross_recovered_paise)} <span class="text-xs text-subdued">(${rr}% RR)</span></div>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${Math.min(100, Math.max(4, item.recovery_rate * 100))}%; background-color: #0ea5e9;"></div>
              </div>
            </div>
          `;
        });
        failureContainer.innerHTML = ftHtml || `<div class="text-subdued text-xs">No failure diagnostic records</div>`;
      }
    } catch (err) {
      console.warn("Error loading breakdowns:", err);
    }
  }

  /** 2. Recovery Queue Tab: Paginated & Filterable Cases Table */
  async function loadCasesQueue() {
    const tbody = document.getElementById("casesTableBody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="10" class="text-center text-subdued" style="padding: 2rem;">Loading recovery queue...</td></tr>`;

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
      document.getElementById("queueTabCount").textContent = data.total_count;

      // Update Pagination Controls
      const totalPages = Math.ceil(data.total_count / state.queue.limit) || 1;
      const currentPage = state.queue.page + 1;
      document.getElementById("paginationInfo").textContent = `Showing ${data.items.length} of ${data.total_count} cases`;
      document.getElementById("pageIndicator").textContent = `Page ${currentPage} of ${totalPages}`;
      document.getElementById("prevPageBtn").disabled = state.queue.page <= 0;
      document.getElementById("nextPageBtn").disabled = currentPage >= totalPages;

      if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="text-center text-subdued" style="padding: 2rem;">No recovery cases match the current filter criteria.</td></tr>`;
        return;
      }

      let rows = "";
      data.items.forEach((c) => {
        const stateClass = getPillClassForState(c.current_state);
        const maskedCust = maskCustomerId(c.customer_id);
        const isSubPill = c.is_subscription ? `<span class="badge badge-subdued text-xs">Recurring</span>` : `<span class="text-subdued text-xs">One-Off</span>`;
        const timeFormatted = formatTimestamp(c.created_at);

        rows += `
          <tr>
            <td class="mono font-bold">${escapeHTML(c.case_id)}</td>
            <td class="mono text-subdued" title="${escapeHTML(c.customer_id)}">${escapeHTML(maskedCust)}</td>
            <td class="mono font-bold text-slate">${formatPaiseINR(c.amount_paise)}</td>
            <td><span class="pill ${stateClass}">${escapeHTML(c.current_state)}</span></td>
            <td><span class="pill pill-action">${escapeHTML(c.recommended_action)}</span></td>
            <td class="text-xs text-subdued">${escapeHTML(c.failure_type || "temporary_failure")}</td>
            <td class="mono text-center">${c.retry_count}</td>
            <td>${isSubPill}</td>
            <td class="text-xs text-subdued">${timeFormatted}</td>
            <td>
              <button class="btn btn-secondary btn-sm view-case-btn" data-case-id="${escapeHTML(c.case_id)}">
                View Detail
              </button>
            </td>
          </tr>
        `;
      });
      tbody.innerHTML = rows;

      // Attach detail click listeners
      document.querySelectorAll(".view-case-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const cid = btn.getAttribute("data-case-id");
          openCaseDetail(cid);
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="10" class="text-center text-rose" style="padding: 2rem;">Error loading cases: ${escapeHTML(err.message)}</td></tr>`;
    }
  }

  function getPillClassForState(st) {
    if (!st) return "pill-pending";
    const s = st.toUpperCase();
    if (s === "RECOVERED") return "pill-recovered";
    if (s === "NOT_RECOVERED") return "pill-not-recovered";
    if (s === "DECIDED") return "pill-decided";
    if (s === "ACTION_EXECUTED") return "pill-executed";
    if (s === "EXECUTION_FAILED") return "pill-failed";
    return "pill-pending";
  }

  /** 3. Subscriptions Tab: Listing & Bounded Single-Subscription Sync */
  async function loadSubscriptions() {
    const tbody = document.getElementById("subscriptionsTableBody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="9" class="text-center text-subdued" style="padding: 2rem;">Loading subscriptions...</td></tr>`;

    try {
      const subs = await fetchAPI("/api/v1/recovery/subscriptions");
      document.getElementById("subTabCount").textContent = subs.length;

      if (!subs || subs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center text-subdued" style="padding: 2rem;">No subscriptions found in the registry.</td></tr>`;
        return;
      }

      let rows = "";
      subs.forEach((s) => {
        const statusClass = s.status === "active" ? "pill-recovered" : (s.status === "halted" ? "pill-failed" : "pill-pending");
        const maskedCust = maskCustomerId(s.customer_id);
        const recoverableText = s.is_recoverable ? `<span class="text-emerald">Yes</span>` : `<span class="text-rose">No</span>`;

        rows += `
          <tr>
            <td class="mono font-bold">${escapeHTML(s.subscription_id)}</td>
            <td class="mono text-subdued">${escapeHTML(maskedCust)}</td>
            <td><span class="pill ${statusClass}">${escapeHTML(s.status)}</span></td>
            <td class="mono text-center">${s.current_cycle}${s.total_cycles ? "/" + s.total_cycles : ""}</td>
            <td class="mono font-bold">${formatPaiseINR(s.amount_due_paise)}</td>
            <td class="mono text-center">${s.charge_attempt_count}</td>
            <td class="text-xs font-bold">${recoverableText}</td>
            <td class="text-xs text-subdued">${formatTimestamp(s.updated_at)}</td>
            <td>
              <button class="btn btn-secondary btn-sm sync-sub-btn" data-sub-id="${escapeHTML(s.subscription_id)}">
                Sync & Reconcile
              </button>
            </td>
          </tr>
        `;
      });
      tbody.innerHTML = rows;

      // Attach sync handlers
      document.querySelectorAll(".sync-sub-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const subId = btn.getAttribute("data-sub-id");
          openSyncModal(subId);
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center text-rose" style="padding: 2rem;">Error loading subscriptions: ${escapeHTML(err.message)}</td></tr>`;
    }
  }

  /** 4. Analytics & Trends Tab */
  async function loadTrendsData() {
    const container = document.getElementById("trendChartContainer");
    if (!container) return;

    const interval = document.getElementById("trendIntervalSelect")?.value || "daily";

    try {
      const [trends, retryData, segmentData] = await Promise.all([
        fetchAPI(`/api/v1/analytics/trends?interval=${interval}`),
        fetchAPI("/api/v1/analytics/retry-count"),
        fetchAPI("/api/v1/analytics/subscriptions"),
      ]);

      // Trends Bar Graph
      if (!trends || trends.length === 0) {
        container.innerHTML = `<div class="text-subdued text-xs text-center" style="padding: 3rem 0;">No trend data available for current window</div>`;
      } else {
        const maxGross = Math.max(...trends.map((t) => t.gross_recovered_paise), 1);
        let chartHtml = `<div style="display: flex; gap: 0.75rem; align-items: flex-end; height: 160px; padding: 1rem 0; border-bottom: 1px solid var(--border-color); overflow-x: auto;">`;
        trends.forEach((t) => {
          const heightPct = Math.max(6, Math.round((t.gross_recovered_paise / maxGross) * 100));
          chartHtml += `
            <div style="display: flex; flex-direction: column; align-items: center; gap: 0.35rem; min-width: 50px;">
              <span class="mono text-xs text-emerald" style="font-size: 0.68rem;">${formatPaiseINR(t.gross_recovered_paise)}</span>
              <div style="width: 28px; height: ${heightPct}px; background: linear-gradient(180deg, #6366f1, #3b82f6); border-radius: 4px;" title="${t.time_bucket}: ${t.recovered_cases} recovered (${formatPaiseINR(t.gross_recovered_paise)})"></div>
              <span class="mono text-xs text-subdued" style="font-size: 0.65rem;">${escapeHTML(t.time_bucket.slice(5))}</span>
            </div>
          `;
        });
        chartHtml += `</div>`;
        container.innerHTML = chartHtml;
      }

      // Retry Breakdown
      const retryContainer = document.getElementById("retryBreakdownList");
      if (retryContainer) {
        let rcHtml = "";
        retryData.forEach((item) => {
          const rr = (item.recovery_rate * 100).toFixed(1);
          rcHtml += `
            <div class="breakdown-row">
              <div class="breakdown-header">
                <span class="font-bold text-xs">${item.retry_count} Prior Retries <span class="text-subdued">(${item.cases} cases)</span></span>
                <span class="mono font-bold text-emerald">${formatPaiseINR(item.gross_recovered_paise)} <span class="text-xs text-subdued">(${rr}% RR)</span></span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${Math.min(100, Math.max(4, item.recovery_rate * 100))}%; background-color: #8b5cf6;"></div>
              </div>
            </div>
          `;
        });
        retryContainer.innerHTML = rcHtml || `<div class="text-subdued text-xs">No retry records</div>`;
      }

      // Segment Breakdown
      const segmentContainer = document.getElementById("segmentBreakdownList");
      if (segmentContainer) {
        let segHtml = "";
        segmentData.forEach((item) => {
          const rr = (item.recovery_rate * 100).toFixed(1);
          const segTitle = item.segment === "subscription" ? "Recurring Subscription" : "One-Off Transaction";
          segHtml += `
            <div class="breakdown-row">
              <div class="breakdown-header">
                <span class="font-bold text-xs">${segTitle} <span class="text-subdued">(${item.cases} cases)</span></span>
                <span class="mono font-bold text-emerald">${formatPaiseINR(item.gross_recovered_paise)} <span class="text-xs text-subdued">(${rr}% RR)</span></span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${Math.min(100, Math.max(4, item.recovery_rate * 100))}%; background-color: #10b981;"></div>
              </div>
            </div>
          `;
        });
        segmentContainer.innerHTML = segHtml || `<div class="text-subdued text-xs">No segment records</div>`;
      }
    } catch (err) {
      showAlert(`Failed to load trends: ${err.message}`, "danger");
    }
  }

  // =========================================================================
  // Case Detail Drawer / Modal
  // =========================================================================

  async function openCaseDetail(caseId) {
    const modal = document.getElementById("caseDetailModal");
    if (!modal) return;

    modal.classList.add("open");
    document.getElementById("modalCaseTitle").textContent = `Case: ${caseId}`;
    document.getElementById("modalCaseSubtitle").textContent = "Loading case detail & audit timeline...";

    try {
      const [detail, timelineData] = await Promise.all([
        fetchAPI(`/api/v1/recovery/cases/${encodeURIComponent(caseId)}`),
        fetchAPI(`/api/v1/recovery/cases/${encodeURIComponent(caseId)}/timeline`),
      ]);

      const c = detail.case;
      document.getElementById("modalCaseSubtitle").textContent = `Customer: ${maskCustomerId(c.customer_id)} • Created: ${formatTimestamp(c.created_at)}`;

      // Section 1: Incident Context
      document.getElementById("dtCaseId").textContent = c.case_id;
      document.getElementById("dtCustomerId").textContent = maskCustomerId(c.customer_id);
      document.getElementById("dtAmount").textContent = formatPaiseINR(c.amount_paise);
      document.getElementById("dtState").innerHTML = `<span class="pill ${getPillClassForState(c.current_state)}">${escapeHTML(c.current_state)}</span>`;
      document.getElementById("dtPaymentMethod").textContent = c.payment_method || "UPI";
      document.getElementById("dtFailureType").textContent = c.failure_type || "temporary_failure";
      document.getElementById("dtRetryCount").textContent = c.retry_count;
      document.getElementById("dtSubscriptionId").textContent = c.subscription_id || "-";
      document.getElementById("dtBillingCycleId").textContent = c.billing_cycle_id || "-";

      // Section 2: Decision Model Forecast
      if (detail.decision_forecast) {
        const d = detail.decision_forecast;
        document.getElementById("dtDecAction").textContent = d.recommended_action.toUpperCase();
        document.getElementById("dtDecProb").textContent = formatPercent(d.recovery_probability);
        document.getElementById("dtDecGross").textContent = formatPaiseINR(d.expected_gross_recovery_paise);
        document.getElementById("dtDecCost").textContent = formatPaiseINR(d.action_cost_paise);
        document.getElementById("dtDecNet").textContent = formatPaiseINR(d.expected_net_recovery_paise);
        document.getElementById("dtDecMargin").textContent = `+${formatPaiseINR(d.decision_margin_paise)} over 2nd best`;
        document.getElementById("dtDecModel").textContent = d.model_family;
        document.getElementById("dtDecExplanation").textContent = d.explanation;
      } else {
        document.getElementById("dtDecAction").textContent = "NO_DECISION";
        document.getElementById("dtDecProb").textContent = "-";
        document.getElementById("dtDecGross").textContent = "-";
        document.getElementById("dtDecCost").textContent = "-";
        document.getElementById("dtDecNet").textContent = "-";
        document.getElementById("dtDecMargin").textContent = "-";
        document.getElementById("dtDecModel").textContent = "-";
        document.getElementById("dtDecExplanation").textContent = "No decision record found for this case.";
      }

      // Section 3: Authoritative Settlement Outcome
      if (detail.action_execution) {
        const a = detail.action_execution;
        document.getElementById("dtActAction").innerHTML = `<span class="pill pill-action">${escapeHTML(a.action)}</span>`;
        document.getElementById("dtActStatus").textContent = a.status;
        document.getElementById("dtActProviderRef").textContent = a.provider_reference || "none";
      } else {
        document.getElementById("dtActAction").textContent = "None";
        document.getElementById("dtActStatus").textContent = "-";
        document.getElementById("dtActProviderRef").textContent = "-";
      }

      if (detail.outcome_settlement) {
        const o = detail.outcome_settlement;
        const resSource = o.resolution_source || "recoverai_intervention";
        const resSourceClass = resSource === "provider_auto_retry" ? "badge-subdued text-sky" : "badge-subdued text-emerald";
        document.getElementById("dtOutStatus").innerHTML = `<span class="pill ${o.outcome_status === 'recovered' ? 'pill-recovered' : 'pill-not-recovered'}">${escapeHTML(o.outcome_status.toUpperCase())}</span>`;
        document.getElementById("dtOutAmount").textContent = formatPaiseINR(o.recovered_amount_paise);
        document.getElementById("dtOutResolutionSource").className = `badge ${resSourceClass}`;
        document.getElementById("dtOutResolutionSource").textContent = resSource;
        document.getElementById("dtOutTimestamp").textContent = formatTimestamp(o.event_timestamp || o.created_at);
      } else {
        document.getElementById("dtOutStatus").textContent = "Unsettled / In-Flight";
        document.getElementById("dtOutAmount").textContent = "-";
        document.getElementById("dtOutResolutionSource").className = "badge badge-subdued";
        document.getElementById("dtOutResolutionSource").textContent = "Pending";
        document.getElementById("dtOutTimestamp").textContent = "-";
      }

      // Section 4: Chronological Audit Timeline
      renderTimeline(timelineData.events);
    } catch (err) {
      showAlert(`Failed to load case detail: ${err.message}`, "danger");
    }
  }

  function renderTimeline(events) {
    const container = document.getElementById("timelineContainer");
    if (!container) return;

    if (!events || events.length === 0) {
      container.innerHTML = `<div class="text-subdued text-xs">No audit timeline records available</div>`;
      return;
    }

    let html = "";
    events.forEach((evt) => {
      const isComplete = evt.status === "COMPLETED";
      const isFailed = evt.status === "FAILED" || evt.status === "NOT_RECOVERED";
      const dotClass = isComplete ? "timeline-dot-completed" : (isFailed ? "timeline-dot-failed" : "");

      let metaChips = "";
      if (evt.metadata) {
        for (const [k, v] of Object.entries(evt.metadata)) {
          if (v !== null && v !== undefined && v !== "") {
            const formattedVal = k.includes("paise") ? formatPaiseINR(v) : String(v);
            metaChips += `<span class="meta-chip">${escapeHTML(k)}: ${escapeHTML(formattedVal)}</span>`;
          }
        }
      }

      html += `
        <div class="timeline-item">
          <div class="timeline-dot ${dotClass}"></div>
          <div class="timeline-header">
            <span class="timeline-title">${escapeHTML(evt.title)}</span>
            <span class="timeline-time">${formatTimestamp(evt.timestamp)}</span>
          </div>
          <div class="timeline-desc">${escapeHTML(evt.description)}</div>
          ${metaChips ? `<div class="timeline-meta-box">${metaChips}</div>` : ""}
        </div>
      `;
    });
    container.innerHTML = html;
  }

  // =========================================================================
  // Subscription Single-Sync Modal & Action
  // =========================================================================

  function openSyncModal(subscriptionId) {
    state.pendingSyncSubId = subscriptionId;
    document.getElementById("syncTargetSubscriptionId").textContent = subscriptionId;
    const modal = document.getElementById("syncModal");
    if (modal) modal.classList.add("open");
  }

  function closeSyncModal() {
    state.pendingSyncSubId = null;
    const modal = document.getElementById("syncModal");
    if (modal) modal.classList.remove("open");
  }

  async function executeSingleSubscriptionSync() {
    const subId = state.pendingSyncSubId;
    if (!subId) return;

    const confirmBtn = document.getElementById("confirmSyncBtn");
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Reconciling...";

    try {
      const resp = await fetchAPI("/api/v1/recovery/subscriptions/sync", {
        method: "POST",
        body: JSON.stringify({ subscription_id: subId }),
      });
      closeSyncModal();
      showAlert(`Successfully reconciled ${subId}. Authoritative status: ${resp.status}`, "success");
      loadSubscriptions();
      loadOverviewData();
    } catch (err) {
      showAlert(`Subscription sync failed: ${err.message}`, "danger");
    } finally {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Reconcile Subscription";
    }
  }

  // =========================================================================
  // Lifecycle & Event Binding
  // =========================================================================

  function updateTimestamp() {
    const tsEl = document.getElementById("lastUpdatedText");
    if (tsEl) {
      tsEl.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
    }
  }

  function refreshCurrentTab() {
    const refreshIcon = document.getElementById("refreshIcon");
    if (refreshIcon) refreshIcon.style.transform = "rotate(360deg)";
    setTimeout(() => {
      if (refreshIcon) refreshIcon.style.transform = "none";
    }, 400);

    if (state.activeTab === "tab-overview") {
      loadOverviewData();
    } else if (state.activeTab === "tab-queue") {
      loadCasesQueue();
    } else if (state.activeTab === "tab-subscriptions") {
      loadSubscriptions();
    } else if (state.activeTab === "tab-analytics") {
      loadTrendsData();
    }
  }

  function setupAutoRefresh() {
    if (state.timerId) clearInterval(state.timerId);
    if (state.autoRefreshInterval > 0) {
      state.timerId = setInterval(() => {
        refreshCurrentTab();
      }, state.autoRefreshInterval);
    }
  }

  function init() {
    // 1. Tab Switching
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetTab = btn.getAttribute("data-tab");
        state.activeTab = targetTab;

        document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

        btn.classList.add("active");
        const contentEl = document.getElementById(targetTab);
        if (contentEl) contentEl.classList.add("active");

        refreshCurrentTab();
      });
    });

    // 2. Queue Filters & Pagination
    document.getElementById("applyFiltersBtn")?.addEventListener("click", () => {
      state.queue.search = document.getElementById("filterSearch")?.value.trim() || "";
      state.queue.state = document.getElementById("filterState")?.value || "";
      state.queue.action = document.getElementById("filterAction")?.value || "";
      state.queue.failureType = document.getElementById("filterFailureType")?.value || "";
      state.queue.isSubscription = document.getElementById("filterSubscription")?.value || "";
      state.queue.page = 0;
      loadCasesQueue();
    });

    document.getElementById("resetFiltersBtn")?.addEventListener("click", () => {
      document.getElementById("filterSearch").value = "";
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

    // 3. Modals Close
    document.getElementById("modalCloseBtn")?.addEventListener("click", () => {
      document.getElementById("caseDetailModal")?.classList.remove("open");
    });
    document.getElementById("caseDetailModal")?.addEventListener("click", (e) => {
      if (e.target.id === "caseDetailModal") {
        document.getElementById("caseDetailModal").classList.remove("open");
      }
    });

    document.getElementById("syncModalCloseBtn")?.addEventListener("click", closeSyncModal);
    document.getElementById("cancelSyncBtn")?.addEventListener("click", closeSyncModal);
    document.getElementById("confirmSyncBtn")?.addEventListener("click", executeSingleSubscriptionSync);
    document.getElementById("syncModal")?.addEventListener("click", (e) => {
      if (e.target.id === "syncModal") closeSyncModal();
    });

    // 4. Auto-Refresh Select & Manual Refresh
    document.getElementById("refreshBtn")?.addEventListener("click", refreshCurrentTab);
    document.getElementById("autoRefreshSelect")?.addEventListener("change", (e) => {
      state.autoRefreshInterval = parseInt(e.target.value, 10);
      setupAutoRefresh();
    });

    document.getElementById("trendIntervalSelect")?.addEventListener("change", loadTrendsData);

    // Initial Load
    loadOverviewData();
    setupAutoRefresh();
  }

  // Boot on DOMContentLoaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
