(() => {
  if (typeof Konva === "undefined") return;
  const stageContainer = document.getElementById("floorPlanStage");
  if (!stageContainer) return;

  const api = window.PLAN_API || {};
  const ui = {
    floorPlanUpload: document.getElementById("floorPlanUpload"),
    uploadPlanButton: document.getElementById("uploadPlanButton"),
    currentPlanInfo: document.getElementById("currentPlanInfo"),
    toggleScaleModeButton: document.getElementById("toggleScaleModeButton"),
    scalePoint1Display: document.getElementById("scalePoint1Display"),
    scalePoint2Display: document.getElementById("scalePoint2Display"),
    scaleDistanceInput: document.getElementById("scaleDistanceInput"),
    setScaleButton: document.getElementById("setScaleButton"),
    pixelsPerMeterDisplay: document.getElementById("pixelsPerMeterDisplay"),
    objectPropertiesPanel: document.getElementById("objectPropertiesPanel"),
    closePropertiesButton: document.getElementById("closePropertiesButton"),
    objectStandIdSelect: document.getElementById("objectStandId"),
    useCustomStandNameCheckbox: document.getElementById("useCustomStandName"),
    standCustomNameInput: document.getElementById("standCustomNameInput"),
    standProperties: document.getElementById("standProperties"),
    standWidthInput: document.getElementById("standWidth"),
    standHeightInput: document.getElementById("standHeight"),
    standColorInput: document.getElementById("standColor"),
    trashCanProperties: document.getElementById("trashCanProperties"),
    trashCanColorSelect: document.getElementById("trashCanColorSelect"),
    powerOutletProperties: document.getElementById("powerOutletProperties"),
    powerOutletLabelInput: document.getElementById("powerOutletLabel"),
    wcProperties: document.getElementById("wcProperties"),
    wcLabelInput: document.getElementById("wcLabel"),
    saveObjectButton: document.getElementById("saveObjectButton"),
    deleteObjectButton: document.getElementById("deleteObjectButton"),
    legendContent: document.getElementById("legendContent"),
    zoomInButton: document.getElementById("zoomInButton"),
    zoomOutButton: document.getElementById("zoomOutButton"),
    fitViewButton: document.getElementById("fitViewButton"),
    stageEmptyState: document.getElementById("stageEmptyState"),
    toast: document.getElementById("inlineMessageContainer"),
  };

  const TRASH_COLOR_MAP = {
    yellow: "#facc15",
    blue: "#3b82f6",
    black: "#111827",
    green: "#16a34a",
  };

  const state = {
    currentPlan: null,
    objects: [],
    availableStands: [],
    selected: null,
    scalePoints: [],
    scaleMode: false,
    placeType: null,
    floorPlanImageObj: null,
    scaleOverlayNodes: [],
    pendingSaveTimers: new Map(),
    localIdCounter: 0,
    toolboxDrag: null,
    suppressToolboxClickUntil: 0,
  };

  const stage = new Konva.Stage({
    container: "floorPlanStage",
    width: Math.max(stageContainer.clientWidth, 100),
    height: Math.max(stageContainer.clientHeight, 100),
    draggable: true,
  });
  const bgLayer = new Konva.Layer();
  const objLayer = new Konva.Layer();
  const overlayLayer = new Konva.Layer();
  overlayLayer.listening(false);
  stage.add(bgLayer);
  stage.add(objLayer);
  stage.add(overlayLayer);

  const transformer = new Konva.Transformer({
    enabledAnchors: ["top-left", "top-right", "bottom-left", "bottom-right"],
    rotateEnabled: false,
    anchorSize: 10,
    borderStroke: "#0d6efd",
    anchorStroke: "#0d6efd",
    anchorFill: "#ffffff",
    anchorCornerRadius: 2,
    keepRatio: false,
  });
  objLayer.add(transformer);

  // ---------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------
  function toast(text, type = "info", duration = 2800) {
    if (!ui.toast) return;
    ui.toast.textContent = text;
    ui.toast.className = `assessment-toast show ${type}`;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      ui.toast.className = "assessment-toast";
    }, duration);
  }

  function nextLocalId() {
    state.localIdCounter += 1;
    return `tmp-${Date.now()}-${state.localIdCounter}`;
  }

  function getPixelsPerMeter() {
    return state.currentPlan?.pixels_per_meter || 0;
  }

  function metersToPx(m) {
    const ppm = getPixelsPerMeter() || 1;
    return Number(m || 0) * ppm;
  }

  function pxToMeters(px) {
    const ppm = getPixelsPerMeter();
    if (!ppm) return "";
    return (Number(px || 0) / ppm).toFixed(1);
  }

  function computeContrastColor(hex) {
    const clean = (hex || "#cccccc").replace("#", "");
    if (clean.length < 6) return "#111827";
    const r = parseInt(clean.slice(0, 2), 16) || 0;
    const g = parseInt(clean.slice(2, 4), 16) || 0;
    const b = parseInt(clean.slice(4, 6), 16) || 0;
    const brightness = (r * 299 + g * 587 + b * 114) / 1000;
    return brightness > 145 ? "#111827" : "#ffffff";
  }

  function resizeStageToContainer() {
    if (!stageContainer) return;
    stage.width(Math.max(stageContainer.clientWidth, 100));
    stage.height(Math.max(stageContainer.clientHeight, 100));
  }

  // ---------------------------------------------------------------------
  // Konva Nodes
  // ---------------------------------------------------------------------
  function createNodeFromObj(obj) {
    const nodeId = String(obj.id || nextLocalId());
    const baseX = Number(obj.x || 0);
    const baseY = Number(obj.y || 0);
    const baseW = Number(obj.width || 30);
    const baseH = Number(obj.height || 30);
    const draggable = !state.scaleMode;

    let node;
    let label = null;

    if (obj.type === "stand") {
      node = new Konva.Rect({
        id: nodeId,
        x: baseX,
        y: baseY,
        width: baseW || 80,
        height: baseH || 80,
        fill: obj.color || "#cccccc",
        stroke: "#111827",
        strokeWidth: 2,
        cornerRadius: 4,
        draggable,
      });
      const displayName = obj.custom_stand_name || obj.stand_name || "";
      label = new Konva.Text({
        x: baseX,
        y: baseY,
        width: baseW || 80,
        height: baseH || 80,
        text: displayName,
        align: "center",
        verticalAlign: "middle",
        fontSize: 9,
        padding: 1,
        fill: computeContrastColor(obj.color || "#cccccc"),
        listening: false,
      });
    } else if (obj.type === "trash_can") {
      const radius = Math.max(baseW, baseH) / 2 || 15;
      const fill = TRASH_COLOR_MAP[obj.trash_can_color || "yellow"] || TRASH_COLOR_MAP.yellow;
      node = new Konva.Circle({
        id: nodeId,
        x: baseX + radius,
        y: baseY + radius,
        radius,
        fill,
        stroke: "#111827",
        strokeWidth: 2,
        draggable,
      });
    } else if (obj.type === "power_outlet") {
      const radius = Math.max(baseW, baseH) / 2 || 15;
      node = new Konva.Circle({
        id: nodeId,
        x: baseX + radius,
        y: baseY + radius,
        radius,
        fill: "#16a34a",
        stroke: "#111827",
        strokeWidth: 2,
        draggable,
      });
      label = new Konva.Text({
        x: baseX,
        y: baseY,
        width: radius * 2,
        height: radius * 2,
        text: obj.power_outlet_label || "",
        align: "center",
        verticalAlign: "middle",
        fontStyle: "bold",
        fontSize: 12,
        fill: "#ffffff",
        listening: false,
      });
    } else if (obj.type === "wc") {
      node = new Konva.Rect({
        id: nodeId,
        x: baseX,
        y: baseY,
        width: baseW || 28,
        height: baseH || 28,
        fill: "#8b5cf6",
        stroke: "#111827",
        strokeWidth: 2,
        cornerRadius: 4,
        draggable,
      });
      label = new Konva.Text({
        x: baseX,
        y: baseY,
        width: baseW || 28,
        height: baseH || 28,
        text: obj.wc_label || "WC",
        align: "center",
        verticalAlign: "middle",
        fontStyle: "bold",
        fontSize: 13,
        fill: "#ffffff",
        listening: false,
      });
    } else {
      node = new Konva.Rect({
        id: nodeId,
        x: baseX,
        y: baseY,
        width: baseW,
        height: baseH,
        fill: "#94a3b8",
        stroke: "#111827",
        strokeWidth: 2,
        draggable,
      });
    }

    const meta = { ...obj };
    meta.id = obj.id || null;
    meta.localId = nodeId;
    node.setAttr("meta", meta);
    if (label) node.setAttr("labelNode", label);

    node.on("click tap", (e) => {
      e.cancelBubble = true;
      if (state.scaleMode) return;
      selectNode(node);
    });
    node.on("dragmove", (evt) => {
      // Falls pointerup/mouseup verloren geht: Drag sofort beenden,
      // sobald keine Primär-Maustaste mehr gedrückt ist.
      if (!isPrimaryPointerDown(evt)) {
        forceStopNodeDrag(node);
        return;
      }
      clampToImage(node);
    });
    node.on("dragmove transform", () => syncNodeVisual(node));
    node.on("dragend transformend", () => {
      syncNodeVisual(node);
      scheduleSave(node);
    });

    return node;
  }

  function clampToImage(node) {
    if (!state.floorPlanImageObj) return;
    const maxW = state.floorPlanImageObj.width();
    const maxH = state.floorPlanImageObj.height();
    if (node.className === "Circle") {
      const r = (node.radius() || 15) * Math.max(node.scaleX(), node.scaleY());
      node.x(Math.max(r, Math.min(node.x(), maxW - r)));
      node.y(Math.max(r, Math.min(node.y(), maxH - r)));
      return;
    }
    const w = node.width() * node.scaleX();
    const h = node.height() * node.scaleY();
    node.x(Math.max(0, Math.min(node.x(), maxW - w)));
    node.y(Math.max(0, Math.min(node.y(), maxH - h)));
  }

  function isPrimaryPointerDown(evt) {
    const nativeEvt = evt?.evt;
    if (!nativeEvt) return true;
    if (typeof nativeEvt.buttons === "number") return (nativeEvt.buttons & 1) === 1;
    if (typeof nativeEvt.which === "number") return nativeEvt.which === 1;
    return true;
  }

  function forceStopNodeDrag(node, persist = true) {
    if (!node || typeof node.stopDrag !== "function") return;
    if (typeof node.isDragging === "function" && !node.isDragging()) return;
    node.stopDrag();
    syncNodeVisual(node);
    if (persist) scheduleSave(node);
  }

  function syncNodeVisual(node) {
    const meta = node.getAttr("meta");
    const labelNode = node.getAttr("labelNode");
    if (!meta || !labelNode) return;
    const isRect = node.className === "Rect";
    if (isRect) {
      const w = node.width() * node.scaleX();
      const h = node.height() * node.scaleY();
      labelNode.position({ x: node.x(), y: node.y() });
      labelNode.width(w);
      labelNode.height(h);
      if (meta.type === "stand") {
        const base = Math.min(w, h);
        const fontSize = Math.max(6, Math.min(10, base * 0.22));
        labelNode.fontSize(fontSize);
        labelNode.visible(w >= 28 && h >= 14);
        labelNode.text(meta.custom_stand_name || meta.stand_name || "");
        labelNode.fill(computeContrastColor(meta.color || "#cccccc"));
      } else if (meta.type === "wc") {
        labelNode.fontSize(Math.max(10, Math.min(16, h * 0.22)));
        labelNode.visible(true);
        labelNode.text(meta.wc_label || "WC");
      }
    } else {
      const r = (node.radius() || 15) * Math.max(node.scaleX(), node.scaleY());
      labelNode.position({ x: node.x() - r, y: node.y() - r });
      labelNode.width(r * 2);
      labelNode.height(r * 2);
      if (meta.type === "power_outlet") labelNode.text(meta.power_outlet_label || "");
    }
  }

  function rebuildObjects() {
    transformer.nodes([]);
    objLayer.destroyChildren();
    objLayer.add(transformer);
    state.objects.forEach((obj) => {
      const node = createNodeFromObj(obj);
      objLayer.add(node);
      const labelNode = node.getAttr("labelNode");
      if (labelNode) objLayer.add(labelNode);
      syncNodeVisual(node);
    });
    transformer.moveToTop();
    objLayer.batchDraw();
    refreshLegend();
  }

  function upsertObjectFromNode(node) {
    const meta = node.getAttr("meta") || {};
    const isRect = node.className === "Rect";
    const isCircle = node.className === "Circle";
    const circleScale = Math.max(node.scaleX(), node.scaleY());
    const circleDiameter = Number((node.radius() || 15) * 2 * circleScale);
    const payload = {
      ...meta,
      x: isCircle ? node.x() - circleDiameter / 2 : node.x(),
      y: isCircle ? node.y() - circleDiameter / 2 : node.y(),
      width: isRect ? node.width() * node.scaleX() : circleDiameter,
      height: isRect ? node.height() * node.scaleY() : circleDiameter,
    };
    if (isCircle) node.radius(circleDiameter / 2);
    node.scaleX(1);
    node.scaleY(1);
    node.setAttr("meta", payload);

    const idx = state.objects.findIndex((o) => {
      if (meta.id && o.id) return String(o.id) === String(meta.id);
      return o.localId && o.localId === meta.localId;
    });
    if (idx >= 0) state.objects[idx] = { ...state.objects[idx], ...payload };
    else state.objects.push(payload);
    return payload;
  }

  function scheduleSave(node) {
    const meta = upsertObjectFromNode(node);
    const key = String(meta.id || meta.localId || node.id());
    clearTimeout(state.pendingSaveTimers.get(key));
    state.pendingSaveTimers.set(
      key,
      setTimeout(() => saveObject(node, meta), 180),
    );
  }

  async function saveObject(node, obj) {
    if (!state.currentPlan) return;
    const payload = {
      id: obj.id || null,
      plan_id: state.currentPlan.id,
      type: obj.type,
      x: obj.x,
      y: obj.y,
      width: obj.width,
      height: obj.height,
      color: obj.color || null,
      trash_can_color: obj.trash_can_color || null,
      power_outlet_label: obj.power_outlet_label || null,
      wc_label: obj.wc_label || null,
      stand_id: obj.stand_id || null,
      custom_stand_name: obj.custom_stand_name || null,
    };
    try {
      const response = await fetch(api.saveObject, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!data.success) {
        toast(data.message || "Objekt konnte nicht gespeichert werden.", "danger");
        return;
      }
      if (data.object_id) {
        obj.id = data.object_id;
        node.setAttr("meta", { ...obj, id: data.object_id });
        const stateObj = state.objects.find((o) => o.localId === obj.localId);
        if (stateObj) stateObj.id = data.object_id;
      }
    } catch (err) {
      toast("Speichern fehlgeschlagen.", "danger");
    }
  }

  // ---------------------------------------------------------------------
  // Selection / Properties-Panel
  // ---------------------------------------------------------------------
  function selectNode(node) {
    state.selected = node;
    const meta = node.getAttr("meta") || {};
    if (meta.type === "stand" || meta.type === "wc") {
      transformer.nodes([node]);
      transformer.moveToTop();
    } else {
      transformer.nodes([]);
    }
    ui.objectPropertiesPanel.classList.remove("d-none");
    ui.standProperties.classList.toggle("d-none", meta.type !== "stand");
    ui.trashCanProperties.classList.toggle("d-none", meta.type !== "trash_can");
    ui.powerOutletProperties.classList.toggle("d-none", meta.type !== "power_outlet");
    ui.wcProperties.classList.toggle("d-none", meta.type !== "wc");

    if (meta.type === "stand") {
      ui.standWidthInput.value = pxToMeters(meta.width);
      ui.standHeightInput.value = pxToMeters(meta.height);
      ui.standColorInput.value = meta.color || "#cccccc";
      ui.objectStandIdSelect.value = meta.stand_id ? String(meta.stand_id) : "";
      ui.useCustomStandNameCheckbox.checked = !!meta.custom_stand_name;
      ui.standCustomNameInput.value = meta.custom_stand_name || "";
      ui.standCustomNameInput.disabled = !ui.useCustomStandNameCheckbox.checked;
      ui.objectStandIdSelect.disabled = ui.useCustomStandNameCheckbox.checked;
    }
    if (meta.type === "trash_can") {
      ui.trashCanColorSelect.value = meta.trash_can_color || "yellow";
    }
    if (meta.type === "power_outlet") {
      ui.powerOutletLabelInput.value = meta.power_outlet_label || "";
    }
    if (meta.type === "wc") {
      ui.wcLabelInput.value = meta.wc_label || "WC";
    }
    objLayer.batchDraw();
  }

  function deselectNode() {
    state.selected = null;
    transformer.nodes([]);
    ui.objectPropertiesPanel.classList.add("d-none");
    objLayer.batchDraw();
  }

  // ---------------------------------------------------------------------
  // Maßstab
  // ---------------------------------------------------------------------
  function clearScaleOverlay() {
    state.scaleOverlayNodes.forEach((n) => n.destroy());
    state.scaleOverlayNodes = [];
    overlayLayer.batchDraw();
  }

  function renderScaleOverlay() {
    clearScaleOverlay();
    if (!state.scalePoints.length) return;
    // Größe unabhängig vom Zoom: durch stage.scale dividieren.
    const scale = stage.scaleX() || 1;
    const pointRadius = 4 / scale;
    const pointStroke = 1 / scale;
    const lineStroke = 1.5 / scale;
    state.scalePoints.forEach((p, i) => {
      const dot = new Konva.Circle({
        x: p.x,
        y: p.y,
        radius: pointRadius,
        fill: i === 0 ? "#ef4444" : "#22c55e",
        stroke: "#ffffff",
        strokeWidth: pointStroke,
      });
      state.scaleOverlayNodes.push(dot);
      overlayLayer.add(dot);
    });
    if (state.scalePoints.length === 2) {
      const [p1, p2] = state.scalePoints;
      const line = new Konva.Line({
        points: [p1.x, p1.y, p2.x, p2.y],
        stroke: "#f59e0b",
        strokeWidth: lineStroke,
        dash: [6 / scale, 4 / scale],
      });
      state.scaleOverlayNodes.push(line);
      overlayLayer.add(line);
    }
    overlayLayer.batchDraw();
  }

  function calculatePixelsPerMeter() {
    if (!state.currentPlan) return null;
    const distanceMeters = parseFloat(ui.scaleDistanceInput.value || "");
    if (state.scalePoints.length !== 2 || !Number.isFinite(distanceMeters) || distanceMeters <= 0) {
      ui.pixelsPerMeterDisplay.textContent = "Maßstab: Nicht definiert";
      ui.setScaleButton.disabled = true;
      return null;
    }
    const [p1, p2] = state.scalePoints;
    const pixelDistance = Math.hypot(p2.x - p1.x, p2.y - p1.y);
    const ppm = pixelDistance / distanceMeters;
    ui.pixelsPerMeterDisplay.textContent = `Maßstab: ${ppm.toFixed(2)} Pixel/Meter`;
    ui.setScaleButton.disabled = false;
    state.currentPlan.pixels_per_meter = ppm;
    return ppm;
  }

  function toggleScaleMode(forceState) {
    state.scaleMode = typeof forceState === "boolean" ? forceState : !state.scaleMode;
    if (state.scaleMode) {
      ui.toggleScaleModeButton.textContent = "Maßstab-Modus deaktivieren";
      ui.toggleScaleModeButton.classList.add("assessment-scale-active");
      stageContainer.classList.add("scale-mode");
      toast("Maßstab-Modus aktiv – zwei Punkte auf dem Plan setzen.", "info");
    } else {
      ui.toggleScaleModeButton.textContent = "Maßstab-Modus aktivieren";
      ui.toggleScaleModeButton.classList.remove("assessment-scale-active");
      stageContainer.classList.remove("scale-mode");
    }
    // Im Scale-Modus dürfen weder Stage noch Nodes gezogen werden.
    stage.draggable(!state.scaleMode);
    objLayer.find((n) => !!n.getAttr("meta")).forEach((n) => n.draggable(!state.scaleMode));
    renderScaleOverlay();
  }

  function forceStopAllDrags() {
    // HTML5-DnD verhindert normale mouseup/pointerup -> Konva kann in einem
    // internen "drag pending"-Zustand hängen. Wir feuern einen synthetischen
    // Mouseup-Event und stoppen alle aktiven Konva-Drags hart.
    try {
      const up = new MouseEvent("mouseup", { bubbles: true, cancelable: true });
      window.dispatchEvent(up);
      document.dispatchEvent(up);
      stage.container().dispatchEvent(up);
    } catch (_) { /* older browsers */ }
    try {
      if (Konva.DD && typeof Konva.DD._endDragBefore === "function") {
        Konva.DD._endDragBefore();
      }
      if (Konva.DD) {
        if (Konva.DD.node && typeof Konva.DD.node.stopDrag === "function") {
          Konva.DD.node.stopDrag();
        }
        Konva.DD.isDragging = false;
        Konva.DD.node = null;
      }
    } catch (_) { /* api shift between konva versions */ }
    if (typeof stage.stopDrag === "function" && stage.isDragging && stage.isDragging()) {
      stage.stopDrag();
    }
    objLayer.find((n) => !!n.getAttr && n.getAttr("meta")).forEach((n) => {
      if (typeof n.isDragging === "function" && n.isDragging()) {
        n.stopDrag();
      }
    });
  }

  // ---------------------------------------------------------------------
  // Legende
  // ---------------------------------------------------------------------
  function refreshLegend() {
    const stands = state.objects.filter((o) => o.type === "stand");
    if (!stands.length) {
      ui.legendContent.innerHTML = '<p class="small text-muted mb-0">Keine Objekte platziert.</p>';
      return;
    }
    ui.legendContent.innerHTML = "";
    stands.forEach((stand, idx) => {
      const color = (stand.color || "#cccccc").toLowerCase();
      const name = stand.custom_stand_name || stand.stand_name || `Stand ${idx + 1}`;
      const row = document.createElement("div");
      row.className = "d-flex align-items-center gap-2 mb-1 small";
      row.innerHTML = `<span class="legend-swatch" style="background:${color}"></span><span>${name}</span>`;
      ui.legendContent.appendChild(row);
    });
  }

  // ---------------------------------------------------------------------
  // Zoom / Viewport
  // ---------------------------------------------------------------------
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

  function fitToViewport() {
    if (!state.floorPlanImageObj) return;
    const w = state.floorPlanImageObj.width();
    const h = state.floorPlanImageObj.height();
    if (!w || !h) return;
    const scale = Math.min(stage.width() / w, stage.height() / h) * 0.98;
    stage.scale({ x: scale, y: scale });
    stage.position({
      x: (stage.width() - w * scale) / 2,
      y: (stage.height() - h * scale) / 2,
    });
    stage.batchDraw();
  }

  // ---------------------------------------------------------------------
  // Plan laden / hochladen
  // ---------------------------------------------------------------------
  function populateStandsSelect() {
    ui.objectStandIdSelect.innerHTML = '<option value="">Stand wählen…</option>';
    for (const stand of state.availableStands) {
      const opt = document.createElement("option");
      opt.value = String(stand.id);
      opt.textContent = stand.name;
      ui.objectStandIdSelect.appendChild(opt);
    }
  }

  async function fetchActivePlan() {
    try {
      const response = await fetch(api.getActivePlan);
      if (response.status === 404) {
        ui.currentPlanInfo.textContent = "Kein aktiver Plan";
        ui.stageEmptyState.classList.remove("d-none");
        return;
      }
      const data = await response.json();
      if (!data.success || !data.plan) {
        ui.currentPlanInfo.textContent = "Kein aktiver Plan";
        ui.stageEmptyState.classList.remove("d-none");
        return;
      }
      state.currentPlan = data.plan;
      state.objects = (data.objects || []).map((o) => ({ ...o, localId: String(o.id) }));
      state.availableStands = data.available_stands || [];
      populateStandsSelect();

      if (state.currentPlan.scale_point1_x != null && state.currentPlan.scale_point2_x != null) {
        state.scalePoints = [
          { x: Number(state.currentPlan.scale_point1_x), y: Number(state.currentPlan.scale_point1_y) },
          { x: Number(state.currentPlan.scale_point2_x), y: Number(state.currentPlan.scale_point2_y) },
        ];
        ui.scalePoint1Display.textContent = `(${state.scalePoints[0].x.toFixed(0)}, ${state.scalePoints[0].y.toFixed(0)})`;
        ui.scalePoint2Display.textContent = `(${state.scalePoints[1].x.toFixed(0)}, ${state.scalePoints[1].y.toFixed(0)})`;
        if (state.currentPlan.scale_distance_meters) {
          ui.scaleDistanceInput.value = state.currentPlan.scale_distance_meters;
        }
      } else {
        state.scalePoints = [];
        ui.scalePoint1Display.textContent = "–";
        ui.scalePoint2Display.textContent = "–";
      }
      ui.currentPlanInfo.textContent = `Aktueller Plan: ${state.currentPlan.name}`;
      ui.stageEmptyState.classList.add("d-none");

      Konva.Image.fromURL(state.currentPlan.image_url, (kImage) => {
        bgLayer.destroyChildren();
        kImage.setAttrs({ x: 0, y: 0, listening: false });
        state.floorPlanImageObj = kImage;
        bgLayer.add(kImage);
        bgLayer.batchDraw();
        fitToViewport();
        rebuildObjects();
        renderScaleOverlay();
        calculatePixelsPerMeter();
      });
    } catch (err) {
      toast("Konnte aktiven Plan nicht laden.", "danger");
    }
  }

  async function uploadPlan() {
    const file = ui.floorPlanUpload.files?.[0];
    if (!file) {
      toast("Bitte zuerst eine Datei auswählen.", "info");
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    ui.uploadPlanButton.disabled = true;
    ui.uploadPlanButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Lade hoch…';
    try {
      const response = await fetch(api.uploadPlan, { method: "POST", body: formData });
      const data = await response.json();
      if (!data.success) {
        toast(data.message || "Upload fehlgeschlagen.", "danger");
        return;
      }
      toast(data.message || "Plan hochgeladen.", "success");
      ui.floorPlanUpload.value = "";
      await fetchActivePlan();
    } catch (err) {
      toast("Upload fehlgeschlagen.", "danger");
    } finally {
      ui.uploadPlanButton.disabled = false;
      ui.uploadPlanButton.innerHTML = '<i class="bi bi-upload me-1"></i>Plan hochladen &amp; aktivieren';
    }
  }

  // ---------------------------------------------------------------------
  // Objekte erzeugen
  // ---------------------------------------------------------------------
  function defaultForType(type) {
    if (type === "stand") return { width: 80, height: 80 };
    if (type === "trash_can") return { width: 30, height: 30 };
    if (type === "power_outlet") return { width: 30, height: 30 };
    if (type === "wc") return { width: 28, height: 28 };
    return { width: 30, height: 30 };
  }

  function createObject(type, worldPoint) {
    if (!state.currentPlan) {
      toast("Bitte zuerst einen Lageplan hochladen.", "info");
      return;
    }
    const sizes = defaultForType(type);
    const obj = {
      id: null,
      localId: nextLocalId(),
      plan_id: state.currentPlan.id,
      type,
      x: worldPoint.x - sizes.width / 2,
      y: worldPoint.y - sizes.height / 2,
      width: sizes.width,
      height: sizes.height,
      color: type === "stand" ? "#cccccc" : null,
      trash_can_color: type === "trash_can" ? "yellow" : null,
      power_outlet_label: type === "power_outlet" ? "1" : null,
      wc_label: type === "wc" ? "WC" : null,
      stand_id: null,
      custom_stand_name: null,
      stand_name: "",
    };
    state.objects.push(obj);
    rebuildObjects();
    const added = objLayer.findOne((n) => n.getAttr && n.getAttr("meta")?.localId === obj.localId);
    if (added) {
      selectNode(added);
      scheduleSave(added);
    }
  }

  function stageToWorld(pointer) {
    const scale = stage.scaleX() || 1;
    return { x: (pointer.x - stage.x()) / scale, y: (pointer.y - stage.y()) / scale };
  }

  function clientToStagePoint(clientX, clientY) {
    const rect = stage.container().getBoundingClientRect();
    if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
      return null;
    }
    return { x: clientX - rect.left, y: clientY - rect.top };
  }

  // ---------------------------------------------------------------------
  // Place-Modus (anstatt HTML5-Drag&Drop, um Sticky-Objekt-Probleme zu verhindern)
  // ---------------------------------------------------------------------
  function setPlaceMode(type) {
    if (state.scaleMode) {
      toast("Maßstab-Modus ist aktiv – bitte zuerst deaktivieren.", "info");
      return;
    }
    // Gleicher Toolbox-Item zweimal = abbrechen
    if (state.placeType === type) {
      cancelPlaceMode();
      return;
    }
    state.placeType = type;
    stageContainer.classList.add("place-mode");
    document.querySelectorAll(".toolbox-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.objectType === type);
    });
    toast("Klicken Sie auf den Plan, um das Objekt zu platzieren. Esc zum Abbrechen.", "info", 4000);
  }

  function cancelPlaceMode() {
    state.placeType = null;
    stageContainer.classList.remove("place-mode");
    document.querySelectorAll(".toolbox-item").forEach((el) => el.classList.remove("active"));
  }

  // ---------------------------------------------------------------------
  // Event-Bindings
  // ---------------------------------------------------------------------
  function bindEvents() {
    ui.uploadPlanButton.addEventListener("click", uploadPlan);

    document.querySelectorAll(".toolbox-item").forEach((item) => {
      // Explizit kein draggable=true, HTML5-DnD stört Konvas Drag-System.
      item.removeAttribute("draggable");
      item.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        if (!state.currentPlan) return;
        state.toolboxDrag = {
          type: item.dataset.objectType,
          startX: e.clientX,
          startY: e.clientY,
          moved: false,
        };
        item.classList.add("active");
      });
      item.addEventListener("click", () => {
        if (Date.now() < state.suppressToolboxClickUntil) return;
        if (!state.currentPlan) {
          toast("Bitte zuerst einen Lageplan hochladen.", "info");
          return;
        }
        setPlaceMode(item.dataset.objectType);
      });
    });

    // Escape bricht Place-Modus ab.
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && state.placeType) {
        cancelPlaceMode();
        toast("Platzierung abgebrochen.", "info");
      }
    });

    window.addEventListener("pointermove", (e) => {
      const drag = state.toolboxDrag;
      if (!drag) return;
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      if (Math.hypot(dx, dy) > 5) drag.moved = true;
    });

    window.addEventListener("pointerup", (e) => {
      const drag = state.toolboxDrag;
      if (!drag) return;
      state.toolboxDrag = null;
      document.querySelectorAll(".toolbox-item").forEach((el) => el.classList.remove("active"));
      if (!drag.moved) return;
      const stagePoint = clientToStagePoint(e.clientX, e.clientY);
      if (!stagePoint) return;
      const worldPoint = stageToWorld(stagePoint);
      createObject(drag.type, worldPoint);
      state.suppressToolboxClickUntil = Date.now() + 250;
    });

    stage.on("click tap", (e) => {
      // Place-Modus: nur wenn auf Bild/Stage geklickt wird (nicht auf anderes Objekt)
      if (state.placeType && state.floorPlanImageObj && (e.target === stage || e.target === state.floorPlanImageObj)) {
        const pos = stageToWorld(stage.getPointerPosition());
        const type = state.placeType;
        cancelPlaceMode();
        createObject(type, pos);
        return;
      }
      if (state.scaleMode && state.floorPlanImageObj && (e.target === stage || e.target === state.floorPlanImageObj)) {
        const pos = stageToWorld(stage.getPointerPosition());
        if (state.scalePoints.length < 2) state.scalePoints.push(pos);
        else state.scalePoints = [pos];
        ui.scalePoint1Display.textContent = state.scalePoints[0]
          ? `(${state.scalePoints[0].x.toFixed(0)}, ${state.scalePoints[0].y.toFixed(0)})`
          : "–";
        ui.scalePoint2Display.textContent = state.scalePoints[1]
          ? `(${state.scalePoints[1].x.toFixed(0)}, ${state.scalePoints[1].y.toFixed(0)})`
          : "–";
        renderScaleOverlay();
        calculatePixelsPerMeter();
        return;
      }
      if (e.target === stage || e.target === state.floorPlanImageObj) {
        deselectNode();
      }
    });

    // Wheel-Zoom direkt an der Konva-Stage — zuverlässiger als am DIV-Container,
    // weil Konva den Zeiger-Zustand selbst verwaltet.
    stage.on("wheel", (e) => {
      e.evt.preventDefault();
      const factor = 1.08;
      const oldScale = stage.scaleX();
      const next = e.evt.deltaY < 0 ? oldScale * factor : oldScale / factor;
      const pointer = stage.getPointerPosition() || { x: stage.width() / 2, y: stage.height() / 2 };
      zoomAtPoint(Math.max(0.1, Math.min(6, next)), pointer);
      renderScaleOverlay();
    });
    // Browser-Scroll verhindern, wenn Maus über Canvas
    stageContainer.addEventListener("wheel", (e) => { e.preventDefault(); }, { passive: false });

    const stageCenter = () => ({ x: stage.width() / 2, y: stage.height() / 2 });
    ui.zoomInButton?.addEventListener("click", () => {
      zoomAtPoint(Math.min(6, stage.scaleX() * 1.15), stageCenter());
      renderScaleOverlay();
    });
    ui.zoomOutButton?.addEventListener("click", () => {
      zoomAtPoint(Math.max(0.1, stage.scaleX() / 1.15), stageCenter());
      renderScaleOverlay();
    });
    ui.fitViewButton?.addEventListener("click", () => {
      fitToViewport();
      renderScaleOverlay();
    });

    ui.toggleScaleModeButton.addEventListener("click", () => toggleScaleMode());
    ui.scaleDistanceInput.addEventListener("input", calculatePixelsPerMeter);
    ui.setScaleButton.addEventListener("click", async () => {
      if (!state.currentPlan || state.scalePoints.length !== 2) return;
      const ppm = calculatePixelsPerMeter();
      if (!ppm) return;
      const [p1, p2] = state.scalePoints;
      try {
        const response = await fetch(api.updateScale, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: state.currentPlan.id,
            scale_point1_x: p1.x,
            scale_point1_y: p1.y,
            scale_point2_x: p2.x,
            scale_point2_y: p2.y,
            scale_distance_meters: parseFloat(ui.scaleDistanceInput.value),
            width_px: state.floorPlanImageObj ? state.floorPlanImageObj.width() : 0,
            height_px: state.floorPlanImageObj ? state.floorPlanImageObj.height() : 0,
          }),
        });
        const data = await response.json();
        if (!data.success) {
          toast(data.message || "Maßstab konnte nicht gespeichert werden.", "danger");
          return;
        }
        if (data.pixels_per_meter) state.currentPlan.pixels_per_meter = data.pixels_per_meter;
        toast("Maßstab gespeichert.", "success");
        toggleScaleMode(false);
      } catch (err) {
        toast("Fehler beim Speichern des Maßstabs.", "danger");
      }
    });

    ui.saveObjectButton.addEventListener("click", () => {
      if (!state.selected) return;
      const meta = state.selected.getAttr("meta") || {};
      const node = state.selected;
      if (meta.type === "stand") {
        const w = metersToPx(ui.standWidthInput.value);
        const h = metersToPx(ui.standHeightInput.value);
        if (w > 0) node.width(w);
        if (h > 0) node.height(h);
        node.scaleX(1);
        node.scaleY(1);
        meta.width = node.width();
        meta.height = node.height();
        meta.color = ui.standColorInput.value;
        if (ui.useCustomStandNameCheckbox.checked) {
          meta.custom_stand_name = ui.standCustomNameInput.value || null;
          meta.stand_id = null;
          meta.stand_name = "";
        } else {
          meta.custom_stand_name = null;
          meta.stand_id = ui.objectStandIdSelect.value ? Number(ui.objectStandIdSelect.value) : null;
          const selected = state.availableStands.find((s) => Number(s.id) === Number(meta.stand_id));
          meta.stand_name = selected ? selected.name : "";
        }
        node.fill(meta.color);
      } else if (meta.type === "trash_can") {
        meta.trash_can_color = ui.trashCanColorSelect.value;
        node.fill(TRASH_COLOR_MAP[meta.trash_can_color] || TRASH_COLOR_MAP.yellow);
      } else if (meta.type === "power_outlet") {
        meta.power_outlet_label = ui.powerOutletLabelInput.value;
      } else if (meta.type === "wc") {
        meta.wc_label = ui.wcLabelInput.value || "WC";
      }
      node.setAttr("meta", meta);
      syncNodeVisual(node);
      objLayer.batchDraw();
      scheduleSave(node);
      refreshLegend();
      toast("Objekt gespeichert.", "success");
    });

    ui.deleteObjectButton.addEventListener("click", async () => {
      if (!state.selected) return;
      const meta = state.selected.getAttr("meta") || {};
      if (meta.id) {
        try {
          const response = await fetch(`${api.deleteObjectBase}/${meta.id}`, { method: "DELETE" });
          const data = await response.json();
          if (!data.success) {
            toast(data.message || "Löschen fehlgeschlagen.", "danger");
            return;
          }
        } catch (err) {
          toast("Löschen fehlgeschlagen.", "danger");
          return;
        }
      }
      state.objects = state.objects.filter((o) => {
        if (meta.id) return String(o.id) !== String(meta.id);
        return o.localId !== meta.localId;
      });
      deselectNode();
      rebuildObjects();
      toast("Objekt gelöscht.", "success");
    });

    ui.closePropertiesButton?.addEventListener("click", deselectNode);

    ui.useCustomStandNameCheckbox.addEventListener("change", () => {
      ui.standCustomNameInput.disabled = !ui.useCustomStandNameCheckbox.checked;
      ui.objectStandIdSelect.disabled = ui.useCustomStandNameCheckbox.checked;
    });

    function stopAllDrags() {
      objLayer.find((n) => !!n.getAttr && n.getAttr("meta")).forEach((n) => {
        forceStopNodeDrag(n);
      });
      if (typeof stage.isDragging === "function" && stage.isDragging()) stage.stopDrag();
    }
    window.addEventListener("mouseup", stopAllDrags);
    window.addEventListener("touchend", stopAllDrags);
    window.addEventListener("pointerup", stopAllDrags);

    window.addEventListener("resize", () => {
      resizeStageToContainer();
      fitToViewport();
    });
  }

  bindEvents();
  resizeStageToContainer();
  fetchActivePlan();
})();
