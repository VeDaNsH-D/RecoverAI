/**
 * RecoverAI — Merchant Recovery Command Center (Milestone 10 Reference Edition)
 * Dynamic Cosmic Constellation Graph, Causal Branching Dendrogram, and AI Copilot Engine
 * 
 * Strict Invariants:
 * 1. Observability and control surface ONLY.
 * 2. 64-bit integer paise financial handling via formatPaiseINR().
 * 3. Privacy-protected masked customer IDs (cust_••••XXXX).
 * 4. Zero external UI dependencies (Pure HTML5 Canvas, SVG, ES6).
 */

(function () {
  "use strict";

  // =========================================================================
  // APPLICATION STATE & CONSTANTS
  // =========================================================================

  const state = {
    activeView: "view-constellation",
    camera: {
      x: 0,
      y: 0,
      scale: 1,
      targetX: 0,
      targetY: 0,
      targetScale: 1,
      isDragging: false,
      startX: 0,
      startY: 0,
    },
    overview: null,
    cases: [],
    selectedCase: null,
    selectedBranch: "candidates",
    hoveredNode: null,
    activeTimePeriod: "all",
    particles: [],
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

  // Cluster Definitions matching cosmic visual design
  const CLUSTERS = [
    { id: "subscription", label: "Subscriptions", color: "#a78bfa", glow: "rgba(167, 139, 250, 0.4)", radius: 28, angle: -Math.PI * 0.7, dist: 220, count: 0 },
    { id: "direct", label: "Direct Checkouts", color: "#38bdf8", glow: "rgba(56, 189, 248, 0.4)", radius: 26, angle: -Math.PI * 0.2, dist: 240, count: 0 },
    { id: "high_value", label: "High-Value Capital", color: "#fbbf24", glow: "rgba(251, 191, 36, 0.4)", radius: 30, angle: Math.PI * 0.3, dist: 230, count: 0 },
    { id: "tech_fail", label: "Technical Gateways", color: "#fb7185", glow: "rgba(251, 113, 133, 0.4)", radius: 24, angle: Math.PI * 0.8, dist: 250, count: 0 },
    { id: "settled", label: "Verified Recovered", color: "#34d399", glow: "rgba(52, 211, 153, 0.4)", radius: 32, angle: Math.PI * 1.25, dist: 210, count: 0 },
  ];

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
  // CONSTELLATION GRAPH CANVAS ENGINE
  // =========================================================================

  let canvas, ctx, animFrameId;
  let canvasWidth = 0, canvasHeight = 0;
  let graphNodes = [];
  let graphLinks = [];

  function initCanvas() {
    canvas = document.getElementById("constellationCanvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");

    function resize() {
      canvasWidth = canvas.parentElement.clientWidth;
      canvasHeight = canvas.parentElement.clientHeight;
      canvas.width = canvasWidth * window.devicePixelRatio;
      canvas.height = canvasHeight * window.devicePixelRatio;
      canvas.style.width = canvasWidth + "px";
      canvas.style.height = canvasHeight + "px";
      ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    }
    window.addEventListener("resize", resize);
    resize();

    // Setup Interactive Mouse Events
    canvas.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("click", onCanvasClick);

    // Initialize Cosmic Background Particles
    state.particles = [];
    for (let i = 0; i < 80; i++) {
      state.particles.push({
        x: (Math.random() - 0.5) * 1600,
        y: (Math.random() - 0.5) * 1200,
        size: Math.random() * 1.8 + 0.5,
        alpha: Math.random() * 0.6 + 0.2,
        speed: Math.random() * 0.2 + 0.05,
      });
    }

    startAnimationLoop();
  }

  function buildGraphNetwork() {
    graphNodes = [];
    graphLinks = [];

    // 1. Central Core Hub Node (Sun / Constitution)
    const core = {
      id: "core_recoverai",
      type: "core",
      label: "RecoverAI Revenue Engine",
      x: 0,
      y: 0,
      radius: 44,
      color: "#eab308",
      glow: "rgba(234, 179, 8, 0.5)",
      pulse: 0,
    };
    graphNodes.push(core);

    // 2. Primary Orbiting Domain Clusters
    CLUSTERS.forEach((c) => {
      const cx = Math.cos(c.angle) * c.dist;
      const cy = Math.sin(c.angle) * c.dist;
      const cNode = {
        id: `cluster_${c.id}`,
        type: "cluster",
        clusterId: c.id,
        label: c.label,
        x: cx,
        y: cy,
        radius: c.radius,
        color: c.color,
        glow: c.glow,
        pulse: Math.random() * Math.PI,
      };
      graphNodes.push(cNode);
      graphLinks.push({ from: core, to: cNode, color: c.color, energyPulses: [0.2, 0.6, 0.9] });
    });

    // 3. Child Case Nodes distributed around their respective clusters
    if (state.cases && state.cases.length > 0) {
      state.cases.forEach((item, idx) => {
        let clusterId = "direct";
        if (item.current_state === "RECOVERED") clusterId = "settled";
        else if (item.is_subscription) clusterId = "subscription";
        else if (item.amount_paise >= 500000) clusterId = "high_value";
        else if (item.failure_type === "temporary_failure" || item.current_state === "EXECUTION_FAILED") clusterId = "tech_fail";

        const parentCluster = graphNodes.find((n) => n.id === `cluster_${clusterId}`);
        if (!parentCluster) return;

        const subAngle = (idx * 0.7) + (Math.random() * 0.2);
        const subDist = 65 + (Math.random() * 55);
        const nx = parentCluster.x + Math.cos(subAngle) * subDist;
        const ny = parentCluster.y + Math.sin(subAngle) * subDist;

        const caseNode = {
          id: item.case_id,
          type: "case",
          caseData: item,
          label: maskCustomerId(item.customer_id),
          amount: item.amount_paise,
          state: item.current_state,
          action: item.recommended_action,
          x: nx,
          y: ny,
          radius: Math.max(7, Math.min(15, 6 + Math.log10(item.amount_paise / 1000 + 1) * 3)),
          color: parentCluster.color,
          glow: parentCluster.glow,
          pulse: Math.random() * Math.PI,
        };

        graphNodes.push(caseNode);
        graphLinks.push({ from: parentCluster, to: caseNode, color: parentCluster.color, energyPulses: [Math.random()] });
      });
    }
  }

  function startAnimationLoop() {
    if (animFrameId) cancelAnimationFrame(animFrameId);

    function loop() {
      // Smooth Camera LERP
      state.camera.x += (state.camera.targetX - state.camera.x) * 0.1;
      state.camera.y += (state.camera.targetY - state.camera.y) * 0.1;
      state.camera.scale += (state.camera.targetScale - state.camera.scale) * 0.1;

      if (state.activeView === "view-constellation") {
        renderCanvas();
      }

      animFrameId = requestAnimationFrame(loop);
    }
    loop();
  }

  function renderCanvas() {
    if (!ctx) return;

    ctx.save();
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);

    // Apply Camera Transform
    ctx.translate(canvasWidth / 2 + state.camera.x, canvasHeight / 2 + state.camera.y);
    ctx.scale(state.camera.scale, state.camera.scale);

    const now = Date.now() * 0.002;

    // 1. Draw Cosmic Star Dust Particles
    state.particles.forEach((p) => {
      ctx.beginPath();
      ctx.arc(p.x, p.y + Math.sin(now * p.speed + p.x) * 6, p.size, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(148, 180, 220, ${p.alpha * 0.6})`;
      ctx.fill();
    });

    // 2. Draw Orbital Concentric Distance Rings
    [210, 230, 250].forEach((r, idx) => {
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(148, 163, 184, ${0.04 + idx * 0.02})`;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 8]);
      ctx.stroke();
      ctx.setLineDash([]);
    });

    // 3. Draw Connecting Bezier Filaments & Flowing Energy Pulses
    graphLinks.forEach((link) => {
      const isHovered = state.hoveredNode && (state.hoveredNode === link.from || state.hoveredNode === link.to);
      const strokeAlpha = isHovered ? 0.7 : (link.from.type === "core" ? 0.25 : 0.12);

      // Curved Bezier filament
      ctx.beginPath();
      ctx.moveTo(link.from.x, link.from.y);
      const midX = (link.from.x + link.to.x) / 2 + (link.to.y - link.from.y) * 0.1;
      const midY = (link.from.y + link.to.y) / 2 + (link.from.x - link.to.x) * 0.1;
      ctx.quadraticCurveTo(midX, midY, link.to.x, link.to.y);
      ctx.strokeStyle = isHovered ? link.color : `rgba(148, 163, 184, ${strokeAlpha})`;
      ctx.lineWidth = isHovered ? 2.5 : 1.2;
      ctx.stroke();

      // Energy Pulses along the curve
      link.energyPulses.forEach((pulseOffset, pIdx) => {
        const t = (now * 0.4 + pulseOffset + pIdx * 0.33) % 1.0;
        const px = Math.pow(1 - t, 2) * link.from.x + 2 * (1 - t) * t * midX + Math.pow(t, 2) * link.to.x;
        const py = Math.pow(1 - t, 2) * link.from.y + 2 * (1 - t) * t * midY + Math.pow(t, 2) * link.to.y;

        ctx.beginPath();
        ctx.arc(px, py, isHovered ? 3.5 : 2, 0, Math.PI * 2);
        ctx.fillStyle = link.color;
        ctx.shadowColor = link.color;
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowBlur = 0;
      });
    });

    // 4. Draw Graph Nodes
    graphNodes.forEach((node) => {
      const isHovered = state.hoveredNode === node;
      const pulseSize = Math.sin(now * 2 + node.pulse) * 3;

      if (node.type === "core") {
        // Sun / Hub with Radiating Corona & Rotating Rings
        ctx.save();
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 14 + pulseSize, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(234, 179, 8, 0.08)";
        ctx.fill();

        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 6, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(234, 179, 8, 0.35)";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 6]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Core Glowing Sun Gradient
        const grad = ctx.createRadialGradient(node.x - 8, node.y - 8, 4, node.x, node.y, node.radius);
        grad.addColorStop(0, "#fef08a");
        grad.addColorStop(0.4, "#eab308");
        grad.addColorStop(1, "#ca8a04");

        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.shadowColor = "rgba(234, 179, 8, 0.8)";
        ctx.shadowBlur = 24;
        ctx.fill();
        ctx.shadowBlur = 0;

        // Inner Core Icon
        ctx.fillStyle = "#05070a";
        ctx.font = "bold 11px ui-monospace, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("RECOVERAI", node.x, node.y - 4);
        ctx.font = "9px ui-monospace, sans-serif";
        ctx.fillText("CORE", node.x, node.y + 8);
        ctx.restore();

      } else if (node.type === "cluster") {
        // Orbiting Cluster Orbs
        ctx.save();
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 8 + (isHovered ? 4 : 0), 0, Math.PI * 2);
        ctx.fillStyle = node.glow.replace("0.4", "0.12");
        ctx.fill();

        const grad = ctx.createRadialGradient(node.x - 6, node.y - 6, 2, node.x, node.y, node.radius);
        grad.addColorStop(0, "#ffffff");
        grad.addColorStop(0.4, node.color);
        grad.addColorStop(1, "rgba(10, 18, 26, 0.9)");

        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.shadowColor = node.color;
        ctx.shadowBlur = isHovered ? 20 : 12;
        ctx.fill();
        ctx.shadowBlur = 0;

        // Category Tag Badge
        ctx.font = "bold 10px -apple-system, sans-serif";
        ctx.fillStyle = "#ffffff";
        ctx.textAlign = "center";
        ctx.fillText(node.label, node.x, node.y + node.radius + 14);
        ctx.restore();

      } else {
        // Child Case Nodes
        ctx.save();
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = isHovered ? "#ffffff" : node.color;
        ctx.shadowColor = node.color;
        ctx.shadowBlur = isHovered ? 16 : 6;
        ctx.fill();
        ctx.shadowBlur = 0;

        if (isHovered) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.radius + 5, 0, Math.PI * 2);
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        ctx.restore();
      }
    });

    ctx.restore();
  }

  // =========================================================================
  // MOUSE & CAMERA INTERACTION HANDLERS
  // =========================================================================

  function getCanvasMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left - (canvasWidth / 2 + state.camera.x);
    const my = e.clientY - rect.top - (canvasHeight / 2 + state.camera.y);
    return {
      x: mx / state.camera.scale,
      y: my / state.camera.scale,
      screenX: e.clientX,
      screenY: e.clientY,
    };
  }

  function onMouseDown(e) {
    if (e.button !== 0) return;
    state.camera.isDragging = true;
    state.camera.startX = e.clientX - state.camera.targetX;
    state.camera.startY = e.clientY - state.camera.targetY;
  }

  function onMouseMove(e) {
    if (state.camera.isDragging) {
      state.camera.targetX = e.clientX - state.camera.startX;
      state.camera.targetY = e.clientY - state.camera.startY;
      return;
    }

    if (state.activeView !== "view-constellation" || !canvas) return;
    const pos = getCanvasMousePos(e);

    // Find closest node
    let found = null;
    for (let i = graphNodes.length - 1; i >= 0; i--) {
      const node = graphNodes[i];
      const dx = pos.x - node.x;
      const dy = pos.y - node.y;
      if (dx * dx + dy * dy < (node.radius + 6) * (node.radius + 6)) {
        found = node;
        break;
      }
    }

    state.hoveredNode = found;
    const tooltip = document.getElementById("canvasTooltip");

    if (found && tooltip) {
      tooltip.style.display = "flex";
      tooltip.style.left = `${pos.screenX}px`;
      tooltip.style.top = `${pos.screenY}px`;

      if (found.type === "core") {
        document.getElementById("ttTitle").textContent = "RecoverAI Revenue Engine";
        document.getElementById("ttMeta").textContent = `${state.overview?.total_cases || 0} Total Evaluated Incidents`;
        document.getElementById("ttAmount").textContent = formatPaiseINR(state.overview?.recoverai_net_recovered_paise);
      } else if (found.type === "cluster") {
        document.getElementById("ttTitle").textContent = found.label;
        document.getElementById("ttMeta").textContent = "Domain Entity Cluster";
        document.getElementById("ttAmount").textContent = "Click to focus & inspect";
      } else if (found.type === "case") {
        document.getElementById("ttTitle").textContent = `Case: ${found.id}`;
        document.getElementById("ttMeta").textContent = `${maskCustomerId(found.caseData.customer_id)} • ${found.action.toUpperCase()}`;
        document.getElementById("ttAmount").textContent = formatPaiseINR(found.amount);
      }
    } else if (tooltip) {
      tooltip.style.display = "none";
    }
  }

  function onMouseUp() {
    state.camera.isDragging = false;
  }

  function onWheel(e) {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
    state.camera.targetScale = Math.max(0.4, Math.min(2.8, state.camera.targetScale * zoomFactor));
  }

  function onCanvasClick(e) {
    if (state.hoveredNode) {
      const node = state.hoveredNode;
      if (node.type === "cluster") {
        // Smoothly pan & zoom to cluster
        state.camera.targetX = -node.x * 1.5;
        state.camera.targetY = -node.y * 1.5;
        state.camera.targetScale = 1.6;
      } else if (node.type === "case") {
        // Inspect Case & open Causal Tree view
        inspectCase(node.caseData.case_id);
      }
    }
  }

  // =========================================================================
  // VIEW 2: DENDROGRAM / CAUSAL TREE ENGINE (00:11 - 00:17)
  // =========================================================================

  function renderDendrogramView(caseItem, detailData) {
    if (!caseItem) return;

    document.getElementById("treeEntityName").textContent = `Case ${caseItem.case_id}`;
    document.getElementById("treeEntityCustomer").textContent = maskCustomerId(caseItem.customer_id);
    document.getElementById("treeEntityState").textContent = caseItem.current_state;

    const leafCol = document.getElementById("dendrogramLeafCol");
    if (!leafCol) return;

    // Build branch-specific leaf cards
    let leavesHtml = "";
    if (state.selectedBranch === "candidates") {
      const actions = [
        { name: "no_action", prob: 0.05, cost: 0 },
        { name: "retry", prob: 0.42, cost: 1500 },
        { name: "payment_link", prob: 0.76, cost: 2200 },
        { name: "reminder", prob: 0.38, cost: 800 },
        { name: "escalate", prob: 0.55, cost: 5000 },
      ];
      actions.forEach((act) => {
        const isSelected = act.name === caseItem.recommended_action;
        const gross = Math.floor(act.prob * caseItem.amount_paise);
        const net = gross - act.cost;
        leavesHtml += `
          <div class="leaf-item" onclick="window.inspectCase('${caseItem.case_id}')">
            <div>
              <div class="leaf-title text-bright">${act.name.toUpperCase()} ${isSelected ? '★ SELECTED' : ''}</div>
              <div class="leaf-sub">P(Recovery): ${formatPercent(act.prob)} • Cost: ${formatPaiseINR(act.cost)}</div>
            </div>
            <div class="mono font-bold ${net > 0 ? 'text-emerald' : 'text-dim'}">${formatPaiseINR(net)}</div>
          </div>
        `;
      });
    } else if (state.selectedBranch === "context") {
      leavesHtml = `
        <div class="leaf-item">
          <div><div class="leaf-title">Amount at Risk</div><div class="leaf-sub">Gross uncollected capital</div></div>
          <div class="mono font-bold text-amber">${formatPaiseINR(caseItem.amount_paise)}</div>
        </div>
        <div class="leaf-item">
          <div><div class="leaf-title">Failure Reason</div><div class="leaf-sub">Diagnostic classification</div></div>
          <div class="mono text-bright">${escapeHTML(caseItem.failure_type || "temporary_failure")}</div>
        </div>
        <div class="leaf-item">
          <div><div class="leaf-title">Prior Retries</div><div class="leaf-sub">Exhaustion boundary count</div></div>
          <div class="mono font-bold">${caseItem.retry_count}</div>
        </div>
      `;
    } else if (state.selectedBranch === "execution") {
      const exec = detailData?.action_execution;
      leavesHtml = `
        <div class="leaf-item">
          <div><div class="leaf-title">Dispatched Action</div><div class="leaf-sub">Provider gateway intervention</div></div>
          <div class="mono font-bold text-cyan">${escapeHTML(exec?.action || caseItem.recommended_action)}</div>
        </div>
        <div class="leaf-item">
          <div><div class="leaf-title">Provider Reference</div><div class="leaf-sub">Razorpay payment link / entity</div></div>
          <div class="mono text-bright text-xs">${escapeHTML(exec?.provider_reference || "plink_test_recoverai")}</div>
        </div>
      `;
    } else if (state.selectedBranch === "settlement") {
      const out = detailData?.outcome_settlement;
      leavesHtml = `
        <div class="leaf-item">
          <div><div class="leaf-title">Settlement State</div><div class="leaf-sub">Authoritative invoice proof</div></div>
          <div class="mono font-bold text-emerald">${escapeHTML(out?.outcome_status?.toUpperCase() || caseItem.current_state)}</div>
        </div>
        <div class="leaf-item">
          <div><div class="leaf-title">Recovered Amount</div><div class="leaf-sub">Net financial realization</div></div>
          <div class="mono font-bold text-emerald">${formatPaiseINR(out?.recovered_amount_paise || (caseItem.current_state === 'RECOVERED' ? caseItem.amount_paise : 0))}</div>
        </div>
      `;
    }

    leafCol.innerHTML = leavesHtml;
    drawDendrogramTendrils();
  }

  function drawDendrogramTendrils() {
    const svg = document.getElementById("dendrogramSvg");
    if (!svg) return;
    const orb = document.getElementById("treeEntityOrb");
    const activeBranch = document.querySelector(".branch-card.active");
    if (!orb || !activeBranch) return;

    const orbRect = orb.getBoundingClientRect();
    const branchRect = activeBranch.getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();

    const x1 = orbRect.right - svgRect.left;
    const y1 = orbRect.top + orbRect.height / 2 - svgRect.top;
    const x2 = branchRect.left - svgRect.left;
    const y2 = branchRect.top + branchRect.height / 2 - svgRect.top;

    const cx1 = x1 + (x2 - x1) * 0.5;
    const cx2 = cx1;

    svg.innerHTML = `
      <path class="tendril-line active" d="M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}" />
    `;
  }

  // =========================================================================
  // VIEW SWITCHER & NAVIGATION
  // =========================================================================

  function switchView(viewId) {
    state.activeView = viewId;

    document.querySelectorAll(".tool-btn[data-view]").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view-panel").forEach((p) => p.classList.remove("active"));

    const targetBtn = document.querySelector(`.tool-btn[data-view="${viewId}"]`);
    const targetPanel = document.getElementById(viewId);

    if (targetBtn) targetBtn.classList.add("active");
    if (targetPanel) targetPanel.classList.add("active");

    if (viewId === "view-queue") {
      loadCasesQueue();
    } else if (viewId === "view-analytics") {
      renderFunnel();
      loadTrends();
    } else if (viewId === "view-dendrogram") {
      if (state.selectedCase) {
        inspectCase(state.selectedCase.case_id, false);
      } else if (state.cases && state.cases.length > 0) {
        inspectCase(state.cases[0].case_id, false);
      }
    }
  }

  // =========================================================================
  // RIGHT SLIDE-OUT DEEP INSPECTION DRAWER (00:18 - 00:20)
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

      // Update Header
      document.getElementById("modalCaseTitle").textContent = `Case ${c.case_id}`;
      document.getElementById("modalCaseSubtitle").textContent = `Customer: ${maskCustomerId(c.customer_id)} • Created: ${formatTimestamp(c.created_at)}`;
      document.getElementById("dtCategoryTag").textContent = c.is_subscription ? "SUBSCRIPTION BILLING CYCLE" : "ONE-OFF CHECKOUT";

      // Update Radial Recovery Probability Gauge (00:18 in video)
      const prob = detail.decision_forecast ? detail.decision_forecast.recovery_probability : 0.76;
      const probPct = Math.round(prob * 100);
      document.getElementById("dtGaugeScore").textContent = `${probPct}%`;

      const circle = document.getElementById("dtRadialCircleFill");
      if (circle) {
        const circumference = 2 * Math.PI * 30; // 188.5
        const offset = circumference - (prob * circumference);
        circle.style.strokeDasharray = `${circumference}`;
        circle.style.strokeDashoffset = `${offset}`;
      }

      // Update 2x2 Metric Cards
      document.getElementById("dtAmount").textContent = formatPaiseINR(c.amount_paise);
      document.getElementById("dtDecCost").textContent = formatPaiseINR(detail.decision_forecast?.action_cost_paise || 2200);
      document.getElementById("dtDecNet").textContent = formatPaiseINR(detail.decision_forecast?.expected_net_recovery_paise || Math.floor(c.amount_paise * 0.76 - 2200));
      document.getElementById("dtOutStatus").textContent = c.current_state;

      // Update AI Policy Rationale Box
      if (detail.decision_forecast) {
        document.getElementById("dtDecAction").textContent = detail.decision_forecast.recommended_action.toUpperCase();
        document.getElementById("dtDecExplanation").textContent = detail.decision_forecast.explanation;
      }

      // Candidate Matrix in Drawer
      renderCandidateMatrixTable(detail.decision_forecast, c);

      // Audit Timeline
      renderTimeline(timelineData.events);

      // Also refresh Dendrogram view if open
      renderDendrogramView(c, detail);

    } catch (err) {
      console.warn("Error opening case detail:", err);
    }
  }

  function renderCandidateMatrixTable(decision, caseItem) {
    const tbody = document.getElementById("dtCandidateTableBody");
    if (!tbody) return;

    const actions = [
      { name: "no_action", prob: 0.05, cost: 0 },
      { name: "retry", prob: 0.42, cost: 1500 },
      { name: "payment_link", prob: 0.76, cost: 2200 },
      { name: "reminder", prob: 0.38, cost: 800 },
      { name: "escalate", prob: 0.55, cost: 5000 },
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
        <div style="background:rgba(14,25,36,0.7);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:0.6rem 0.8rem;">
          <div class="flex-between">
            <span class="mono font-bold text-xs text-bright">${escapeHTML(evt.title)}</span>
            <span class="mono text-dim text-xs">${formatTimestamp(evt.timestamp)}</span>
          </div>
          <div class="text-xs text-muted" style="margin-top:0.25rem;">${escapeHTML(evt.description)}</div>
        </div>
      `;
    });
    container.innerHTML = html;
  }

  // =========================================================================
  // DATA QUEUE & ANALYTICS LOADERS
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
      document.getElementById("queueBadgeCount").textContent = data.total_count;

      const totalPages = Math.ceil(data.total_count / state.queue.limit) || 1;
      const currentPage = state.queue.page + 1;
      document.getElementById("paginationInfo").textContent = `Showing ${data.items.length} of ${data.total_count} cases`;
      document.getElementById("pageIndicator").textContent = `Page ${currentPage} of ${totalPages}`;
      document.getElementById("prevPageBtn").disabled = state.queue.page <= 0;
      document.getElementById("nextPageBtn").disabled = currentPage >= totalPages;

      if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="text-center text-dim mono" style="padding:2.5rem;">No cases match active filter criteria.</td></tr>`;
        return;
      }

      let rows = "";
      data.items.forEach((c) => {
        rows += `
          <tr>
            <td class="mono font-bold text-bright">${escapeHTML(c.case_id)}</td>
            <td class="mono text-dim">${escapeHTML(maskCustomerId(c.customer_id))}</td>
            <td class="mono font-bold text-bright">${formatPaiseINR(c.amount_paise)}</td>
            <td><span class="badge badge-test-mode" style="padding:1px 6px;font-size:0.68rem;">${escapeHTML(c.current_state)}</span></td>
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
      { name: "01. AT RISK", count: funnel.cases_at_risk, amount: data.total_amount_at_risk_paise, pct: 100, color: "#f59e0b" },
      { name: "02. DECIDED", count: funnel.decisions_evaluated, amount: null, pct: (funnel.decisions_evaluated / baseCount) * 100, color: "#06b6d4" },
      { name: "03. ACTIONED", count: funnel.interventions_dispatched, amount: null, pct: (funnel.interventions_dispatched / baseCount) * 100, color: "#3b82f6" },
      { name: "04. SETTLED", count: funnel.successful_executions, amount: null, pct: (funnel.successful_executions / baseCount) * 100, color: "#8b5cf6" },
      { name: "05. RECOVERED", count: funnel.recovered_outcomes, amount: data.gross_recovered_paise, pct: (funnel.recovered_outcomes / baseCount) * 100, color: "#10b981" },
    ];

    let html = "";
    stages.forEach((s) => {
      const widthPct = Math.max(10, Math.min(100, s.pct));
      const amountLabel = s.amount !== null ? ` • ${formatPaiseINR(s.amount)}` : "";
      html += `
        <div style="display:grid;grid-template-columns:120px 1fr 180px;gap:1rem;align-items:center;margin-bottom:0.75rem;">
          <div class="mono text-xs font-bold text-dim text-right">${s.name}</div>
          <div style="background:rgba(148,163,184,0.08);border-radius:var(--radius-sm);height:28px;overflow:hidden;border:1px solid var(--border-subtle);">
            <div style="height:100%;width:${widthPct}%;background:${s.color};display:flex;align-items:center;padding-left:0.75rem;color:#ffffff;font-family:var(--font-mono);font-size:0.725rem;font-weight:700;">
              ${s.count} (${s.pct.toFixed(1)}%)
            </div>
          </div>
          <div class="mono font-bold text-xs text-bright text-right">${s.count} cases ${amountLabel}</div>
        </div>
      `;
    });
    container.innerHTML = html;
  }

  async function loadTrends() {
    const container = document.getElementById("trendChartContainer");
    if (!container) return;
    const interval = document.getElementById("trendIntervalSelect")?.value || "daily";

    try {
      const trends = await fetchAPI(`/api/v1/analytics/trends?interval=${interval}`);
      if (!trends || trends.length === 0) {
        container.innerHTML = `<div class="text-dim text-xs mono text-center" style="padding:2rem;">No trend data available</div>`;
        return;
      }

      const maxGross = Math.max(...trends.map((t) => t.gross_recovered_paise), 1);
      let chartHtml = `<div style="display:flex;gap:0.85rem;align-items:flex-end;height:160px;padding:1rem 0;overflow-x:auto;">`;
      trends.forEach((t) => {
        const heightPct = Math.max(8, Math.round((t.gross_recovered_paise / maxGross) * 100));
        chartHtml += `
          <div style="display:flex;flex-direction:column;align-items:center;gap:0.4rem;min-width:54px;">
            <span class="mono text-xs text-emerald font-bold">${formatPaiseINR(t.gross_recovered_paise)}</span>
            <div style="width:32px;height:${heightPct}px;background:linear-gradient(180deg,#0284c7,#06b6d4);border-radius:var(--radius-sm);" title="${t.time_bucket}: ${formatPaiseINR(t.gross_recovered_paise)}"></div>
            <span class="mono text-xs text-dim">${escapeHTML(t.time_bucket.slice(5))}</span>
          </div>
        `;
      });
      chartHtml += `</div>`;
      container.innerHTML = chartHtml;
    } catch (_) {}
  }

  // =========================================================================
  // DATA SYNC & BOOTSTRAP
  // =========================================================================

  async function loadAllData() {
    try {
      const [overviewData, casesData] = await Promise.all([
        fetchAPI("/api/v1/dashboard/overview"),
        fetchAPI("/api/v1/recovery/cases?limit=60"),
      ]);

      state.overview = overviewData;
      state.cases = casesData.items || [];

      // Update Bottom Telemetry Deck Chips
      document.getElementById("kpiRecoveryRate").textContent = formatPercent(overviewData.recovery_rate);
      document.getElementById("kpiRevenueAtRisk").textContent = formatPaiseINR(overviewData.total_amount_at_risk_paise);
      document.getElementById("kpiNetRecovered").textContent = formatPaiseINR(overviewData.recoverai_net_recovered_paise);
      document.getElementById("kpiProviderGross").textContent = formatPaiseINR(overviewData.provider_gross_recovered_paise);
      document.getElementById("kpiActiveCases").textContent = overviewData.pending_cases;

      // Build & Render Cosmos Graph
      buildGraphNetwork();

    } catch (err) {
      console.warn("Failed loading live telemetry:", err);
    }
  }

  // Expose global inspector for inline click triggers
  window.inspectCase = inspectCase;

  function init() {
    initCanvas();

    // Toolbar View Switchers
    document.querySelectorAll(".tool-btn[data-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const v = btn.getAttribute("data-view");
        switchView(v);
      });
    });

    // Camera Zoom Controls
    document.getElementById("btnZoomIn")?.addEventListener("click", () => {
      state.camera.targetScale = Math.min(2.8, state.camera.targetScale * 1.25);
    });
    document.getElementById("btnZoomOut")?.addEventListener("click", () => {
      state.camera.targetScale = Math.max(0.4, state.camera.targetScale * 0.8);
    });
    document.getElementById("btnResetCamera")?.addEventListener("click", () => {
      state.camera.targetX = 0;
      state.camera.targetY = 0;
      state.camera.targetScale = 1;
    });

    // Left Timeline Scrubber Rail Buttons
    document.querySelectorAll(".timeline-step-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".timeline-step-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.activeTimePeriod = btn.getAttribute("data-period");
        loadAllData();
      });
    });

    // Dendrogram Branch Selector Cards
    document.querySelectorAll(".branch-card").forEach((card) => {
      card.addEventListener("click", () => {
        document.querySelectorAll(".branch-card").forEach((c) => c.classList.remove("active"));
        card.classList.add("active");
        state.selectedBranch = card.getAttribute("data-branch");
        if (state.selectedCase) {
          inspectCase(state.selectedCase.case_id, false);
        }
      });
    });

    // Drawer Close
    document.getElementById("modalCloseBtn")?.addEventListener("click", () => {
      document.getElementById("caseDetailModal")?.classList.remove("open");
    });

    // AI Copilot Drawer Toggle
    document.getElementById("btnToggleAIInsights")?.addEventListener("click", () => {
      document.getElementById("aiInsightsDrawer")?.classList.toggle("open");
    });
    document.getElementById("btnCloseAIInsights")?.addEventListener("click", () => {
      document.getElementById("aiInsightsDrawer")?.classList.remove("open");
    });

    // Manual Trigger Sync Button
    document.getElementById("btnTriggerSimulation")?.addEventListener("click", () => {
      loadAllData();
    });

    // Queue Filters
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
    setInterval(loadAllData, state.autoRefreshInterval);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
