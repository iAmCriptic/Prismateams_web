(() => {
  if (typeof Konva === "undefined") return;
  const stageContainer = document.getElementById("floorPlanStage");
  if (!stageContainer) return;

  const api = window.PLAN_API || {};
  const ui = {
    currentPlanInfo: document.getElementById("currentPlanInfo"),
    stageEmptyState: document.getElementById("stageEmptyState"),
    zoomInButton: document.getElementById("zoomInButton"),
    zoomOutButton: document.getElementById("zoomOutButton"),
    fitViewButton: document.getElementById("fitViewButton"),
    legendContent: document.getElementById("legendContent"),
    infoPanel: document.getElementById("infoPanel"),
    infoTitle: document.getElementById("infoTitle"),
    infoBody: document.getElementById("infoBody"),
  };

  const TRASH_COLOR_MAP = {
    yellow: "#facc15",
    blue: "#3b82f6",
    black: "#111827",
    green: "#16a34a",
  };

  const state = { plan: null, objects: [], image: null };

  const stage = new Konva.Stage({
    container: "floorPlanStage",
    width: Math.max(stageContainer.clientWidth, 100),
    height: Math.max(stageContainer.clientHeight, 100),
    draggable: true,
  });
  const bgLayer = new Konva.Layer();
  const objLayer = new Konva.Layer();
  stage.add(bgLayer);
  stage.add(objLayer);

  function computeContrastColor(hex) {
    const clean = (hex || "#cccccc").replace("#", "");
    if (clean.length < 6) return "#111827";
    const r = parseInt(clean.slice(0, 2), 16) || 0;
    const g = parseInt(clean.slice(2, 4), 16) || 0;
    const b = parseInt(clean.slice(4, 6), 16) || 0;
    return (r * 299 + g * 587 + b * 114) / 1000 > 145 ? "#111827" : "#ffffff";
  }

  function fitToViewport() {
    if (!state.image) return;
    const w = state.image.width();
    const h = state.image.height();
    if (!w || !h) return;
    const scale = Math.min(stage.width() / w, stage.height() / h) * 0.98;
    stage.scale({ x: scale, y: scale });
    stage.position({
      x: (stage.width() - w * scale) / 2,
      y: (stage.height() - h * scale) / 2,
    });
    stage.batchDraw();
  }

  function zoomAtPoint(nextScale, center) {
    const oldScale = stage.scaleX();
    const pointer = center || stage.getPointerPosition() || { x: stage.width() / 2, y: stage.height() / 2 };
    const pointTo = {
      x: (pointer.x - stage.x()) / oldScale,
      y: (pointer.y - stage.y()) / oldScale,
    };
    stage.scale({ x: nextScale, y: nextScale });
    stage.position({
      x: pointer.x - pointTo.x * nextScale,
      y: pointer.y - pointTo.y * nextScale,
    });
    stage.batchDraw();
  }

  function showObjectInfo(obj) {
    if (!ui.infoPanel) return;
    ui.infoPanel.classList.remove("d-none");
    if (obj.type === "stand") {
      ui.infoTitle.textContent = obj.custom_stand_name || obj.stand_name || "Stand";
      ui.infoBody.innerHTML = `
        <div><i class="bi bi-palette me-1"></i>Farbe: <span class="legend-swatch" style="background:${obj.color || '#ccc'}"></span></div>
      `;
    } else if (obj.type === "trash_can") {
      ui.infoTitle.textContent = "Mülleimer";
      ui.infoBody.textContent = `Farbe: ${obj.trash_can_color || 'gelb'}`;
    } else if (obj.type === "power_outlet") {
      ui.infoTitle.textContent = "Steckdose";
      ui.infoBody.textContent = `Label: ${obj.power_outlet_label || '-'}`;
    } else if (obj.type === "wc") {
      ui.infoTitle.textContent = "WC";
      ui.infoBody.textContent = obj.wc_label || "WC";
    }
  }

  function renderObjects() {
    objLayer.destroyChildren();
    state.objects.forEach((obj) => {
      const x = Number(obj.x || 0);
      const y = Number(obj.y || 0);
      const w = Number(obj.width || 30);
      const h = Number(obj.height || 30);
      let node;
      let label = null;

      if (obj.type === "stand") {
        node = new Konva.Rect({
          x, y, width: w, height: h,
          fill: obj.color || "#cccccc",
          stroke: "#111827", strokeWidth: 2, cornerRadius: 4,
        });
        label = new Konva.Text({
          x, y, width: w, height: h,
          text: obj.custom_stand_name || obj.stand_name || "",
          align: "center", verticalAlign: "middle",
          fontSize: Math.max(11, Math.min(22, h * 0.22)),
          fill: computeContrastColor(obj.color || "#cccccc"),
          listening: false,
        });
      } else if (obj.type === "trash_can") {
        const r = Math.max(w, h) / 2 || 15;
        node = new Konva.Circle({
          x: x + r, y: y + r, radius: r,
          fill: TRASH_COLOR_MAP[obj.trash_can_color || "yellow"] || TRASH_COLOR_MAP.yellow,
          stroke: "#111827", strokeWidth: 2,
        });
      } else if (obj.type === "power_outlet") {
        const r = Math.max(w, h) / 2 || 15;
        node = new Konva.Circle({
          x: x + r, y: y + r, radius: r,
          fill: "#16a34a", stroke: "#111827", strokeWidth: 2,
        });
        label = new Konva.Text({
          x, y, width: r * 2, height: r * 2,
          text: obj.power_outlet_label || "",
          align: "center", verticalAlign: "middle",
          fontStyle: "bold", fontSize: 12, fill: "#ffffff",
          listening: false,
        });
      } else if (obj.type === "wc") {
        node = new Konva.Rect({
          x, y, width: w, height: h,
          fill: "#8b5cf6", stroke: "#111827", strokeWidth: 2, cornerRadius: 4,
        });
        label = new Konva.Text({
          x, y, width: w, height: h,
          text: obj.wc_label || "WC",
          align: "center", verticalAlign: "middle",
          fontStyle: "bold", fontSize: 13, fill: "#ffffff",
          listening: false,
        });
      } else {
        node = new Konva.Rect({ x, y, width: w, height: h, fill: "#94a3b8" });
      }

      node.on("click tap", (e) => {
        e.cancelBubble = true;
        showObjectInfo(obj);
      });

      objLayer.add(node);
      if (label) objLayer.add(label);
    });
    objLayer.batchDraw();
  }

  function renderLegend() {
    const stands = state.objects.filter((o) => o.type === "stand");
    if (!stands.length) {
      ui.legendContent.innerHTML = '<p class="small text-muted mb-0">Keine Objekte vorhanden.</p>';
      return;
    }
    const grouped = new Map();
    for (const s of stands) {
      const key = (s.color || "#cccccc").toLowerCase();
      const name = s.custom_stand_name || s.stand_name || "Stand";
      if (!grouped.has(key)) grouped.set(key, new Set());
      grouped.get(key).add(name);
    }
    ui.legendContent.innerHTML = "";
    grouped.forEach((names, color) => {
      const row = document.createElement("div");
      row.className = "d-flex align-items-center gap-2 mb-1 small";
      row.innerHTML = `<span class="legend-swatch" style="background:${color}"></span><span>${Array.from(names).join(", ")}</span>`;
      ui.legendContent.appendChild(row);
    });
  }

  async function loadPlan() {
    try {
      const response = await fetch(api.getActivePlan);
      if (response.status === 404) {
        ui.currentPlanInfo.textContent = "Kein aktiver Plan vorhanden";
        ui.stageEmptyState.classList.remove("d-none");
        return;
      }
      const data = await response.json();
      if (!data.success || !data.plan) {
        ui.currentPlanInfo.textContent = "Kein aktiver Plan vorhanden";
        ui.stageEmptyState.classList.remove("d-none");
        return;
      }
      state.plan = data.plan;
      state.objects = data.objects || [];
      ui.currentPlanInfo.textContent = state.plan.name;
      ui.stageEmptyState.classList.add("d-none");

      Konva.Image.fromURL(state.plan.image_url, (img) => {
        bgLayer.destroyChildren();
        img.setAttrs({ x: 0, y: 0, listening: false });
        state.image = img;
        bgLayer.add(img);
        bgLayer.batchDraw();
        fitToViewport();
        renderObjects();
        renderLegend();
      });
    } catch (err) {
      ui.currentPlanInfo.textContent = "Fehler beim Laden";
    }
  }

  stage.on("click tap", (e) => {
    if (e.target === stage || e.target === state.image) {
      ui.infoPanel?.classList.add("d-none");
    }
  });

  stageContainer.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = 1.08;
    const next = e.deltaY < 0 ? stage.scaleX() * factor : stage.scaleX() / factor;
    zoomAtPoint(Math.max(0.1, Math.min(6, next)), { x: e.offsetX, y: e.offsetY });
  }, { passive: false });

  ui.zoomInButton?.addEventListener("click", () => zoomAtPoint(Math.min(6, stage.scaleX() * 1.15)));
  ui.zoomOutButton?.addEventListener("click", () => zoomAtPoint(Math.max(0.1, stage.scaleX() / 1.15)));
  ui.fitViewButton?.addEventListener("click", fitToViewport);

  window.addEventListener("resize", () => {
    stage.width(Math.max(stageContainer.clientWidth, 100));
    stage.height(Math.max(stageContainer.clientHeight, 100));
    fitToViewport();
  });

  loadPlan();
})();
