(function () {
  "use strict";

  const STORAGE_TUTORIAL = "armorygis_sim_tutorial_seen";
  let map = null;
  let launchMarker = null;
  let targetMarker = null;
  let rangeCircle = null;
  let rangeAzimuthLayer = null;
  let pathLayer = null;
  let baseLayer = null;
  let defenseCircle = null;
  let measureLayer = null;
  let measurePoints = [];
  let catalog = [];
  let catalogFiltered = [];
  let activeWeapon = null;
  let simCount = 0;
  let animTimer = null;
  let readinessTimer = null;
  let pendingWeapon = null;
  let pyBridge = null;
  let launchUndo = [];
  let measureMode = false;
  let tutorialStep = 0;
  let basemapMode = "dark";
  let simPhase = "idle";
  let swotReport = null;
  let swotEditor = null;
  let swotVisible = false;
  let layoutEditMode = false;
  const LAYOUT_STORAGE_KEY = "armorygis_sim_layout_v1";
  const LAYOUT_FS_STORAGE_KEY = "armorygis_sim_layout_fs_norm_v1";
  let simPrefsHydrated = false;
  let simPrefsReadyToPersist = false;
  let simUiHydrating = false;
  let persistTriggersWired = false;
  let persistTimer = null;
  let preFullscreenLayout = null;

  const SIM_SIDEBAR_HIDDEN_KEY = "armorygis_sim_sidebar_hidden_v1";

  const READINESS_SEC = 3.2;
  const basemaps = {
    dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    osm: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    sat: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  };
  const MISSING_TILE =
    "data:image/svg+xml," +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">' +
        '<rect width="256" height="256" fill="#1a2030"/>' +
        '<path d="M0 0 L256 256 M256 0 L0 256" stroke="#2e3648" stroke-width="1"/>' +
        "</svg>"
    );
  let offlineTilesEnabled = false;

  function normalizeBasemapKey(key) {
    const k = String(key || "dark").toLowerCase();
    if (k === "sat" || k === "satellite") return "satellite";
    if (k === "topo") return "topo";
    if (k === "osm") return "osm";
    return "dark";
  }

  function basemapSelectKey(key) {
    const k = normalizeBasemapKey(key);
    if (k === "satellite") return "sat";
    return k in basemaps ? k : "dark";
  }

  function canUseOfflineTiles() {
    return !!(offlineTilesEnabled && pyBridge && pyBridge.get_tile_data_uri);
  }

  function createCachedTileLayer(basemapKey) {
    const basemap = normalizeBasemapKey(basemapKey);
    const OfflineLayer = L.GridLayer.extend({
      createTile: function (coords, done) {
        const tile = document.createElement("img");
        tile.alt = "";
        tile.setAttribute("role", "presentation");
        tile.width = 256;
        tile.height = 256;
        if (!canUseOfflineTiles()) {
          tile.src = MISSING_TILE;
          done(null, tile);
          return tile;
        }
        pyBridge.get_tile_data_uri(basemap, coords.z, coords.x, coords.y, function (uri) {
          tile.src = uri || MISSING_TILE;
          done(null, tile);
        });
        return tile;
      },
    });
    return new OfflineLayer({
      attribution: "&copy; Offline cache",
      maxZoom: 19,
      tileSize: 256,
    });
  }

  function $(id) {
    return document.getElementById(id);
  }

  function panelFloatIds() {
    return {
      hud: true,
      statusStrip: true,
      aiSimBox: true,
      neonMissileTitle: true,
      simModelBox: true,
      btnPlayMap: true,
      btnTransferMainMap: true,
    };
  }

  function isFreeFloatPanel(el) {
    return !!(el && el.id && panelFloatIds()[el.id]);
  }

  function setHudText(txt) {
    const b = $("hudBody");
    if (b) {
      b.textContent = txt || "";
      return;
    }
    const h = $("hud");
    if (h) h.textContent = txt || "";
  }

  function setStatusStripText(txt) {
    const b = $("statusStripBody");
    if (b) {
      b.textContent = txt || "";
      return;
    }
    const s = $("statusStrip");
    if (s) s.textContent = txt || "";
  }

  function setNeonMissileTitleText(txt) {
    const b = $("neonMissileTitleBody");
    if (b) {
      b.textContent = txt || "";
      return;
    }
    const t = $("neonMissileTitle");
    if (t) t.textContent = txt || "";
  }

  function i18n(key, fallback) {
    const t = (window.__SIM_I18N && window.__SIM_I18N[key]) || fallback || key;
    return t;
  }

  function getPlaySpeed() {
    const el = $("playSpeed");
    const v = el ? Number(el.value) : 1;
    if (!v || v < 0.1) return 1;
    return v;
  }

  function clampPctTo01(id, defPct) {
    const el = $(id);
    const n = el ? Number(el.value) : defPct;
    const p = isNaN(n) ? defPct : n;
    return Math.max(0, Math.min(100, p)) / 100;
  }

  function clampLayoutGlassPct(n) {
    const x = Number(n);
    if (isNaN(x)) return 38;
    return Math.max(8, Math.min(55, Math.round(x)));
  }

  function applyLayoutGlassOpacityFromUi() {
    const el = $("simLayoutGlassOp");
    const pct = clampLayoutGlassPct(el ? el.value : 38);
    if (el && String(el.value) !== String(pct)) el.value = String(pct);
    const sp = $("simLayoutGlassOpVal");
    if (sp) sp.textContent = pct + "%";
    document.documentElement.style.setProperty("--sim-layout-glass-a", String(pct / 100));
  }

  function getMapLayerStyleFromUI() {
    return {
      rangeFill: ($("styleRangeFill") && $("styleRangeFill").value) || "#ff3d7a",
      rangeFillOp: clampPctTo01("styleRangeFillOp", 10),
      rangeOutline: ($("styleRangeOutline") && $("styleRangeOutline").value) || "#ff5e9a",
      rangeOutlineOp: clampPctTo01("styleRangeOutlineOp", 95),
      pathColor: ($("stylePathColor") && $("stylePathColor").value) || "#00fff2",
      pathOp: clampPctTo01("stylePathOp", 98),
    };
  }

  function rangeCircleStyleOpts() {
    const s = getMapLayerStyleFromUI();
    return {
      className: "armory-range-ring",
      color: s.rangeOutline,
      weight: 2.5,
      opacity: s.rangeOutlineOp,
      fillColor: s.rangeFill,
      fillOpacity: s.rangeFillOp,
    };
  }

  /** Great-circle destination from (lat, lon), bearing ° clockwise from north, distance km. */
  function geoDestinationKm(latDeg, lonDeg, bearingDeg, distanceKm) {
    const R = 6371;
    const δ = distanceKm / R;
    const θ = (bearingDeg * Math.PI) / 180;
    const φ1 = (latDeg * Math.PI) / 180;
    const λ1 = (lonDeg * Math.PI) / 180;
    const sinφ1 = Math.sin(φ1);
    const cosφ1 = Math.cos(φ1);
    const sinδ = Math.sin(δ);
    const cosδ = Math.cos(δ);
    const sinθ = Math.sin(θ);
    const cosθ = Math.cos(θ);
    const φ2 = Math.asin(sinφ1 * cosδ + cosφ1 * sinδ * cosθ);
    let λ2 = λ1 + Math.atan2(sinθ * sinδ * cosφ1, cosδ - sinφ1 * Math.sin(φ2));
    let lon2 = (λ2 * 180) / Math.PI;
    lon2 = ((lon2 + 540) % 360) - 180;
    return [(φ2 * 180) / Math.PI, lon2];
  }

  function clearRangeAzimuthLayer() {
    if (rangeAzimuthLayer && map) {
      map.removeLayer(rangeAzimuthLayer);
      rangeAzimuthLayer = null;
    }
  }

  function addAzimuthDecorations(layerGroup, centerLat, centerLon, radiusMeters, outlineColor) {
    const rKm = radiusMeters / 1000;
    if (!rKm || rKm <= 0) return;
    const step = 45;
    const tickKm = Math.min(Math.max(rKm * 0.035, 0.2), rKm * 0.12);
    const labelKm = Math.min(Math.max(rKm * 0.055, 0.35), rKm * 0.14);
    const col = outlineColor || "#ffffff";
    for (let b = 0; b < 360; b += step) {
      const outer = geoDestinationKm(centerLat, centerLon, b, rKm);
      const inner = geoDestinationKm(centerLat, centerLon, b, Math.max(0.001, rKm - tickKm));
      L.polyline([inner, outer], {
        color: col,
        weight: 2,
        opacity: 0.9,
        interactive: false,
      }).addTo(layerGroup);
      const lp = geoDestinationKm(centerLat, centerLon, b, rKm + labelKm);
      L.marker(lp, {
        icon: L.divIcon({
          className: "armory-azimuth-label",
          html: '<span>' + b + "°</span>",
          iconSize: [36, 18],
          iconAnchor: [18, 9],
        }),
        interactive: false,
        keyboard: false,
      }).addTo(layerGroup);
    }
  }

  function refreshRangeAzimuthDecorations() {
    clearRangeAzimuthLayer();
    if (!map || !rangeCircle || !activeWeapon) return;
    if (!$("visRangeAzimuth") || !$("visRangeAzimuth").checked) return;
    const lat = activeWeapon.origin_lat != null ? Number(activeWeapon.origin_lat) : 31.5;
    const lon = activeWeapon.origin_lon != null ? Number(activeWeapon.origin_lon) : 34.8;
    const rKm = activeWeapon.range_km != null ? Number(activeWeapon.range_km) : 100;
    const radiusM = Math.max(1000, rKm * 1000);
    const ro = getMapLayerStyleFromUI().rangeOutline || "#ff5e9a";
    rangeAzimuthLayer = L.layerGroup();
    addAzimuthDecorations(rangeAzimuthLayer, lat, lon, radiusM, ro);
    rangeAzimuthLayer.addTo(map);
  }

  function pathLineStyleOpts() {
    const s = getMapLayerStyleFromUI();
    const wEl = $("stylePathWeight");
    let weight = wEl ? Number(wEl.value) : 4;
    if (isNaN(weight) || weight < 1) weight = 4;
    weight = Math.min(24, Math.max(1, weight));
    const pattern = ($("stylePathDash") && $("stylePathDash").value) || "solid";
    let dashArray = null;
    let lineCap = "round";
    if (pattern === "dash") {
      dashArray = "12 10";
    } else if (pattern === "longdash") {
      dashArray = "26 18";
    } else if (pattern === "dots") {
      dashArray = "1 14";
      lineCap = "round";
    }
    const o = {
      className: "armory-route",
      color: s.pathColor,
      weight: weight,
      opacity: s.pathOp,
      lineCap: lineCap,
      lineJoin: "round",
    };
    if (dashArray) o.dashArray = dashArray;
    return o;
  }

  function translatePathStyleSelects() {
    const w = $("stylePathWeight");
    if (w) {
      for (let i = 0; i < w.options.length; i++) {
        const o = w.options[i];
        const px = o.value;
        o.textContent = px + " " + i18n("sim_style_px", "px");
      }
    }
    const d = $("stylePathDash");
    if (d && d.options.length >= 4) {
      d.options[0].text = i18n("sim_path_dash_solid", "Solid");
      d.options[1].text = i18n("sim_path_dash_short", "Dash");
      d.options[2].text = i18n("sim_path_dash_long", "Long dash");
      d.options[3].text = i18n("sim_path_dash_dots", "Round dots");
    }
  }

  function updateMapStyleValueLabels() {
    function one(idOp, idSpan) {
      const el = $(idOp);
      const sp = $(idSpan);
      if (el && sp) sp.textContent = Math.round(Number(el.value) || 0) + "%";
    }
    one("styleRangeFillOp", "styleRangeFillOpVal");
    one("styleRangeOutlineOp", "styleRangeOutlineOpVal");
    one("stylePathOp", "stylePathOpVal");
  }

  function applyLiveMapLayerStyle() {
    updateMapStyleValueLabels();
    const ro = rangeCircleStyleOpts();
    const po = pathLineStyleOpts();
    if (rangeCircle && typeof rangeCircle.setStyle === "function") {
      rangeCircle.setStyle({
        color: ro.color,
        opacity: ro.opacity,
        fillColor: ro.fillColor,
        fillOpacity: ro.fillOpacity,
        weight: ro.weight,
      });
    }
    if (pathLayer && typeof pathLayer.setStyle === "function") {
      const ps = {
        color: po.color,
        opacity: po.opacity,
        weight: po.weight,
        lineCap: po.lineCap,
        lineJoin: po.lineJoin,
      };
      // Leaflet keeps previous dashArray unless explicitly cleared to empty string.
      if (po.dashArray != null) ps.dashArray = po.dashArray;
      else ps.dashArray = "";
      pathLayer.setStyle(ps);
    }
    refreshRangeAzimuthDecorations();
  }

  function resetMapLayerStyleInputs() {
    const set = function (id, v) {
      const el = $(id);
      if (el) el.value = v;
    };
    set("styleRangeFillOp", "10");
    set("styleRangeOutlineOp", "95");
    set("stylePathOp", "98");
    set("styleRangeFill", "#ff3d7a");
    set("styleRangeOutline", "#ff5e9a");
    set("stylePathColor", "#00fff2");
    set("stylePathWeight", "4");
    set("stylePathDash", "solid");
    applyLiveMapLayerStyle();
    schedulePersistSimulatorUiSoon();
  }

  function wireMapLayerStyleControls() {
    const live = function () {
      applyLiveMapLayerStyle();
      schedulePersistSimulatorUiSoon();
    };
    ["styleRangeFillOp", "styleRangeOutlineOp", "stylePathOp"].forEach(function (id) {
      const el = $(id);
      if (el) el.addEventListener("input", live);
    });
    ["styleRangeFill", "styleRangeOutline", "stylePathColor"].forEach(function (id) {
      const el = $(id);
      if (el) el.addEventListener("input", live);
    });
    ["stylePathWeight", "stylePathDash"].forEach(function (id) {
      const el = $(id);
      if (el) el.addEventListener("change", live);
    });
    const btn = $("btnStyleReset");
    if (btn) btn.onclick = resetMapLayerStyleInputs;
    updateMapStyleValueLabels();
    translatePathStyleSelects();
  }

  const ARMORY_SVG_LAUNCH =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 56" fill="none">' +
    '<path d="M28 4 L50 16 V40 L28 52 L6 40 V16 Z" stroke="#39ff9c" stroke-width="2" fill="rgba(0,42,30,0.58)"/>' +
    '<path d="M28 12 L40 22 L32 22 L32 38 L24 38 L24 22 L16 22 Z" fill="#7dffb3" stroke="#39ff9c" stroke-width="1.1"/>' +
    "</svg>";

  const ARMORY_SVG_TARGET =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 56" fill="none">' +
    '<circle cx="28" cy="28" r="24" stroke="#ff9911" stroke-width="2.2" fill="rgba(45,22,0,0.42)"/>' +
    '<circle cx="28" cy="28" r="12" stroke="#ffcc44" stroke-width="1.6"/>' +
    '<circle cx="28" cy="28" r="4.5" fill="#ff7700" stroke="#ffcc66" stroke-width="0.8"/>' +
    '<line x1="28" y1="3" x2="28" y2="13" stroke="#ffaa22" stroke-width="2.8" stroke-linecap="square"/>' +
    '<line x1="28" y1="43" x2="28" y2="53" stroke="#ffaa22" stroke-width="2.8" stroke-linecap="square"/>' +
    '<line x1="3" y1="28" x2="13" y2="28" stroke="#ffaa22" stroke-width="2.8" stroke-linecap="square"/>' +
    '<line x1="43" y1="28" x2="53" y2="28" stroke="#ffaa22" stroke-width="2.8" stroke-linecap="square"/>' +
    "</svg>";

  function launchArmyIcon() {
    return L.divIcon({
      className: "armory-div-icon armory-marker-launch",
      html: '<div class="armory-marker-svg">' + ARMORY_SVG_LAUNCH + "</div>",
      iconSize: [48, 48],
      iconAnchor: [24, 24],
    });
  }

  function targetArmyIcon() {
    return L.divIcon({
      className: "armory-div-icon armory-marker-target",
      html: '<div class="armory-marker-svg">' + ARMORY_SVG_TARGET + "</div>",
      iconSize: [48, 48],
      iconAnchor: [24, 24],
    });
  }

  function applyLocale() {
    document.documentElement.setAttribute("dir", window.__SIM_RTL ? "rtl" : "ltr");
    document.documentElement.setAttribute("lang", window.__SIM_RTL ? "ar" : "en");
    document.body.setAttribute("dir", window.__SIM_RTL ? "rtl" : "ltr");
    const m = {
      i18n_title: "sim_title",
      i18n_subtitle: "sim_subtitle",
      simStyleSummary: "sim_style_summary",
      lbl_style_range_ring: "sim_style_range_ring",
      lbl_style_fill_op: "sim_style_fill_op",
      lbl_style_fill_color: "sim_style_fill_color",
      lbl_style_outline_op: "sim_style_outline_op",
      lbl_style_outline_color: "sim_style_outline_color",
      lbl_style_path_group: "sim_style_path_group",
      lbl_style_path_op: "sim_style_path_op",
      lbl_style_path_color: "sim_style_path_color",
      lbl_style_path_weight: "sim_style_path_weight",
      lbl_style_path_dash: "sim_style_path_dash",
      btnStyleReset: "sim_style_reset",
      lbl_search: "sim_search_label",
      lbl_weapon: "sim_weapon_system",
      weaponSearch: "sim_search_ph",
      lbl_basemap: "sim_basemap",
      lbl_flight: "sim_flight_profile",
      lbl_arc: "sim_arc_style",
      lbl_play_speed: "sim_play_speed",
      lbl_quickzoom: "sim_quick_zoom",
      btnPlayLabel: "sim_play",
      btnPlayMapLabel: "sim_play",
      btnLabels: "sim_labels_off",
      btnMeasure: "sim_measure",
      btnUndoLaunch: "sim_undo_launch",
      btnResetTarget: "sim_reset_target",
      btnExport: "sim_export_png",
      btnOpenMap: "sim_open_main_map",
      btnFullscreenLabel: "sim_fullscreen_enter",
      btnLoadAll: "sim_load_full_catalog",
      lbl_defense: "sim_defense_layer",
      lbl_hc: "sim_high_contrast",
      i18n_map_hint: "sim_map_hint",
      i18n_legend_title: "sim_legend_title",
      tut_title: "sim_tutorial_welcome",
      tut_body: "sim_tutorial_intro",
      btnTutorialSkip: "sim_tutorial_skip",
      btnTutorialNext: "sim_tutorial_next",
      help_title: "sim_help_title",
      help_body: "sim_help_keys",
      btnHelpClose: "sim_tutorial_done",
      neonLblReadiness: "sim_neon_readiness",
      neonLblTime: "sim_neon_time",
      neonLblSpeed: "sim_neon_speed",
      neonLblDist: "sim_neon_dist",
      neonLblCoord: "sim_neon_position",
      simToolsSummary: "sim_tools_summary",
      lbl_swot_toggle: "sim_swot_toggle",
      lbl_sim_save: "sim_save_session",
      lbl_sim_load: "sim_load_session",
      lbl_sim_export: "sim_export_system",
      lbl_sim_components: "sim_components",
      lbl_vis_range_azimuth: "sim_comp_range_azimuth",
      lbl_vis_legend: "sim_comp_legend",
      lbl_vis_hud: "sim_comp_hud",
      lbl_vis_status: "sim_comp_status",
      lbl_vis_telemetry: "sim_comp_telemetry",
      lbl_vis_title: "sim_comp_title",
      lbl_vis_zoom: "sim_comp_zoom",
      lbl_vis_help: "sim_comp_help",
      lbl_vis_ai: "sim_comp_ai",
      lbl_vis_swot: "sim_comp_swot",
      lbl_vis_model3d: "sim_comp_model3d",
      simModelHead: "sim_comp_model3d",
      swotTitle: "sim_swot_title",
      swotKNet: "sim_swot_net",
      swotKWeighted: "sim_swot_weighted",
      swotKUpdated: "sim_swot_updated",
      lbl_sim_swot_panel_glass: "sim_swot_panel_glass",
      lbl_sim_layout_glass_op: "sim_layout_glass_op",
    };
    Object.keys(m).forEach(function (id) {
      const el = $(id);
      if (!el) return;
      if (el.tagName === "INPUT" && el.type === "search") {
        el.placeholder = i18n(m[id], el.placeholder);
      } else {
        el.textContent = i18n(m[id], el.textContent);
      }
    });
    const selBm = $("basemapSelect");
    if (selBm && selBm.options.length >= 3) {
      selBm.options[0].text = i18n("sim_bm_dark", "Dark");
      selBm.options[1].text = i18n("sim_bm_street", "Street");
      selBm.options[2].text = i18n("sim_bm_satellite", "Satellite");
    }
    const fp = $("flightProfile");
    if (fp && fp.options.length >= 2) {
      fp.options[0].text = i18n("sim_profile_low", fp.options[0].text);
      fp.options[1].text = i18n("sim_profile_high", fp.options[1].text);
    }
    const arc = $("arcStyle");
    if (arc && arc.options.length >= 3) {
      arc.options[0].text = i18n("sim_arc_ballistic", arc.options[0].text);
      arc.options[1].text = i18n("sim_arc_cruise", arc.options[1].text);
      arc.options[2].text = i18n("sim_arc_direct", arc.options[2].text);
    }
    $("leg_launch").innerHTML =
      '<span style="color:#ff5e9a;text-shadow:0 0 10px #ff3d7a,0 0 18px rgba(255,60,120,0.5)">●</span> ' +
      i18n("sim_legend_launch", "Launch / range");
    $("leg_target").innerHTML =
      '<span style="color:#ffe566;text-shadow:0 0 10px #ffc857,0 0 18px rgba(255,200,80,0.45)">●</span> ' +
      i18n("sim_legend_target", "Target");
    $("leg_path").innerHTML =
      '<span style="color:#00fff2;text-shadow:0 0 10px #00e8ff,0 0 20px rgba(0,240,255,0.5)">—</span> ' +
      i18n("sim_legend_path", "Path");
    translatePathStyleSelects();
    updateFullscreenButtonLabel();
    refreshLabelButton();
    updateHud();
    updateStats();
    renderWeapon3dModel();
    applyLayoutGlassOpacityFromUi();
    if ($("btnTransferMainMap"))
      $("btnTransferMainMap").title = i18n("sim_transfer_main_map", "Send scene to main map");
    if ($("btnTransferFromSwot"))
      $("btnTransferFromSwot").title = i18n("sim_transfer_main_map", "Send scene to main map");
    refreshSimSidebarToggleUi();
  }

  function loadSimSidebarHiddenPref() {
    try {
      return localStorage.getItem(SIM_SIDEBAR_HIDDEN_KEY) === "1";
    } catch (e) {
      return false;
    }
  }

  function saveSimSidebarHiddenPref(hidden) {
    try {
      localStorage.setItem(SIM_SIDEBAR_HIDDEN_KEY, hidden ? "1" : "0");
    } catch (e) {}
  }

  function refreshSimSidebarToggleUi() {
    const btn = $("btnSimMenuToggle");
    if (!btn) return;
    const hidden = document.body.classList.contains("sim-sidebar-hidden");
    btn.setAttribute("aria-expanded", hidden ? "false" : "true");
    btn.title = i18n(
      hidden ? "sim_sidebar_show_menu" : "sim_sidebar_hide_menu",
      hidden ? "Show simulator menu" : "Hide simulator menu"
    );
    const icon = btn.querySelector(".sim-sidebar-toggle-icon");
    if (icon) {
      icon.innerHTML = hidden
        ? '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"><path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        : '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"><path d="M15 18l-6-6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }
  }

  function applySimSidebarHidden(hidden) {
    document.body.classList.toggle("sim-sidebar-hidden", !!hidden);
    refreshSimSidebarToggleUi();
    setTimeout(function () {
      if (map && typeof map.invalidateSize === "function") map.invalidateSize(false);
    }, 350);
  }

  function wireSimSidebarToggle() {
    const btn = $("btnSimMenuToggle");
    if (!btn || btn.__wiredSimSidebar) return;
    btn.__wiredSimSidebar = true;
    applySimSidebarHidden(loadSimSidebarHiddenPref());
    btn.addEventListener("click", function () {
      const isHidden = document.body.classList.contains("sim-sidebar-hidden");
      const nextHidden = !isHidden;
      applySimSidebarHidden(nextHidden);
      saveSimSidebarHiddenPref(nextHidden);
    });
  }

  function setVisible(id, on) {
    const el = $(id);
    if (!el) return;
    el.classList.toggle("hidden", !on);
  }

  function applyComponentVisibility() {
    const legendOn = $("visLegend") ? !!$("visLegend").checked : true;
    const hudOn = $("visHud") ? !!$("visHud").checked : true;
    const statusOn = $("visStatus") ? !!$("visStatus").checked : true;
    const telOn = $("visTelemetry") ? !!$("visTelemetry").checked : true;
    const titleOn = $("visMissileTitle") ? !!$("visMissileTitle").checked : true;
    const zoomOn = $("visZoom") ? !!$("visZoom").checked : true;
    const helpOn = $("visHelp") ? !!$("visHelp").checked : true;
    const aiOn = $("visAiSim") ? !!$("visAiSim").checked : false;
    const swotOn = $("visSwot") ? !!$("visSwot").checked : false;
    const modelOn = $("visModel3d") ? !!$("visModel3d").checked : false;

    const legend = document.querySelector(".legend");
    if (legend) legend.classList.toggle("hidden", !legendOn);
    setVisible("hud", hudOn);
    setVisible("statusStrip", statusOn);
    setVisible("neonTelemetry", telOn);
    setVisible("neonMissileTitle", titleOn);
    const zb = document.querySelector(".zoom-bar");
    if (zb) zb.classList.toggle("hidden", !zoomOn);
    setVisible("btnHelp", helpOn);
    setVisible("aiSimBox", aiOn);
    setVisible("simModelBox", modelOn && !!(activeWeapon && activeWeapon.primary_model));

    swotVisible = swotOn;
    renderSwotOverlay();
  }

  function getBoxEls() {
    const ids = [
      "neonTelemetry",
      "swotOverlay",
      "legendBox",
      "hud",
      "statusStrip",
      "neonMissileTitle",
      "aiSimBox",
      "simModelBox",
      "zoomBar",
      "btnPlayMap",
      "btnTransferMainMap",
      "btnHelp",
    ];
    return ids
      .map(function (id) { return $(id); })
      .filter(Boolean);
  }

  function ensureBoxChrome(el) {
    if (!el) return;
    Array.from(el.querySelectorAll(".box-corner-toggle")).forEach(function (n) {
      n.remove();
    });
    const existingGrip = el.querySelector(".box-grip");
    if (existingGrip) {
      existingGrip.textContent = "";
      existingGrip.setAttribute("aria-label", i18n("sim_layout_drag_panel", "Move panel"));
    }
    el.classList.remove("layout-collapsed");

    if (el.__boxChrome) return;
    el.__boxChrome = true;
    el.style.position = el.style.position || "absolute";
    el.classList.add("layout-box");

    let grip = el.querySelector(".box-grip");
    let resize = el.querySelector(".box-resize");
    let wrap = el.querySelector(".layout-box-content");

    const wrapTag = el.tagName === "BUTTON" ? "span" : "div";
    if (!wrap) {
      wrap = document.createElement(wrapTag);
      wrap.className = "layout-box-content";
      const moving = [];
      Array.from(el.childNodes).forEach(function (n) {
        if (n.nodeType !== 1) {
          moving.push(n);
          return;
        }
        const cls = n.classList;
        if (
          cls.contains("box-grip") ||
          cls.contains("box-resize") ||
          cls.contains("box-corner-toggle")
        ) {
          return;
        }
        moving.push(n);
      });
      moving.forEach(function (n) {
        wrap.appendChild(n);
      });
    }

    if (!grip) {
      grip = document.createElement("div");
      grip.className = "box-grip";
      grip.setAttribute("aria-label", i18n("sim_layout_drag_panel", "Move panel"));
    }
    grip.textContent = "";

    if (!resize) {
      resize = document.createElement("div");
      resize.className = "box-resize";
    }

    el.appendChild(grip);
    el.appendChild(wrap);
    el.appendChild(resize);
  }

  function boxRectRelativeToWrap(el) {
    const wrap = $("map-wrap");
    const r = el.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return {
      left: r.left - w.left,
      top: r.top - w.top,
      width: r.width,
      height: r.height,
    };
  }

  /** Default AI panel size when layout has no stored width/height (matches applyFullscreenEdgeLayout). */
  function defaultAiSimBoxSizePx() {
    const wrap = $("map-wrap");
    const W = wrap ? wrap.clientWidth || 1200 : 1200;
    const H = wrap ? wrap.clientHeight || 800 : 800;
    const rightW = Math.min(420, Math.max(250, Math.round(W * 0.31)));
    const aiH = Math.min(280, Math.max(140, Math.round(H * 0.23)));
    return { width: rightW, height: aiH };
  }

  function applyBoxRect(el, rect) {
    if (!el || !rect) return;
    el.style.left = rect.left + "px";
    el.style.top = rect.top + "px";
    el.style.right = "auto";
    el.style.bottom = "auto";
    let rw = rect.width;
    let rh = rect.height;
    if (el.id === "aiSimBox") {
      const d = defaultAiSimBoxSizePx();
      if (rw == null || !Number.isFinite(Number(rw)) || Number(rw) <= 0) rw = d.width;
      else rw = Number(rw);
      let mh = rh;
      if (mh == null || !Number.isFinite(Number(mh)) || Number(mh) <= 0) mh = d.height;
      else mh = Number(mh);
      el.style.width = rw + "px";
      el.style.height = "";
      el.style.minHeight = Math.max(100, mh) + "px";
      return;
    }
    if (rw != null) el.style.width = rw + "px";
    if (rh != null) el.style.height = rh + "px";
  }

  function snapshotLayoutNormalized() {
    const wrap = $("map-wrap");
    if (!wrap) return {};
    const W = Math.max(1, wrap.clientWidth);
    const H = Math.max(1, wrap.clientHeight);
    const out = {};
    getBoxEls().forEach(function (el) {
      const id = el.getAttribute("data-box-id") || el.id;
      const r = boxRectRelativeToWrap(el);
      out[id] = {
        relLeft: r.left / W,
        relTop: r.top / H,
        relWidth: r.width / W,
        relHeight: r.height / H,
      };
    });
    return out;
  }

  function applyLayoutFromNormalized(norm) {
    if (!norm || typeof norm !== "object") return;
    const wrap = $("map-wrap");
    if (!wrap) return;
    const W = wrap.clientWidth || 1;
    const H = wrap.clientHeight || 1;
    Object.keys(norm).forEach(function (id) {
      const el = $(id);
      const n = norm[id];
      if (!el || !n || typeof n !== "object") return;
      let rw = n.relWidth != null ? Number(n.relWidth) * W : null;
      let rh = n.relHeight != null ? Number(n.relHeight) * H : null;
      if (id === "aiSimBox") {
        const d = defaultAiSimBoxSizePx();
        if (rw == null || !Number.isFinite(rw) || rw <= 0) rw = d.width;
        if (rh == null || !Number.isFinite(rh) || rh <= 0) rh = d.height;
      }
      applyBoxRect(el, {
        left: Number(n.relLeft) * W,
        top: Number(n.relTop) * H,
        width: rw,
        height: rh,
      });
    });
  }

  function saveFullscreenLayoutNormalized() {
    try {
      const norm = snapshotLayoutNormalized();
      localStorage.setItem(LAYOUT_FS_STORAGE_KEY, JSON.stringify(norm));
    } catch (e) {}
  }

  function loadFullscreenLayoutNormalized() {
    try {
      const raw = localStorage.getItem(LAYOUT_FS_STORAGE_KEY);
      if (!raw) return null;
      const st = JSON.parse(raw);
      return st && typeof st === "object" && Object.keys(st).length ? st : null;
    } catch (e) {
      return null;
    }
  }

  function applyFullscreenLayoutFromSavedOrDefault() {
    const saved = loadFullscreenLayoutNormalized();
    if (saved) {
      applyLayoutFromNormalized(saved);
    } else {
      applyFullscreenEdgeLayout();
    }
    if (map && typeof map.invalidateSize === "function") map.invalidateSize(false);
  }

  function loadLayoutFromStorage() {
    try {
      const raw = localStorage.getItem(LAYOUT_STORAGE_KEY);
      if (!raw) return;
      const st = JSON.parse(raw);
      if (!st || typeof st !== "object") return;
      Object.keys(st).forEach(function (id) {
        const el = $(id);
        if (el) applyBoxRect(el, st[id]);
      });
    } catch (e) {}
  }

  function saveLayoutToStorage() {
    try {
      if (isSimulatorMapFullscreen()) {
        saveFullscreenLayoutNormalized();
      } else {
        const out = {};
        getBoxEls().forEach(function (el) {
          const id = el.getAttribute("data-box-id") || el.id;
          const r = boxRectRelativeToWrap(el);
          out[id] = r;
        });
        localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(out));
      }
    } catch (e) {}
    if (!simUiHydrating && simPrefsReadyToPersist) schedulePersistSimulatorUiSoon();
  }

  function setLayoutEditMode(on) {
    layoutEditMode = !!on;
    document.body.classList.toggle("layout-edit", layoutEditMode);
    // Disable map interactions while editing to avoid fighting drag/zoom.
    if (map) {
      if (layoutEditMode) {
        try { map.dragging.disable(); } catch (e) {}
        try { map.scrollWheelZoom.disable(); } catch (e) {}
        try { map.doubleClickZoom.disable(); } catch (e) {}
      } else {
        try { map.dragging.enable(); } catch (e) {}
        try { map.scrollWheelZoom.enable(); } catch (e) {}
        try { map.doubleClickZoom.enable(); } catch (e) {}
      }
    }
    getBoxEls().forEach(function (el) {
      ensureBoxChrome(el);
      el.classList.toggle("layout-outline", layoutEditMode);
    });
  }

  function toggleLayoutEditMode() {
    const entering = !layoutEditMode;
    setLayoutEditMode(entering);
    if (!entering) {
      saveLayoutToStorage();
      schedulePersistSimulatorUiSoon(true);
    }
  }

  function wireDragResize() {
    const wrap = $("map-wrap");
    if (!wrap) return;
    getBoxEls().forEach(function (el) {
      ensureBoxChrome(el);
      if (el.__wiredDragResize) return;
      el.__wiredDragResize = true;
      let mode = null; // "drag" | "resize"
      let startX = 0, startY = 0;
      let startRect = null;

      function onDown(ev) {
        const t = ev.target;
        const isResize = !!t.closest(".box-resize");
        const isGrip = !!t.closest(".box-grip");
        if (!layoutEditMode && isFreeFloatPanel(el)) {
          if (!isResize && !isGrip) return;
        } else if (!layoutEditMode) {
          return;
        }
        mode = isResize ? "resize" : "drag";
        startX = ev.clientX;
        startY = ev.clientY;
        startRect = boxRectRelativeToWrap(el);
        try { el.setPointerCapture(ev.pointerId); } catch (e) {}
        ev.preventDefault();
        ev.stopPropagation();
      }

      function onMove(ev) {
        if (!mode || !startRect) return;
        if (!layoutEditMode && !isFreeFloatPanel(el)) return;
        const dx = ev.clientX - startX;
        const dy = ev.clientY - startY;
        const wrapRect = wrap.getBoundingClientRect();
        let left = startRect.left;
        let top = startRect.top;
        let width = startRect.width;
        let height = startRect.height;

        if (mode === "drag") {
          left = startRect.left + dx;
          top = startRect.top + dy;
        } else {
          if (el.id === "aiSimBox") return;
          width = Math.max(140, startRect.width + dx);
          height = Math.max(40, startRect.height + dy);
          if (el.id === "btnHelp") {
            width = Math.max(38, startRect.width + dx);
            height = Math.max(38, startRect.height + dy);
          }
        }

        // Clamp inside map-wrap bounds.
        left = Math.max(0, Math.min(left, wrapRect.width - 40));
        top = Math.max(0, Math.min(top, wrapRect.height - 40));
        if (width) width = Math.min(width, wrapRect.width - left);
        if (height) height = Math.min(height, wrapRect.height - top);

        applyBoxRect(el, { left: left, top: top, width: width, height: height });
        if (map && typeof map.invalidateSize === "function") map.invalidateSize(false);
        ev.preventDefault();
        ev.stopPropagation();
      }

      function onUp(ev) {
        if (!mode) return;
        mode = null;
        startRect = null;
        saveLayoutToStorage();
        ev.preventDefault();
        ev.stopPropagation();
      }

      el.addEventListener("pointerdown", onDown, { passive: false });
      el.addEventListener("pointermove", onMove, { passive: false });
      el.addEventListener("pointerup", onUp, { passive: false });
      el.addEventListener("pointercancel", onUp, { passive: false });
    });
  }

  function toggleSwotOverlay() {
    const cb = $("visSwot");
    if (cb) cb.checked = !cb.checked;
    applyComponentVisibility();
  }

  function fmtDate(ts) {
    if (!ts) return "—";
    try {
      const d = new Date(ts);
      if (!isNaN(d.getTime())) return d.toLocaleString();
    } catch (e) {}
    return String(ts);
  }

  function renderSwotOverlay() {
    const box = $("swotOverlay");
    if (!box) return;
    if (!swotVisible || (!swotReport && !swotEditor)) {
      box.classList.add("hidden");
      return;
    }

    const summary = swotReport && swotReport.score_summary ? swotReport.score_summary : {};
    $("swotNet").textContent = summary && summary.net_score != null ? String(summary.net_score) : "—";
    $("swotWeighted").textContent = summary && summary.weighted_net_score != null ? String(summary.weighted_net_score) : "—";
    $("swotUpdated").textContent = fmtDate((swotReport && (swotReport.created_at || swotReport.createdAt || swotReport.created)) || "");

    function listToText(x) {
      if (!x) return "";
      if (Array.isArray(x)) {
        return x
          .map(function (s) {
            const t = String(s || "").trim();
            return t ? "- " + t : "";
          })
          .filter(Boolean)
          .join("\n");
      }
      return String(x);
    }

    // Prefer live editor text if available (even unsaved).
    const src = swotEditor || swotReport || {};
    $("swotStrengths").textContent = listToText(src.strengths) || "—";
    $("swotWeaknesses").textContent = listToText(src.weaknesses) || "—";
    $("swotOpportunities").textContent = listToText(src.opportunities) || "—";
    $("swotThreats").textContent = listToText(src.threats) || "—";
    $("swotRecs").textContent = (src.recommendations && String(src.recommendations).trim()) || "—";

    box.classList.remove("hidden");
  }

  function gatherState() {
    const st = {
      version: 1,
      weapon_id: activeWeapon ? activeWeapon.id : null,
      weapon_name: activeWeapon ? activeWeapon.weapon_name : null,
      model: activeWeapon ? activeWeapon.model : null,
      range_km: activeWeapon ? activeWeapon.range_km : null,
      basemap: basemapMode,
      arcStyle: $("arcStyle") ? $("arcStyle").value : null,
      flightProfile: $("flightProfile") ? $("flightProfile").value : null,
      playSpeed: $("playSpeed") ? Number($("playSpeed").value) : 1,
      defenseOn: $("chkDefense") ? !!$("chkDefense").checked : false,
      highContrast: $("chkHC") ? !!$("chkHC").checked : false,
      styles: {
        rangeFillOp: $("styleRangeFillOp") ? Number($("styleRangeFillOp").value) : 10,
        rangeOutlineOp: $("styleRangeOutlineOp") ? Number($("styleRangeOutlineOp").value) : 95,
        pathOp: $("stylePathOp") ? Number($("stylePathOp").value) : 98,
        rangeFill: $("styleRangeFill") ? $("styleRangeFill").value : "#ff3d7a",
        rangeOutline: $("styleRangeOutline") ? $("styleRangeOutline").value : "#ff5e9a",
        pathColor: $("stylePathColor") ? $("stylePathColor").value : "#00fff2",
        pathWeight: $("stylePathWeight") ? $("stylePathWeight").value : "4",
        pathDash: $("stylePathDash") ? $("stylePathDash").value : "solid",
        layoutGlassOp: $("simLayoutGlassOp") ? clampLayoutGlassPct($("simLayoutGlassOp").value) : 38,
      },
      visibility: {
        legend: $("visLegend") ? !!$("visLegend").checked : true,
        hud: $("visHud") ? !!$("visHud").checked : true,
        status: $("visStatus") ? !!$("visStatus").checked : true,
        telemetry: $("visTelemetry") ? !!$("visTelemetry").checked : true,
        title: $("visMissileTitle") ? !!$("visMissileTitle").checked : true,
        zoom: $("visZoom") ? !!$("visZoom").checked : true,
        help: $("visHelp") ? !!$("visHelp").checked : true,
        ai: $("visAiSim") ? !!$("visAiSim").checked : false,
        swot: $("visSwot") ? !!$("visSwot").checked : false,
        model3d: $("visModel3d") ? !!$("visModel3d").checked : false,
        rangeAzimuth: $("visRangeAzimuth") ? !!$("visRangeAzimuth").checked : false,
      },
      layout: (function () {
        const out = {};
        getBoxEls().forEach(function (el) {
          const id = el.getAttribute("data-box-id") || el.id;
          const r = boxRectRelativeToWrap(el);
          out[id] = r;
        });
        return out;
      })(),
    };
    if (launchMarker) {
      const p = launchMarker.getLatLng();
      st.launch = { lat: p.lat, lon: p.lng };
    }
    if (targetMarker) {
      const p = targetMarker.getLatLng();
      st.target = { lat: p.lat, lon: p.lng };
    }
    if ($("exportFormat")) st.exportFormat = $("exportFormat").value || "png";
    if (map) {
      var c = map.getCenter();
      st.mapView = { lat: c.lat, lng: c.lng, zoom: map.getZoom() };
    }
    return st;
  }

  function gatherPersistableUiPrefs() {
    try {
      const st = gatherState();
      delete st.version;
      delete st.weapon_id;
      delete st.weapon_name;
      delete st.model;
      delete st.range_km;
      delete st.launch;
      delete st.target;
      st.persistUiVersion = 2;
      return st;
    } catch (e) {
      return { persistUiVersion: 2 };
    }
  }

  function schedulePersistSimulatorUiSoon(immediate) {
    if (!simPrefsReadyToPersist) return;
    if (!pyBridge || !pyBridge.save_simulator_ui_state) return;
    if (simUiHydrating) return;
    if (isSimulatorMapFullscreen()) return;
    if (persistTimer != null) clearTimeout(persistTimer);
    if (immediate === true) {
      persistTimer = null;
      try {
        pyBridge.save_simulator_ui_state(JSON.stringify(gatherPersistableUiPrefs()));
      } catch (e) {}
      return;
    }
    persistTimer = setTimeout(function () {
      persistTimer = null;
      try {
        pyBridge.save_simulator_ui_state(JSON.stringify(gatherPersistableUiPrefs()));
      } catch (e2) {}
    }, 520);
  }

  function applySimulatorUiChrome(state, options) {
    if (!state || typeof state !== "object") return;
    options = options || {};
    if (options.applyMapView && state.mapView && map) {
      const mv = state.mapView;
      if (mv.lat != null && mv.lng != null && mv.zoom != null) {
        map.setView([Number(mv.lat), Number(mv.lng)], Number(mv.zoom), { animate: false });
      }
    }
    if ($("exportFormat") && state.exportFormat != null) $("exportFormat").value = String(state.exportFormat);
    if ($("basemapSelect") && state.basemap) {
      $("basemapSelect").value = state.basemap;
      setBasemap(state.basemap);
    }
    if ($("arcStyle") && state.arcStyle) $("arcStyle").value = state.arcStyle;
    if ($("flightProfile") && state.flightProfile) $("flightProfile").value = state.flightProfile;
    if ($("playSpeed") && state.playSpeed) $("playSpeed").value = String(state.playSpeed);
    if ($("chkDefense")) $("chkDefense").checked = !!state.defenseOn;
    if ($("chkHC")) $("chkHC").checked = !!state.highContrast;
    if ($("chkHC")) document.body.classList.toggle("sim-hc", $("chkHC").checked);

    if (state.styles) {
      const s = state.styles;
      if ($("styleRangeFillOp") && s.rangeFillOp != null) $("styleRangeFillOp").value = String(s.rangeFillOp);
      if ($("styleRangeOutlineOp") && s.rangeOutlineOp != null) $("styleRangeOutlineOp").value = String(s.rangeOutlineOp);
      if ($("stylePathOp") && s.pathOp != null) $("stylePathOp").value = String(s.pathOp);
      if ($("styleRangeFill") && s.rangeFill) $("styleRangeFill").value = s.rangeFill;
      if ($("styleRangeOutline") && s.rangeOutline) $("styleRangeOutline").value = s.rangeOutline;
      if ($("stylePathColor") && s.pathColor) $("stylePathColor").value = s.pathColor;
      if ($("stylePathWeight") && s.pathWeight) $("stylePathWeight").value = String(s.pathWeight);
      if ($("stylePathDash") && s.pathDash) $("stylePathDash").value = String(s.pathDash);
      if ($("simLayoutGlassOp") && s.layoutGlassOp != null)
        $("simLayoutGlassOp").value = String(clampLayoutGlassPct(s.layoutGlassOp));
      applyLiveMapLayerStyle();
      applyLayoutGlassOpacityFromUi();
    }

    if (state.visibility) {
      const v = state.visibility;
      if ($("visLegend") && v.legend != null) $("visLegend").checked = !!v.legend;
      if ($("visHud") && v.hud != null) $("visHud").checked = !!v.hud;
      if ($("visStatus") && v.status != null) $("visStatus").checked = !!v.status;
      if ($("visTelemetry") && v.telemetry != null) $("visTelemetry").checked = !!v.telemetry;
      if ($("visMissileTitle") && v.title != null) $("visMissileTitle").checked = !!v.title;
      if ($("visZoom") && v.zoom != null) $("visZoom").checked = !!v.zoom;
      if ($("visHelp") && v.help != null) $("visHelp").checked = !!v.help;
      if ($("visAiSim") && v.ai != null) $("visAiSim").checked = !!v.ai;
      if ($("visSwot") && v.swot != null) $("visSwot").checked = !!v.swot;
      if ($("visModel3d") && v.model3d != null) $("visModel3d").checked = !!v.model3d;
      if ($("visRangeAzimuth") && v.rangeAzimuth != null) $("visRangeAzimuth").checked = !!v.rangeAzimuth;
      applyComponentVisibility();
    }

    if (state.layout && typeof state.layout === "object" && !isSimulatorMapFullscreen()) {
      Object.keys(state.layout).forEach(function (id) {
        const el = $(id);
        if (el) applyBoxRect(el, state.layout[id]);
      });
      saveLayoutToStorage();
    }
    if (map && activeWeapon && rangeCircle) {
      refreshRangeAzimuthDecorations();
    }
  }

  function applyPersistedSimulatorPrefs(prefs) {
    applySimulatorUiChrome(prefs, { applyMapView: true });
    updateHud();
    updateStats();
  }

  function loadState(state) {
    if (!state || typeof state !== "object") return;
    applySimulatorUiChrome(state, { applyMapView: false });

    if (launchMarker && state.launch && state.launch.lat != null && state.launch.lon != null) {
      launchMarker.setLatLng([Number(state.launch.lat), Number(state.launch.lon)]);
    }
    if (targetMarker && state.target && state.target.lat != null && state.target.lon != null) {
      targetMarker.setLatLng([Number(state.target.lat), Number(state.target.lon)]);
      enforceTargetInRange();
    }
    if (state.mapView && map) {
      const mv = state.mapView;
      if (mv.lat != null && mv.lng != null && mv.zoom != null) {
        map.setView([Number(mv.lat), Number(mv.lng)], Number(mv.zoom), { animate: false });
      }
    }
    updateHud();
  }

  function exportSvgString() {
    const wrap = $("map-wrap");
    const w = wrap ? wrap.clientWidth : 800;
    const h = wrap ? wrap.clientHeight : 600;
    const svgEl = document.querySelector("#map .leaflet-overlay-pane svg");
    const overlay = svgEl ? svgEl.outerHTML : "";
    const bg = "<rect width=\"100%\" height=\"100%\" fill=\"rgba(0,0,0,0.0)\"/>";
    return (
      "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
      "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" +
      w +
      "\" height=\"" +
      h +
      "\" viewBox=\"0 0 " +
      w +
      " " +
      h +
      "\">" +
      bg +
      overlay +
      "</svg>"
    );
  }

  function ensureHtml2Canvas(cb) {
    if (typeof html2canvas !== "undefined") return cb(true);
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
    s.onload = function () { cb(true); };
    s.onerror = function () { cb(false); };
    document.head.appendChild(s);
  }

  function exportToSystem() {
    const fmt = $("exportFormat") ? $("exportFormat").value : "png";
    if (!pyBridge) return;
    const title = (activeWeapon && activeWeapon.weapon_name) ? activeWeapon.weapon_name : "armorygis-simulator";
    const suggestedBase = title.replace(/[\\\\/:*?\"<>|]+/g, "_");
    if (fmt === "pdf") {
      ensureHtml2Canvas(function (ok) {
        if (!ok) return;
        html2canvas($("map-wrap"), { useCORS: true, logging: false, scale: 1 }).then(function (canvas) {
          const png = canvas.toDataURL("image/png");
          const meta = {
            title: "ArmoryGIS Simulator Export",
            weapon_name: activeWeapon ? activeWeapon.weapon_name : null,
            timestamp: new Date().toISOString(),
          };
          pyBridge.export_pdf(suggestedBase + ".pdf", png, JSON.stringify(meta));
        });
      });
      return;
    }
    if (fmt === "svg") {
      const svg = exportSvgString();
      const dataUrl = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
      pyBridge.save_data_url(suggestedBase + ".svg", dataUrl);
      return;
    }
    if (fmt === "docx") {
      ensureHtml2Canvas(function (ok) {
        if (!ok) return;
        html2canvas($("map-wrap"), { useCORS: true, logging: false, scale: 1 }).then(function (canvas) {
          const png = canvas.toDataURL("image/png");
          const meta = {
            title: "ArmoryGIS Simulator Export",
            weapon_name: activeWeapon ? activeWeapon.weapon_name : null,
            timestamp: new Date().toISOString(),
          };
          pyBridge.export_docx(suggestedBase + ".docx", png, JSON.stringify(meta));
        });
      });
      return;
    }
    ensureHtml2Canvas(function (ok) {
      if (!ok) return;
      html2canvas($("map-wrap"), { useCORS: true, logging: false, scale: 1 }).then(function (canvas) {
        const url = fmt === "jpg" ? canvas.toDataURL("image/jpeg", 0.92) : canvas.toDataURL("image/png");
        pyBridge.save_data_url(suggestedBase + (fmt === "jpg" ? ".jpg" : ".png"), url);
      });
    });
  }

  function saveSessionToSystem() {
    if (!pyBridge) return;
    const st = gatherState();
    pyBridge.save_session(JSON.stringify(st));
  }

  function loadSessionFromSystem() {
    if (!pyBridge) return;
    pyBridge.load_session();
  }

  function showAiSimBox(text) {
    const box = $("aiSimBox");
    const t = $("aiSimText");
    if (!box || !t) return;
    t.textContent = String(text || "").trim() || "—";
    box.classList.remove("hidden");
  }

  function renderWeapon3dModel() {
    const stage = $("simModelStage");
    const empty = $("simModelEmpty");
    if (!stage || !empty) return;
    const existing = stage.querySelector("model-viewer");
    if (existing) existing.remove();
    const p = activeWeapon && activeWeapon.primary_model ? String(activeWeapon.primary_model).trim() : "";
    function normalizeModelSrc(pathValue) {
      if (!pathValue) return "";
      if (/^(https?:|file:|qrc:|data:)/i.test(pathValue)) return pathValue;
      const winAbs = /^[a-zA-Z]:[\\/]/.test(pathValue);
      if (winAbs) {
        return "file:///" + pathValue.replace(/\\/g, "/");
      }
      return pathValue;
    }
    if (!p) {
      empty.textContent = i18n("sim_model_no_file", "No 3D model available for selected weapon.");
      empty.classList.remove("hidden");
      applyComponentVisibility();
      return;
    }
    const mv = document.createElement("model-viewer");
    mv.setAttribute("src", normalizeModelSrc(p));
    mv.setAttribute("camera-controls", "");
    mv.setAttribute("auto-rotate", "");
    mv.setAttribute("shadow-intensity", "1");
    mv.setAttribute("exposure", "0.95");
    mv.setAttribute("interaction-prompt", "none");
    mv.style.width = "100%";
    mv.style.height = "100%";
    mv.addEventListener("error", function () {
      if (!mv.isConnected) return;
      mv.remove();
      empty.textContent = i18n("sim_model_load_failed", "3D model could not be loaded in simulator.");
      empty.classList.remove("hidden");
    });
    empty.classList.add("hidden");
    stage.appendChild(mv);
    mv.addEventListener("load", function () {
      requestAnimationFrame(function () {
        try {
          if (typeof mv.updateFraming === "function") mv.updateFraming();
        } catch (e) {}
        try {
          mv.dispatchEvent(new Event("resize"));
        } catch (e2) {}
      });
    });
    requestAnimationFrame(function () {
      try {
        if (typeof mv.updateFraming === "function") mv.updateFraming();
      } catch (e) {}
    });
    applyComponentVisibility();
  }

  function requestAiSimAnalysis() {
    if (!pyBridge || !pyBridge.request_sim_analysis) {
      showAiSimBox("AI bridge unavailable.");
      return;
    }
    const st = gatherState();
    showAiSimBox("Working…");
    try {
      pyBridge.request_sim_analysis(JSON.stringify(st));
    } catch (e) {
      showAiSimBox("AI request failed.");
    }
  }

  function setSwotReport(report) {
    swotReport = report || null;
    renderSwotOverlay();
  }

  function setSwotEditorText(payload) {
    swotEditor = payload || null;
    renderSwotOverlay();
  }

  function ensureLeaflet(cb) {
    if (typeof L !== "undefined") {
      cb(true);
      return;
    }
    const s = document.createElement("script");
    s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    s.onload = function () {
      cb(typeof L !== "undefined");
    };
    s.onerror = function () {
      cb(false);
    };
    document.head.appendChild(s);
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = ((lat2 - lat1) * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos((lat1 * Math.PI) / 180) *
        Math.cos((lat2 * Math.PI) / 180) *
        Math.sin(dLon / 2) *
        Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  /** Keep target on the great-circle segment from launch: distance ≤ rKm (meters modeled as km). */
  function clampTargetToRange(lat0, lon0, lat, lng, rKm) {
    const lim = Number(rKm);
    if (!lim || lim <= 0) return [lat, lng];
    const d = haversineKm(lat0, lon0, lat, lng);
    if (d <= lim) return [lat, lng];
    const frac = lim / d;
    return [lat0 + (lat - lat0) * frac, lon0 + (lng - lon0) * frac];
  }

  /** Published missile range (km); matches range ring (defaults to 100 if missing). */
  function weaponRangeKm() {
    if (!activeWeapon) return 0;
    const r = activeWeapon.range_km != null ? Number(activeWeapon.range_km) : 100;
    return r > 0 ? r : 100;
  }

  function launchPoint() {
    if (launchMarker) {
      const p = launchMarker.getLatLng();
      return { lat: p.lat, lng: p.lng };
    }
    const la = activeWeapon && activeWeapon.origin_lat != null ? Number(activeWeapon.origin_lat) : 31.5;
    const lo = activeWeapon && activeWeapon.origin_lon != null ? Number(activeWeapon.origin_lon) : 34.8;
    return { lat: la, lng: lo };
  }

  /** Move target marker inward if it exceeds current missile range from launch. */
  function enforceTargetInRange() {
    if (!targetMarker || !activeWeapon || !map) return;
    const rKm = weaponRangeKm();
    const o = launchPoint();
    const p = targetMarker.getLatLng();
    const c = clampTargetToRange(o.lat, o.lng, p.lat, p.lng, rKm);
    if (Math.abs(c[0] - p.lat) > 1e-7 || Math.abs(c[1] - p.lng) > 1e-7) {
      targetMarker.setLatLng(c);
    }
  }

  function buildArc(lat0, lon0, lat1, lon1, segments, style, flight) {
    const dist = haversineKm(lat0, lon0, lat1, lon1);
    if (dist < 0.5 || style === "direct") {
      const pts = [];
      for (let t = 0; t <= segments; t++) {
        const u = t / segments;
        pts.push([lat0 + u * (lat1 - lat0), lon0 + u * (lon1 - lon0)]);
      }
      return pts;
    }
    let bendFactor = style === "cruise" ? 0.45 : 1;
    const flightMul = flight === "high" ? 1.35 : 1;
    const midLat = (lat0 + lat1) / 2;
    const midLon = (lon0 + lon1) / 2;
    const bend = Math.min(3.5, Math.max(0.12, (dist / 100) * bendFactor * flightMul));
    const apex = [midLat + bend, midLon - bend * 0.28];
    const pts = [];
    for (let t = 0; t <= segments; t++) {
      const u = t / segments;
      const lat = (1 - u) * (1 - u) * lat0 + 2 * (1 - u) * u * apex[0] + u * u * lat1;
      const lon = (1 - u) * (1 - u) * lon0 + 2 * (1 - u) * u * apex[1] + u * u * lon1;
      pts.push([lat, lon]);
    }
    return pts;
  }

  function estMach() {
    const m = activeWeapon && activeWeapon.speed_mach != null ? Number(activeWeapon.speed_mach) : 3;
    return m > 0.2 ? m : 3;
  }

  function estTofHours(distKm) {
    const mach = estMach();
    const kmh = mach * 1225;
    const pathMul = $("arcStyle") && $("arcStyle").value === "direct" ? 1 : $("flightProfile") && $("flightProfile").value === "high" ? 1.22 : 1.05;
    return distKm / kmh * pathMul;
  }

  function pathLengthKm(pts) {
    if (!pts || pts.length < 2) return 0;
    let s = 0;
    for (let j = 1; j < pts.length; j++) {
      s += haversineKm(pts[j - 1][0], pts[j - 1][1], pts[j][0], pts[j][1]);
    }
    return s;
  }

  function distAlongPath(pts, endIndex) {
    if (!pts || endIndex < 1) return 0;
    let s = 0;
    const last = Math.min(endIndex, pts.length - 1);
    for (let j = 1; j <= last; j++) {
      s += haversineKm(pts[j - 1][0], pts[j - 1][1], pts[j][0], pts[j][1]);
    }
    return s;
  }

  function flightDurationSec(pathKm) {
    const mach = estMach();
    const kmh = mach * 1225;
    const pathMul =
      $("arcStyle") && $("arcStyle").value === "direct"
        ? 1
        : $("flightProfile") && $("flightProfile").value === "high"
          ? 1.18
          : 1.06;
    if (pathKm <= 0 || kmh <= 0) return 1;
    return ((pathKm * pathMul) / kmh) * 3600;
  }

  function instSpeedKmh(frac) {
    const base = estMach() * 1225;
    const boost = 0.55 + 0.45 * Math.sin(Math.min(1, frac * 3) * (Math.PI / 2));
    const cruise = 0.88 + 0.12 * Math.sin(frac * Math.PI);
    return base * boost * (0.65 + 0.35 * cruise);
  }

  function formatElapsed(sec) {
    if (sec >= 3600) {
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      return h + ":" + String(m).padStart(2, "0") + ":" + (sec % 60).toFixed(1).padStart(4, "0");
    }
    if (sec >= 60) {
      const m = Math.floor(sec / 60);
      return m + ":" + (sec % 60).toFixed(1).padStart(4, "0");
    }
    return sec.toFixed(2) + " s";
  }

  function setNeonVisible(on) {
    const tel = $("neonTelemetry");
    const tit = $("neonMissileTitle");
    if (tel) tel.classList.toggle("hidden", !on);
    if (tit) tit.classList.toggle("hidden", !on || !activeWeapon);
  }

  function updateNeonMissileTitle() {
    const tit = $("neonMissileTitle");
    if (!tit) return;
    if (!activeWeapon) {
      setNeonMissileTitleText("—");
      tit.classList.add("hidden");
      return;
    }
    const name = activeWeapon.weapon_name || "Weapon";
    const model = activeWeapon.model ? " · " + activeWeapon.model : "";
    setNeonMissileTitleText(name + model);
    tit.classList.remove("hidden");
  }

  function updateNeonIdle() {
    if (simPhase !== "idle") return;
    if (!activeWeapon || !map || !launchMarker) {
      setNeonVisible(false);
      return;
    }
    setNeonVisible(true);
    updateNeonMissileTitle();
    const p0 = launchMarker.getLatLng();
    let distStr = "0.0 km";
    let readiness = i18n("sim_neon_standby", "STANDBY — awaiting launch");
    if (targetMarker) {
      const p1 = targetMarker.getLatLng();
      const d = haversineKm(p0.lat, p0.lng, p1.lat, p1.lng);
      distStr = d.toFixed(2) + " km " + i18n("sim_neon_los", "LOS");
      const tEst = estTofHours(d);
      const tofStr =
        tEst < 1 / 60
          ? (tEst * 3600).toFixed(0) + " s"
          : (tEst * 60).toFixed(1) + " min";
      readiness =
        i18n("sim_neon_ready", "READY") +
        " · " +
        i18n("sim_neon_tof_preview", "est. TOF") +
        " " +
        tofStr;
    }
    const nom = estMach() * 1225;
    updateNeonReadout({
      readiness: readiness,
      time: "0.00 s",
      speed:
        nom.toFixed(0) +
        " km/h · M" +
        estMach().toFixed(2) +
        " (" +
        i18n("sim_neon_nominal", "nominal") +
        ")",
      dist: distStr,
      coord: p0.lat.toFixed(5) + " · " + p0.lng.toFixed(5),
    });
  }

  function updateNeonReadout(state) {
    const nr = $("neonReadiness");
    const nt = $("neonTime");
    const ns = $("neonSpeed");
    const nd = $("neonDist");
    const nc = $("neonCoord");
    if (!nr || !nt || !ns || !nd || !nc) return;
    if (!state) {
      nr.textContent = "—";
      nt.textContent = "—";
      ns.textContent = "—";
      nd.textContent = "—";
      nc.textContent = "—";
      return;
    }
    nr.textContent = state.readiness || "—";
    nt.textContent = state.time || "—";
    ns.textContent = state.speed || "—";
    nd.textContent = state.dist || "—";
    nc.textContent = state.coord || "—";
  }

  function clearFlightTimers() {
    if (animTimer) {
      clearInterval(animTimer);
      animTimer = null;
    }
    if (readinessTimer) {
      clearInterval(readinessTimer);
      readinessTimer = null;
    }
  }

  function updateDefense() {
    if (!map || !launchMarker || !$("chkDefense").checked) {
      if (defenseCircle && map) {
        map.removeLayer(defenseCircle);
        defenseCircle = null;
      }
      return;
    }
    const p = launchMarker.getLatLng();
    const lat = p.lat + 0.35;
    const lng = p.lng + 0.35;
    if (defenseCircle) map.removeLayer(defenseCircle);
    defenseCircle = L.circle([lat, lng], {
      radius: 55e3,
      className: "armory-defense",
      color: "#5dffc8",
      weight: 2.5,
      fillColor: "#3ed4a8",
      fillOpacity: 0.08,
      opacity: 0.92,
    }).addTo(map);
  }

  function updateHud() {
    if (!activeWeapon) {
      setHudText(i18n("sim_status_no_weapon", "No weapon loaded"));
      setStatusStripText("—");
      simPhase = "idle";
      setNeonVisible(false);
      updateNeonReadout(null);
      return;
    }
    const r = activeWeapon.range_km != null ? Number(activeWeapon.range_km) : 0;
    const la = activeWeapon.origin_lat != null ? Number(activeWeapon.origin_lat) : 31.5;
    const lo = activeWeapon.origin_lon != null ? Number(activeWeapon.origin_lon) : 34.8;
    const name = activeWeapon.weapon_name || "Weapon";
    const model = activeWeapon.model || "";
    setHudText(
      name +
      (model ? " (" + model + ")" : "") +
      " · " +
      i18n("sim_hud_range", "Range") +
      " " +
      (r || "?") +
      " km · " +
      i18n("sim_hud_launch", "Launch") +
      " " +
      la.toFixed(3) +
      ", " +
      lo.toFixed(3)
    );

    if (launchMarker && targetMarker) {
      const p0 = launchMarker.getLatLng();
      const p1 = targetMarker.getLatLng();
      const d = haversineKm(p0.lat, p0.lng, p1.lat, p1.lng);
      const rMax = weaponRangeKm();
      const inside = d <= rMax + 1e-5;
      const tof = estTofHours(d);
      const tofStr = tof < 1 / 60 ? (tof * 3600).toFixed(0) + " s est" : (tof * 60).toFixed(1) + " min est";
      setStatusStripText(
        i18n("sim_dist", "Distance") +
        ": " +
        d.toFixed(1) +
        " km · " +
        i18n("sim_tof_est", "TOF est") +
        ": " +
        tofStr +
        " · " +
        (inside ? i18n("sim_inside_range", "Inside range") : i18n("sim_outside_range", "Outside range"))
      );
    } else {
      setStatusStripText("—");
    }
    updateDefense();
    updateNeonIdle();
  }

  function updateStats() {
    const z = map ? map.getZoom() : "—";
    const lab = i18n("sim_stats", "Simulations");
    $("simStats").textContent =
      lab + ": " + simCount + " · " + i18n("sim_zoom", "Zoom") + ": " + z + "×";
  }

  function refreshLabelButton() {
    const btn = $("btnLabels");
    if (!btn) return;
    const on = basemapMode === "osm";
    btn.textContent = on ? i18n("sim_labels_on", "Labels ✓") : i18n("sim_labels_off", "Labels");
  }

  function setBasemap(key) {
    if (!map) return;
    basemapMode = key in basemaps ? key : "dark";
    if (baseLayer) map.removeLayer(baseLayer);
    if (canUseOfflineTiles()) {
      baseLayer = createCachedTileLayer(basemapMode).addTo(map);
    } else {
      const url = basemaps[basemapMode];
      baseLayer = L.tileLayer(url, { maxZoom: 19, attribution: "&copy; OSM/Carto/Esri" }).addTo(map);
    }
    baseLayer.bringToBack();
    const sel = $("basemapSelect");
    if (sel && sel.value !== basemapMode) sel.value = basemapMode;
    refreshLabelButton();
    schedulePersistSimulatorUiSoon();
  }

  function redrawRange() {
    if (!map || !activeWeapon) return;
    const lat = activeWeapon.origin_lat != null ? Number(activeWeapon.origin_lat) : 31.5;
    const lon = activeWeapon.origin_lon != null ? Number(activeWeapon.origin_lon) : 34.8;
    const rKm = activeWeapon.range_km != null ? Number(activeWeapon.range_km) : 100;
    clearRangeAzimuthLayer();
    if (rangeCircle) {
      map.removeLayer(rangeCircle);
      rangeCircle = null;
    }
    rangeCircle = L.circle(
      [lat, lon],
      Object.assign({ radius: Math.max(1000, rKm * 1000) }, rangeCircleStyleOpts())
    ).addTo(map);

    if (launchMarker) map.removeLayer(launchMarker);
    launchMarker = L.marker([lat, lon], {
      draggable: true,
      title: "Launch",
      icon: launchArmyIcon(),
    }).addTo(map);
    launchMarker.on("dragstart", function () {
      if (launchMarker) {
        const p = launchMarker.getLatLng();
        launchUndo.push({ lat: p.lat, lng: p.lng });
        if (launchUndo.length > 12) launchUndo.shift();
      }
    });
    launchMarker.on("dragend", function () {
      const p = launchMarker.getLatLng();
      activeWeapon.origin_lat = p.lat;
      activeWeapon.origin_lon = p.lng;
      redrawRange();
      updateHud();
      if (pyBridge && activeWeapon.id) {
        pyBridge.report_weapon_origin_moved(activeWeapon.id, p.lat, p.lng);
      }
    });

    if (!targetMarker) {
      const off = rKm > 0 ? Math.min(rKm * 0.35 / 111, 2) : 0.5;
      targetMarker = L.marker([lat + off, lon + off], {
        draggable: true,
        title: "Target",
        icon: targetArmyIcon(),
      }).addTo(map);
    } else {
      enforceTargetInRange();
    }
    targetMarker.off("drag");
    targetMarker.on("drag", function () {
      const o = launchPoint();
      const rK = weaponRangeKm();
      const p = targetMarker.getLatLng();
      const c = clampTargetToRange(o.lat, o.lng, p.lat, p.lng, rK);
      targetMarker.setLatLng(c);
    });
    targetMarker.on("dragend", function () {
      enforceTargetInRange();
      updateHud();
    });
    refreshRangeAzimuthDecorations();
    updateHud();
  }

  function onMapClick(e) {
    if (e.originalEvent && e.originalEvent.button !== 0) {
      return;
    }
    if (measureMode) {
      measurePoints.push(e.latlng);
      if (measurePoints.length >= 2) {
        if (measureLayer) map.removeLayer(measureLayer);
        measureLayer = L.polyline(
          [
            [measurePoints[0].lat, measurePoints[0].lng],
            [measurePoints[1].lat, measurePoints[1].lng],
          ],
          {
            className: "armory-measure",
            dashArray: "8 5",
            color: "#ffe566",
            weight: 3,
            opacity: 0.95,
            lineCap: "round",
            lineJoin: "round",
          }
        ).addTo(map);
        const d = haversineKm(
          measurePoints[0].lat,
          measurePoints[0].lng,
          measurePoints[1].lat,
          measurePoints[1].lng
        );
        setStatusStripText(i18n("sim_measure_hint", "Measure") + ": " + d.toFixed(2) + " km");
        measureMode = false;
        $("btnMeasure").classList.remove("active-toggle");
      }
      return;
    }
    if (!activeWeapon || !targetMarker) return;
    const o = launchPoint();
    const rKm = weaponRangeKm();
    let lat = e.latlng.lat;
    let lng = e.latlng.lng;
    const pair = clampTargetToRange(o.lat, o.lng, lat, lng, rKm);
    targetMarker.setLatLng(pair);
    updateHud();
  }

  function playSim() {
    if (!map || !activeWeapon || !launchMarker || !targetMarker) return;
    enforceTargetInRange();
    const rMax = weaponRangeKm();
    let p0 = launchMarker.getLatLng();
    let p1 = targetMarker.getLatLng();
    const sep = haversineKm(p0.lat, p0.lng, p1.lat, p1.lng);
    if (rMax > 0 && sep > rMax + 1e-4) {
      const c = clampTargetToRange(p0.lat, p0.lng, p1.lat, p1.lng, rMax);
      targetMarker.setLatLng(c);
    }
    p0 = launchMarker.getLatLng();
    p1 = targetMarker.getLatLng();
    clearFlightTimers();
    simPhase = "ready";
    if (pathLayer) {
      map.removeLayer(pathLayer);
      pathLayer = null;
    }
    const style = ($("arcStyle") && $("arcStyle").value) || "ballistic";
    const flight = ($("flightProfile") && $("flightProfile").value) || "low";
    const pts = buildArc(p0.lat, p0.lng, p1.lat, p1.lng, 72, style, flight);
    const pathKm = pathLengthKm(pts);
    const totalSec = Math.max(0.4, flightDurationSec(pathKm));

    setNeonVisible(true);
    updateNeonMissileTitle();

    const playSpeed = getPlaySpeed();
    const flightFrameMs = Math.max(8, Math.round(26 / playSpeed));
    const readinessTickMs = Math.max(16, Math.round(40 / playSpeed));

    const tStart = Date.now();
    readinessTimer = setInterval(function () {
      const simElapsed = ((Date.now() - tStart) / 1000) * playSpeed;
      const remain = READINESS_SEC - simElapsed;
      const pLaunch = launchMarker.getLatLng();
      if (remain > 0) {
        updateNeonReadout({
          readiness:
            i18n("sim_neon_armed", "ARMED") +
            " — " +
            i18n("sim_neon_tminus", "T−") +
            remain.toFixed(2) +
            " s",
          time: "0.00 s",
          speed: "0 km/h",
          dist: "0.0 km",
          coord: pLaunch.lat.toFixed(5) + " · " + pLaunch.lng.toFixed(5),
        });
        return;
      }
      clearInterval(readinessTimer);
      readinessTimer = null;
      updateNeonReadout({
        readiness: i18n("sim_neon_liftoff", "LIFTOFF"),
        time: "0.00 s",
        speed: instSpeedKmh(0).toFixed(0) + " km/h",
        dist: "0.0 km",
        coord: pLaunch.lat.toFixed(5) + " · " + pLaunch.lng.toFixed(5),
      });
      pathLayer = L.polyline([pts[0]], pathLineStyleOpts()).addTo(map);
      simPhase = "flight";
      let i = 0;
      animTimer = setInterval(function () {
        i += 2;
        const last = pts.length - 1;
        const idx = Math.min(i, last);
        const frac = last > 0 ? idx / last : 1;
        const elapsedF = frac * totalSec;
        const dist = distAlongPath(pts, idx);
        const lat = pts[idx][0];
        const lon = pts[idx][1];
        const sp = instSpeedKmh(frac);
        updateNeonReadout({
          readiness: i18n("sim_neon_in_flight", "IN FLIGHT"),
          time:
            formatElapsed(elapsedF) + " / " + formatElapsed(totalSec) + " (" + i18n("sim_neon_elapsed", "elapsed") + ")",
          speed: sp.toFixed(0) + " km/h · M" + (sp / 1225).toFixed(2),
          dist:
            dist.toFixed(2) +
            " / " +
            pathKm.toFixed(2) +
            " km (" +
            i18n("sim_neon_track", "track") +
            ")",
          coord: lat.toFixed(5) + " · " + lon.toFixed(5),
        });
        if (i >= pts.length) {
          clearInterval(animTimer);
          animTimer = null;
          pathLayer.setLatLngs(pts);
          simCount++;
          updateStats();
          updateNeonReadout({
            readiness: i18n("sim_neon_terminal", "TERMINAL"),
            time: formatElapsed(totalSec) + " (" + i18n("sim_neon_mission", "mission") + ")",
            speed: instSpeedKmh(1).toFixed(0) + " km/h",
            dist: pathKm.toFixed(2) + " km",
            coord: lat.toFixed(5) + " · " + lon.toFixed(5),
          });
          simPhase = "idle";
          return;
        }
        pathLayer.setLatLngs(pts.slice(0, idx + 1));
      }, flightFrameMs);
    }, readinessTickMs);
  }

  function toggleLabels() {
    if (basemapMode === "osm") setBasemap("dark");
    else setBasemap("osm");
  }

  function populateSelect() {
    const sel = $("weaponSelect");
    const q = ($("weaponSearch") && $("weaponSearch").value.toLowerCase()) || "";
    catalogFiltered = catalog.filter(function (w) {
      if (!q) return true;
      const n = (w.weapon_name || "") + " " + (w.model || "");
      return n.toLowerCase().indexOf(q) >= 0;
    });
    const cur = sel.value;
    sel.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = i18n("sim_select_weapon", "— Select weapon —");
    sel.appendChild(opt0);
    catalogFiltered.forEach(function (w) {
      const o = document.createElement("option");
      o.value = String(w.id);
      o.textContent = (w.weapon_name || "?") + " (" + (w.model || "-") + ")";
      sel.appendChild(o);
    });
    if (cur && catalogFiltered.some(function (x) { return String(x.id) === cur; })) {
      sel.value = cur;
    }
  }

  function applyWeapon(w) {
    if (!w || !w.id) return;
    clearFlightTimers();
    simPhase = "idle";
    // Clear leftover graphics from previous runs/weapon.
    if (map) {
      if (pathLayer) {
        map.removeLayer(pathLayer);
        pathLayer = null;
      }
      if (measureLayer) {
        map.removeLayer(measureLayer);
        measureLayer = null;
        measurePoints = [];
      }
      if (defenseCircle) {
        map.removeLayer(defenseCircle);
        defenseCircle = null;
      }
    }
    activeWeapon = {
      id: w.id,
      weapon_name: w.weapon_name || "",
      model: w.model || "",
      range_km: w.range_km != null ? Number(w.range_km) : 100,
      origin_lat: w.origin_lat != null ? Number(w.origin_lat) : 31.5,
      origin_lon: w.origin_lon != null ? Number(w.origin_lon) : 34.8,
      speed_mach: w.speed_mach != null ? Number(w.speed_mach) : null,
      primary_model: w.primary_model || "",
    };
    launchUndo = [];
    populateSelect();
    const sel = $("weaponSelect");
    sel.value = String(activeWeapon.id);
    if (map) {
      map.setView([activeWeapon.origin_lat, activeWeapon.origin_lon], Math.min(8, map.getZoom() || 6));
      if (targetMarker) {
        map.removeLayer(targetMarker);
        targetMarker = null;
      }
      redrawRange();
    }
    updateHud();
    renderWeapon3dModel();
  }

  function pickFromSelect() {
    const id = $("weaponSelect").value;
    if (!id) return;
    const w = catalog.find(function (x) {
      return String(x.id) === id;
    });
    if (w) applyWeapon(w);
  }

  function undoLaunch() {
    if (!launchMarker || !launchUndo.length) return;
    const prev = launchUndo.pop();
    launchMarker.setLatLng(prev);
    activeWeapon.origin_lat = prev.lat;
    activeWeapon.origin_lon = prev.lng;
    redrawRange();
    if (pyBridge && activeWeapon.id) {
      pyBridge.report_weapon_origin_moved(activeWeapon.id, prev.lat, prev.lng);
    }
  }

  function resetTarget() {
    if (!map || !activeWeapon || !launchMarker) return;
    const lat = activeWeapon.origin_lat != null ? Number(activeWeapon.origin_lat) : 31.5;
    const lon = activeWeapon.origin_lon != null ? Number(activeWeapon.origin_lon) : 34.8;
    const rKm = activeWeapon.range_km != null ? Number(activeWeapon.range_km) : 100;
    const off = rKm > 0 ? Math.min(rKm * 0.35 / 111, 2) : 0.5;
    if (!targetMarker) {
      targetMarker = L.marker([lat + off, lon + off], {
        draggable: true,
        icon: targetArmyIcon(),
      }).addTo(map);
    } else {
      targetMarker.setLatLng([lat + off, lon + off]);
    }
    updateHud();
  }

  function loadFullCatalog() {
    if (!pyBridge || !pyBridge.fetch_full_catalog) return;
    pyBridge.fetch_full_catalog(function (json) {
      try {
        const data = JSON.parse(json);
        if (Array.isArray(data)) {
          catalog = data;
          populateSelect();
        }
      } catch (e) {}
    });
  }

  function exportPng() {
    const wrap = $("map-wrap");
    if (!wrap) return;
    setStatusStripText(i18n("sim_export_busy", "Exporting…"));
    function runCanvas() {
      if (typeof html2canvas === "undefined") {
        setStatusStripText(i18n("sim_export_fail", "Export failed"));
        return;
      }
      html2canvas(wrap, { useCORS: true, logging: false, scale: 1 }).then(function (canvas) {
        const a = document.createElement("a");
        a.download = "armorygis-simulator.png";
        a.href = canvas.toDataURL("image/png");
        a.click();
        setStatusStripText(i18n("sim_export_ok", "Export complete"));
      }).catch(function () {
        setStatusStripText(i18n("sim_export_fail", "Export failed"));
      });
    }
    if (typeof html2canvas !== "undefined") {
      runCanvas();
      return;
    }
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
    s.onload = runCanvas;
    s.onerror = function () {
      setStatusStripText(i18n("sim_export_fail", "Export failed"));
    };
    document.head.appendChild(s);
  }

  function measureSegmentForTransfer() {
    if (!measurePoints || measurePoints.length < 2) return null;
    return [
      { lat: measurePoints[0].lat, lng: measurePoints[0].lng },
      { lat: measurePoints[1].lat, lng: measurePoints[1].lng },
    ];
  }

  function transferAllToMainMap() {
    if (!pyBridge || !activeWeapon || activeWeapon.id == null) return;
    const sim = {};
    if (map && typeof map.getCenter === "function") {
      const c = map.getCenter();
      sim.mapView = { lat: c.lat, lng: c.lng, zoom: map.getZoom() };
    }
    sim.basemap = basemapMode;
    if ($("chkDefense") && $("chkDefense").checked && launchMarker) {
      const dp = launchMarker.getLatLng();
      sim.defense = { lat: dp.lat + 0.35, lon: dp.lng + 0.35, radiusM: 55000 };
    }
    if (launchMarker) {
      const p = launchMarker.getLatLng();
      sim.launch = { lat: p.lat, lon: p.lng };
    }
    if (targetMarker) {
      const p = targetMarker.getLatLng();
      sim.target = { lat: p.lat, lon: p.lng };
    }
    if (launchMarker && targetMarker) {
      const p0 = launchMarker.getLatLng();
      const p1 = targetMarker.getLatLng();
      const style = ($("arcStyle") && $("arcStyle").value) || "ballistic";
      const flight = ($("flightProfile") && $("flightProfile").value) || "low";
      const pts = buildArc(p0.lat, p0.lng, p1.lat, p1.lng, 72, style, flight);
      sim.path = pts.map(function (row) {
        return [row[0], row[1]];
      });
    }

    const session = gatherState();
    sim.flightProfile = session.flightProfile;
    sim.arcStyle = session.arcStyle;
    sim.playSpeed = session.playSpeed;
    sim.visibility = session.visibility;
    sim.styles = session.styles;
    sim.layoutNorm = snapshotLayoutNormalized();
    sim.measure = measureSegmentForTransfer();
    if (swotReport && swotReport.score_summary) {
      try {
        sim.swotSummary = JSON.parse(JSON.stringify(swotReport.score_summary));
      } catch (e) {
        sim.swotSummary = null;
      }
    } else {
      sim.swotSummary = null;
    }

    // Matches applyWeapon(): null range defaults to 100 km in UI — main map must use the same for rings/effects.
    sim.effectiveRangeKm =
      activeWeapon.range_km != null ? Number(activeWeapon.range_km) : 100;

    pyBridge.request_transfer_to_main_map(
      JSON.stringify({ weapon_id: activeWeapon.id, sim: sim })
    );
  }

  function openMainMap() {
    transferAllToMainMap();
  }

  function fullscreenElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement || null;
  }

  function isFullscreenNative() {
    return !!fullscreenElement();
  }

  function isSimulatorFsLayout() {
    return document.body.classList.contains("sim-map-fs");
  }

  function isSimulatorMapFullscreen() {
    return isFullscreenNative() || isSimulatorFsLayout();
  }

  function invalidateAfterFsChange() {
    setTimeout(function () {
      if (map && typeof map.invalidateSize === "function") map.invalidateSize(true);
      updateFullscreenButtonLabel();
    }, 220);
  }

  function snapshotCurrentLayout() {
    const out = {};
    getBoxEls().forEach(function (el) {
      const id = el.getAttribute("data-box-id") || el.id;
      out[id] = boxRectRelativeToWrap(el);
    });
    return out;
  }

  function applyFullscreenEdgeLayout() {
    const wrap = $("map-wrap");
    if (!wrap) return;
    const W = wrap.clientWidth || 1200;
    const H = wrap.clientHeight || 800;
    const pad = 12;
    const gap = 8;
    const zoomBand = 96;
    const leftW = Math.min(400, Math.max(250, Math.round(W * 0.30)));
    const rightW = Math.min(420, Math.max(250, Math.round(W * 0.31)));
    const titleW = Math.min(460, Math.max(240, Math.round(W * 0.34)));
    const modelW = Math.min(500, Math.max(260, Math.round(W * 0.35)));
    const modelH = Math.min(340, Math.max(190, Math.round(H * 0.34)));
    const row2Top = pad + zoomBand;
    const legendH = 132;

    function place(id, left, top, width, height) {
      const el = $(id);
      if (!el) return;
      const w = Math.max(38, Math.min(width, W - left - pad));
      const h = Math.max(38, Math.min(height, H - top - pad));
      applyBoxRect(el, { left: left, top: top, width: w, height: h });
    }

    place("zoomBar", pad, pad, 44, 88);
    place("neonMissileTitle", W - pad - titleW, pad, titleW, 58);
    place("btnTransferMainMap", W - pad - 50, pad + 6, 46, 46);

    const swotH = Math.max(
      200,
      Math.min(460, H - row2Top - Math.round(H * 0.36) - pad)
    );
    place("swotOverlay", pad, row2Top, leftW, swotH);
    place("simModelBox", W - pad - modelW, row2Top, modelW, modelH);

    const legendTop = row2Top + modelH + gap;
    place("legendBox", W - pad - rightW, legendTop, rightW, legendH);

    const bottomY = H - pad;
    const statusH = 60;
    const hudH = 76;
    const telH = 198;
    let aiH = 180;
    const statusTop = bottomY - statusH;
    let aiTop = statusTop - gap - aiH;
    const legendBottom = legendTop + legendH;
    if (aiTop < legendBottom + gap) {
      aiTop = legendBottom + gap;
    }
    if (aiTop + aiH > statusTop - gap) {
      aiH = Math.max(120, statusTop - gap - aiTop);
    }

    place("statusStrip", W - pad - rightW, statusTop, rightW, statusH);
    place("aiSimBox", W - pad - rightW, aiTop, rightW, aiH);

    const hudTop = bottomY - statusH - gap - hudH;
    const telTop = hudTop - gap - telH;
    place("hud", pad, hudTop, leftW, hudH);
    place("neonTelemetry", pad, telTop, Math.min(leftW, 340), telH);
    place("btnPlayMap", pad, telTop - gap - 46, 118, 46);
    place("btnHelp", W - pad - 42, statusTop - gap - 42, 42, 42);

    if (map && typeof map.invalidateSize === "function") map.invalidateSize(false);
  }

  function exitSimulatorFullscreen() {
    try {
      if (
        fullscreenElement() ||
        document.body.classList.contains("sim-map-fs") ||
        isFullscreenNative()
      ) {
        saveFullscreenLayoutNormalized();
      }
    } catch (e) {}
    document.body.classList.remove("sim-map-fs");
    if (isFullscreenNative()) {
      const exitFn = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;
      if (exitFn) {
        try {
          exitFn.call(document);
        } catch (e) {}
      }
    }
    if (preFullscreenLayout && typeof preFullscreenLayout === "object") {
      Object.keys(preFullscreenLayout).forEach(function (id) {
        const el = $(id);
        if (el) applyBoxRect(el, preFullscreenLayout[id]);
      });
      preFullscreenLayout = null;
    }
    invalidateAfterFsChange();
  }

  function updateFullscreenButtonLabel() {
    const label = $("btnFullscreenLabel");
    const btn = $("btnFullscreen");
    if (!label) return;
    const active = isSimulatorMapFullscreen();
    label.textContent = active
      ? i18n("sim_fullscreen_exit", "Exit fullscreen")
      : i18n("sim_fullscreen_enter", "Fullscreen");
    if (btn) {
      btn.title = active
        ? i18n("sim_fullscreen_exit", "Exit fullscreen")
        : i18n("sim_fullscreen_enter", "Fullscreen map");
      btn.classList.toggle("active-toggle", active);
    }
    const mini = $("btnFsDefault");
    if (mini) {
      mini.classList.toggle("hidden", !active);
      mini.title = i18n("sim_fullscreen_exit", "Exit fullscreen");
    }
  }

  function toggleFullscreenMap() {
    if (isSimulatorFsLayout()) {
      exitSimulatorFullscreen();
      return;
    }
    if (isFullscreenNative()) {
      exitSimulatorFullscreen();
      return;
    }
    preFullscreenLayout = snapshotCurrentLayout();
    const wrap = $("map-wrap");
    function layoutFullscreenFallback() {
      document.body.classList.add("sim-map-fs");
      applyFullscreenLayoutFromSavedOrDefault();
      setTimeout(function () {
        applyFullscreenLayoutFromSavedOrDefault();
        saveFullscreenLayoutNormalized();
      }, 320);
      invalidateAfterFsChange();
    }
    if (!wrap) {
      layoutFullscreenFallback();
      return;
    }
    const reqFs = wrap.requestFullscreen || wrap.webkitRequestFullscreen || wrap.msRequestFullscreen;
    if (!reqFs) {
      layoutFullscreenFallback();
      return;
    }
    try {
      var p = reqFs.call(wrap);
      if (p && typeof p.catch === "function") {
        p.catch(layoutFullscreenFallback);
      }
      applyFullscreenLayoutFromSavedOrDefault();
      setTimeout(function () {
        applyFullscreenLayoutFromSavedOrDefault();
        saveFullscreenLayoutNormalized();
      }, 320);
    } catch (e) {
      layoutFullscreenFallback();
    }
    setTimeout(updateFullscreenButtonLabel, 280);
  }

  function wirePersistTriggersOnce() {
    if (persistTriggersWired || !map) return;
    persistTriggersWired = true;
    map.on("moveend", function () {
      schedulePersistSimulatorUiSoon();
    });
    map.on("zoomend", function () {
      updateStats();
      schedulePersistSimulatorUiSoon();
    });
    if ($("playSpeed")) $("playSpeed").addEventListener("change", schedulePersistSimulatorUiSoon);
    if ($("exportFormat")) $("exportFormat").addEventListener("change", schedulePersistSimulatorUiSoon);
  }

  function tryHydrateSimulatorPrefsFromHost() {
    if (simPrefsHydrated || !map) return;
    if (pyBridge && pyBridge.fetch_simulator_ui_state) {
      simPrefsHydrated = true;
      simUiHydrating = true;
      pyBridge.fetch_simulator_ui_state(function (blob) {
        var ok = false;
        if (blob) {
          try {
            applyPersistedSimulatorPrefs(JSON.parse(blob));
            ok = true;
          } catch (ex) {}
        }
        simUiHydrating = false;
        if (!ok) loadLayoutFromStorage();
        if (map && typeof map.invalidateSize === "function") map.invalidateSize(false);
        updateDefense();
        wirePersistTriggersOnce();
        simPrefsReadyToPersist = true;
      });
      return;
    }
    if (typeof qt !== "undefined" && pyBridge) {
      simPrefsHydrated = true;
      loadLayoutFromStorage();
      wirePersistTriggersOnce();
      simPrefsReadyToPersist = !!(pyBridge.save_simulator_ui_state);
      return;
    }
    if (typeof qt === "undefined") {
      simPrefsHydrated = true;
      loadLayoutFromStorage();
      wirePersistTriggersOnce();
      simPrefsReadyToPersist = true;
    }
  }

  function initChannel() {
    if (typeof qt === "undefined" || typeof QWebChannel === "undefined") return;
    new QWebChannel(qt.webChannelTransport, function (channel) {
      pyBridge = channel.objects.pyBridge;
      offlineTilesEnabled = !!(pyBridge && pyBridge.get_tile_data_uri);
      if (offlineTilesEnabled && map) {
        setBasemap(basemapMode);
      }
      // allow Python to push text into the simulator UI
      if (window.armorySimulator) window.armorySimulator.showAiSimBox = showAiSimBox;
      tryHydrateSimulatorPrefsFromHost();
    });
  }

  function tutorialShowStep() {
    $("tut_title").textContent = i18n("sim_tutorial_welcome", "Welcome");
    const bodies = [
      i18n("sim_tutorial_intro", "Tour"),
      i18n("sim_tutorial_step1", "Step 1"),
      i18n("sim_tutorial_step2", "Step 2"),
      i18n("sim_tutorial_step3", "Step 3"),
    ];
    $("tut_body").textContent = bodies[tutorialStep] || bodies[0];
    $("tut_step").textContent = tutorialStep > 0 ? tutorialStep + " / 3" : "";
    const nextBtn = $("btnTutorialNext");
    nextBtn.textContent =
      tutorialStep >= 3 ? i18n("sim_tutorial_done", "Start") : i18n("sim_tutorial_next", "Next");
  }

  function maybeTutorial() {
    try {
      if (!localStorage.getItem(STORAGE_TUTORIAL)) {
        tutorialStep = 0;
        $("tutorial").classList.remove("hidden");
        tutorialShowStep();
      }
    } catch (e) {
      $("tutorial").classList.add("hidden");
    }
    $("btnTutorialSkip").onclick = function () {
      $("tutorial").classList.add("hidden");
      try {
        localStorage.setItem(STORAGE_TUTORIAL, "1");
      } catch (e2) {}
    };
    $("btnTutorialNext").onclick = function () {
      if (tutorialStep >= 3) {
        $("tutorial").classList.add("hidden");
        try {
          localStorage.setItem(STORAGE_TUTORIAL, "1");
        } catch (e2) {}
        return;
      }
      tutorialStep++;
      tutorialShowStep();
    };
  }

  function onKey(ev) {
    if (ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT")) return;
    if (ev.key === " " || ev.code === "Space") {
      ev.preventDefault();
      playSim();
    } else if (ev.key === "z" || ev.key === "Z") {
      undoLaunch();
    } else if (ev.key === "r" || ev.key === "R") {
      resetTarget();
    } else if (ev.key === "m" || ev.key === "M") {
      measureMode = !measureMode;
      measurePoints = [];
      if (measureLayer) {
        map.removeLayer(measureLayer);
        measureLayer = null;
      }
      $("btnMeasure").classList.toggle("active-toggle", measureMode);
      setStatusStripText(
        measureMode ? i18n("sim_measure_hint", "Measure: click two points") : "—"
      );
    } else if (ev.key === "?" || (ev.shiftKey && ev.key === "/")) {
      $("helpModal").classList.remove("hidden");
    } else if (ev.key === "Escape" && measureMode) {
      measureMode = false;
      measurePoints = [];
      $("btnMeasure").classList.remove("active-toggle");
      updateHud();
    } else if (ev.key === "Escape" && typeof isSimulatorMapFullscreen === "function" && isSimulatorMapFullscreen()) {
      exitSimulatorFullscreen();
      ev.preventDefault();
    }
  }

  var _simCtxEl = null;
  var _simCtxCloseBound = false;

  function hideSimContextMenu() {
    if (_simCtxEl) {
      _simCtxEl.style.display = "none";
    }
  }

  function copySimCoordsToClipboard(text) {
    function fallback(t) {
      var ta = document.createElement("textarea");
      ta.value = t;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-10000px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch (err) {}
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () {
        fallback(text);
      });
    } else {
      fallback(text);
    }
  }

  function ensureSimContextMenu() {
    if (_simCtxEl) return _simCtxEl;
    _simCtxEl = document.createElement("div");
    _simCtxEl.id = "simMapCtxMenu";
    _simCtxEl.setAttribute("role", "menu");
    document.body.appendChild(_simCtxEl);
    return _simCtxEl;
  }

  function showSimContextMenu(lat, lng, clientX, clientY) {
    var line = Number(lat).toFixed(6) + ", " + Number(lng).toFixed(6);
    var menu = ensureSimContextMenu();
    menu.innerHTML = "";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "map-ctx-btn";
    btn.setAttribute("role", "menuitem");
    btn.textContent = i18n("sim_ctx_copy_coords", "Copy coordinates");
    btn.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      copySimCoordsToClipboard(line);
      setStatusStripText(i18n("sim_ctx_copied_coords", "Copied coordinates"));
      hideSimContextMenu();
    };
    var preview = document.createElement("div");
    preview.className = "map-ctx-preview";
    preview.textContent = line;
    menu.appendChild(btn);
    menu.appendChild(preview);
    menu.style.display = "block";
    menu.style.visibility = "hidden";
    var mw = menu.offsetWidth;
    var mh = menu.offsetHeight;
    menu.style.visibility = "visible";
    var px = clientX;
    var py = clientY;
    if (px + mw > window.innerWidth - 8) px = Math.max(8, window.innerWidth - mw - 8);
    if (py + mh > window.innerHeight - 8) py = Math.max(8, window.innerHeight - mh - 8);
    menu.style.left = px + "px";
    menu.style.top = py + "px";

    if (!_simCtxCloseBound) {
      _simCtxCloseBound = true;
      document.addEventListener(
        "click",
        function (e) {
          if (_simCtxEl && _simCtxEl.style.display !== "none" && !_simCtxEl.contains(e.target)) {
            hideSimContextMenu();
          }
        },
        true
      );
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") hideSimContextMenu();
      });
    }
    setTimeout(function () {
      btn.focus();
    }, 0);
  }

  function initMap() {
    wireSimSidebarToggle();
    const center = [31.5, 34.8];
    map = L.map("map", { zoomControl: false }).setView(center, 6);
    setBasemap("dark");
    map.on("click", onMapClick);
    map.on("contextmenu", function (evt) {
      evt.originalEvent.preventDefault();
      evt.originalEvent.stopPropagation();
      var ev = evt.originalEvent;
      showSimContextMenu(evt.latlng.lat, evt.latlng.lng, ev.clientX, ev.clientY);
    });
    map.on("zoomstart movestart", hideSimContextMenu);

    $("btnZoomIn").onclick = $("btnZoomIn2").onclick = function () {
      map.zoomIn();
      updateStats();
    };
    $("btnZoomOut").onclick = $("btnZoomOut2").onclick = function () {
      map.zoomOut();
      updateStats();
    };
    document.querySelectorAll("[data-zoom]").forEach(function (btn) {
      btn.onclick = function () {
        const z = parseInt(btn.getAttribute("data-zoom"), 10);
        map.setZoom(z);
        updateStats();
      };
    });
    $("btnLabels").onclick = toggleLabels;
    $("btnPlay").onclick = playSim;
    if ($("btnPlayMap")) $("btnPlayMap").onclick = playSim;
    $("weaponSelect").onchange = pickFromSelect;
    $("weaponSearch").oninput = populateSelect;
    $("basemapSelect").onchange = function () {
      setBasemap($("basemapSelect").value);
    };
    $("btnLoadAll").onclick = loadFullCatalog;
    $("btnMeasure").onclick = function () {
      measureMode = !measureMode;
      measurePoints = [];
      $("btnMeasure").classList.toggle("active-toggle", measureMode);
      setStatusStripText(
        measureMode ? i18n("sim_measure_hint", "Measure: click two points") : "—"
      );
    };
    $("btnUndoLaunch").onclick = undoLaunch;
    $("btnResetTarget").onclick = resetTarget;
    $("btnExport").onclick = exportPng;
    $("btnOpenMap").onclick = openMainMap;
    if ($("btnTransferMainMap")) $("btnTransferMainMap").onclick = transferAllToMainMap;
    if ($("btnTransferFromSwot")) $("btnTransferFromSwot").onclick = transferAllToMainMap;
    $("btnFullscreen").onclick = toggleFullscreenMap;
    if ($("btnToggleSwot")) $("btnToggleSwot").onclick = toggleSwotOverlay;
    if ($("btnAiSim")) $("btnAiSim").onclick = requestAiSimAnalysis;
    if ($("btnSaveSim")) $("btnSaveSim").onclick = saveSessionToSystem;
    if ($("btnLoadSim")) $("btnLoadSim").onclick = loadSessionFromSystem;
    if ($("btnExportSystem")) $("btnExportSystem").onclick = exportToSystem;

    ["visLegend","visHud","visStatus","visTelemetry","visMissileTitle","visZoom","visHelp","visAiSim","visSwot","visModel3d","visRangeAzimuth"].forEach(function(id){
      const el = $(id);
      if (el)
        el.addEventListener("change", function () {
          applyComponentVisibility();
          schedulePersistSimulatorUiSoon();
        });
    });
    if ($("simLayoutGlassOp")) {
      $("simLayoutGlassOp").addEventListener("input", function () {
        applyLayoutGlassOpacityFromUi();
        schedulePersistSimulatorUiSoon();
      });
    }
    $("chkDefense").onchange = function () {
      updateDefense();
      schedulePersistSimulatorUiSoon();
    };
    $("chkHC").onchange = function () {
      document.body.classList.toggle("sim-hc", $("chkHC").checked);
      schedulePersistSimulatorUiSoon();
    };
    $("arcStyle").onchange = function () {
      updateHud();
      schedulePersistSimulatorUiSoon();
    };
    $("flightProfile").onchange = function () {
      updateHud();
      schedulePersistSimulatorUiSoon();
    };

    $("btnHelp").onclick = function () {
      $("helpModal").classList.remove("hidden");
    };
    if ($("btnFsDefault")) {
      $("btnFsDefault").onclick = function () {
        exitSimulatorFullscreen();
      };
    }
    $("btnHelpClose").onclick = function () {
      $("helpModal").classList.add("hidden");
    };
    $("help_title").textContent = i18n("sim_help_title", "Shortcuts");
    $("help_body").textContent = i18n("sim_help_keys", "");

    document.addEventListener("fullscreenchange", function () {
      updateFullscreenButtonLabel();
      if (map && typeof map.invalidateSize === "function") map.invalidateSize(true);
      if (isSimulatorMapFullscreen()) {
        applyFullscreenLayoutFromSavedOrDefault();
        setTimeout(function () {
          applyFullscreenLayoutFromSavedOrDefault();
          saveFullscreenLayoutNormalized();
        }, 320);
      } else if (preFullscreenLayout && typeof preFullscreenLayout === "object") {
        Object.keys(preFullscreenLayout).forEach(function (id) {
          const el = $(id);
          if (el) applyBoxRect(el, preFullscreenLayout[id]);
        });
        preFullscreenLayout = null;
      }
    });
    document.addEventListener("webkitfullscreenchange", updateFullscreenButtonLabel);
    document.addEventListener("msfullscreenchange", updateFullscreenButtonLabel);

    document.addEventListener("keydown", onKey);

    if (pendingWeapon) {
      applyWeapon(pendingWeapon);
      pendingWeapon = null;
    } else if (activeWeapon) {
      redrawRange();
    }
    applyLocale();
    wireMapLayerStyleControls();
    updateFullscreenButtonLabel();
    applyComponentVisibility();
    tryHydrateSimulatorPrefsFromHost();
    wireDragResize();
    if ($("btnLayoutEdit")) $("btnLayoutEdit").onclick = toggleLayoutEditMode;
    setLayoutEditMode(false);
    updateStats();
    setTimeout(tryHydrateSimulatorPrefsFromHost, 0);
  }

  window.armorySimulator = {
    setCatalog: function (items) {
      catalog = Array.isArray(items) ? items : [];
      populateSelect();
    },
    setActiveWeapon: function (w) {
      if (!w || w.id == null) return;
      let merged = catalog.find(function (x) {
        return Number(x.id) === Number(w.id);
      });
      merged = Object.assign({}, merged || {}, w);
      const exists = catalog.some(function (x) {
        return Number(x.id) === Number(merged.id);
      });
      if (!exists) {
        catalog.push({
          id: merged.id,
          weapon_name: merged.weapon_name,
          model: merged.model,
          range_km: merged.range_km,
          origin_lat: merged.origin_lat,
          origin_lon: merged.origin_lon,
          speed_mach: merged.speed_mach,
          primary_model: merged.primary_model || "",
        });
      }
      if (!map) {
        pendingWeapon = merged;
        return;
      }
      applyWeapon(merged);
    },
    setSwotReport: setSwotReport,
    setSwotEditorText: setSwotEditorText,
    showAiSimBox: showAiSimBox,
    loadState: loadState,
    applyLocale: applyLocale,
    transferAllToMainMap: transferAllToMainMap,
  };

  initChannel();
  ensureLeaflet(function (ok) {
    if (!ok) {
      setHudText("Map library failed to load.");
      return;
    }
    initMap();
    maybeTutorial();
  });
})();
