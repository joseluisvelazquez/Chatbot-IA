import { fetchVerifications, getVerificationBySession, updateInconsistenciaPanelResolution } from "./api.js";
import { navigateTo, setSelectedSession } from "./app.js";
import { dispatch, getState, subscribeStore } from "./store.js";

let currentVerificationStatus = "";
let drawerCloseEventsBound = false;
let unsubscribeVerificationStore = null;
let lastRenderedVerificationVersion = -1;
let lastRenderedVerificationFilter = null;
let lastDrawerSessionId = null;
let lastDrawerSignature = "";
let verificationRequestId = 0;
let isRenderingVerifications = false;
let verificationListController = null;
let verificationLoadingTimers = [];

const verificationRowCache = new Map();
const pendingInconsistenciaUpdates = new Set();
const pendingVerificationDetailRequests = new Map();

const SEVERITY_ORDER = {
    critica: 3,
    moderada: 2,
    leve: 1,
};

const SEVERITY_LABELS = {
    critica: "Critica",
    moderada: "Moderada",
    leve: "Leve",
};

const DATA_STATE_META = {
    siga_fresh: {
        label: "SIGA actualizado",
        className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
        tooltip: "Datos confirmados con SIGA en la ultima consulta.",
    },
    cache: {
        label: "Cache",
        className: "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300",
        tooltip: "Mostrando datos guardados recientemente para evitar esperas innecesarias.",
    },
    fallback_local: {
        label: "Fallback local",
        className: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
        tooltip: "Mostrando datos locales porque SIGA no esta disponible.",
    },
    siga_error: {
        label: "Error SIGA",
        className: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300",
        tooltip: "No se pudo conectar con SIGA. Se mantienen datos anteriores o locales.",
    },
};

function canUseSigaBridgeOps() {
    return ["admin", "jefe_operativo"].includes(window.currentUser?.role);
}

function cleanText(value, fallback = "-") {
    if (value == null) return fallback;
    const cleaned = String(value)
        .replace(/\?{2,}/g, "")
        .replace(/\s+/g, " ")
        .trim();
    return cleaned || fallback;
}

function safeNonNegativeNumber(value, fallback = 0, max = Number.POSITIVE_INFINITY) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return fallback;
    return Math.min(number, max);
}

function relativeTime(value) {
    if (!value) return "sin fecha de actualizacion";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "sin fecha de actualizacion";

    const diffMs = Math.max(Date.now() - date.getTime(), 0);
    const minutes = Math.floor(diffMs / 60000);
    if (minutes < 1) return "hace menos de 1 min";
    if (minutes < 60) return `hace ${minutes} min`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `hace ${hours} h`;

    const days = Math.floor(hours / 24);
    return `hace ${days} d`;
}

function resolveDataState(bridge = {}) {
    if (!bridge || typeof bridge !== "object") return "fallback_local";
    const status = String(bridge.status || "").toLowerCase();
    const source = String(bridge.source || "").toLowerCase();

    if (status === "timeout" || status === "error" || bridge.error) return "siga_error";
    if (status === "fallback_local" || source.includes("local")) return "fallback_local";
    if (source.includes("cache") || bridge.cached || bridge.from_cache) return "cache";
    if (bridge.available && (status === "ok" || source.includes("siga"))) return "siga_fresh";
    return bridge.available ? "cache" : "fallback_local";
}

function renderDataStateBadge(bridge = {}) {
    const state = resolveDataState(bridge);
    const meta = DATA_STATE_META[state] || DATA_STATE_META.fallback_local;
    const updatedAt = bridge.updated_at || bridge.cached_at || bridge.last_updated_at;
    const source = state === "siga_fresh" ? "SIGA" : state === "cache" ? "cache" : "local";
    const summary = state === "fallback_local"
        ? "Mostrando datos locales (SIGA no disponible)"
        : state === "siga_error"
            ? "No se pudo conectar con SIGA"
            : `Datos actualizados ${relativeTime(updatedAt)} (${source})`;

    return `
        <span
            class="group relative inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${meta.className}"
            title="${ui.escapeHtml(meta.tooltip)}"
            aria-label="${ui.escapeHtml(summary)}"
        >
            ${ui.escapeHtml(meta.label)}
            <span class="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-max max-w-[16rem] -translate-x-1/2 rounded-md bg-slate-950 px-2 py-1 text-[11px] text-white shadow-lg group-hover:block dark:bg-slate-100 dark:text-slate-900">
                ${ui.escapeHtml(`${summary}. ${meta.tooltip}`)}
            </span>
        </span>
    `;
}

function isVerificationDetailRequestActive(sessionId) {
    return pendingVerificationDetailRequests.has(String(sessionId || ""));
}

function reportVerificationError(scope, error) {
    console.error(`[verifications] ${scope}:`, error);
}

function cancelStaleVerificationDetailRequests(activeSessionKey = null) {
    for (const [sessionKey, requestState] of pendingVerificationDetailRequests.entries()) {
        if (activeSessionKey != null && sessionKey === activeSessionKey) {
            continue;
        }

        requestState.cancelled = true;
        if (requestState.controller) {
            requestState.controller.abort();
        }
        pendingVerificationDetailRequests.delete(sessionKey);
    }
}

function renderVerificationError(message = "Error renderizando verificaciones") {
    try {
        setVerificationState({ type: "error", message });
    } catch (error) {
        reportVerificationError("render_error_state_failed", error);
    }
}

function getDrawerElements() {
    return {
        drawer: document.getElementById("drawer"),
        body: document.getElementById("drawerBody"),
        overlay: document.getElementById("drawerOverlay"),
    };
}

function normalizeSeverity(value) {
    const severity = String(value || "").trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(SEVERITY_ORDER, severity)
        ? severity
        : null;
}

function getSeverityCounts(item = {}) {
    const counts = item.severity_counts || {};
    const critica = safeNonNegativeNumber(counts.critica);
    const moderada = safeNonNegativeNumber(counts.moderada);
    const leve = safeNonNegativeNumber(counts.leve);
    const total = safeNonNegativeNumber(
        item.inconsistencias_count
        ?? counts.total
        ?? (critica + moderada + leve)
    );

    return {
        critica,
        moderada,
        leve,
        total,
        unknown: Math.max(total - critica - moderada - leve, 0),
    };
}

function getHighestSeverity(item = {}) {
    const explicitSeverity = normalizeSeverity(item.highest_severity);
    if (explicitSeverity) {
        return explicitSeverity;
    }

    const counts = getSeverityCounts(item);
    if (counts.critica > 0) return "critica";
    if (counts.moderada > 0) return "moderada";
    if (counts.leve > 0) return "leve";
    return null;
}

function severityBadgeClass(severity) {
    const map = {
        critica: "bg-red-100 text-red-700 border border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
        moderada: "bg-amber-100 text-amber-700 border border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
        leve: "bg-sky-100 text-sky-700 border border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-900",
        unknown: "bg-slate-100 text-slate-700 border border-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-700",
    };

    return map[severity] || map.unknown;
}

function renderSeverityBadge(severity, count = null) {
    const normalized = normalizeSeverity(severity);
    const label = normalized ? SEVERITY_LABELS[normalized] : "Sin grado";

    return `
        <span class="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${severityBadgeClass(normalized || "unknown")}">
            <span>${ui.escapeHtml(label)}</span>
            ${count == null ? "" : `<span>${Number(count)}</span>`}
        </span>
    `;
}

function renderSeveritySummary(item) {
    const counts = getSeverityCounts(item);

    if (!counts.total) {
        return `<span class="text-xs font-medium text-green-600 dark:text-green-400">Sin inconsistencias</span>`;
    }

    const parts = [];

    if (counts.critica > 0) {
        parts.push(renderSeverityBadge("critica", counts.critica));
    }

    if (counts.moderada > 0) {
        parts.push(renderSeverityBadge("moderada", counts.moderada));
    }

    if (counts.leve > 0) {
        parts.push(renderSeverityBadge("leve", counts.leve));
    }

    if (counts.unknown > 0) {
        parts.push(renderSeverityBadge(null, counts.unknown));
    }

    return parts.join("");
}

function renderInconsistenciasCell(item) {
    const counts = getSeverityCounts(item);
    const highestSeverity = getHighestSeverity(item);

    if (!counts.total) {
        return `<span class="text-sm font-medium text-green-600 dark:text-green-400">Sin inconsistencias</span>`;
    }

    const breakdown = [];

    if (counts.critica > 0) breakdown.push(`${counts.critica} critica`);
    if (counts.moderada > 0) breakdown.push(`${counts.moderada} moderada`);
    if (counts.leve > 0) breakdown.push(`${counts.leve} leve`);
    if (counts.unknown > 0) breakdown.push(`${counts.unknown} sin grado`);

    return `
        <div class="flex min-w-0 flex-col gap-1 md:min-w-[180px]">
            <div class="flex items-center gap-2">
                <span class="text-sm font-semibold text-gray-900 dark:text-white">${counts.total}</span>
                ${renderSeverityBadge(highestSeverity)}
            </div>
            <span class="text-xs text-gray-500 dark:text-slate-400">${ui.escapeHtml(breakdown.join(" | "))}</span>
        </div>
    `;
}

function buildRowSignature(item) {
    const counts = getSeverityCounts(item);

    return JSON.stringify([
        item.no_cuenta || "",
        item.folio || "",
        item.phone || "",
        item.status || "",
        Number(item.progress_pct || 0),
        item.current_step || "",
        Number(item.inconsistencias_count || 0),
        counts.critica,
        counts.moderada,
        counts.leve,
        counts.unknown,
        getHighestSeverity(item) || "",
        item.last_activity || "",
    ]);
}

function buildDrawerSignature(item) {
    return JSON.stringify({
        session_id: item.session_id,
        folio: item.folio || "",
        name: item.name || "",
        phone: item.phone || "",
        no_cuenta: item.no_cuenta || "",
        status: item.status || "",
        progress_pct: Number(item.progress_pct || 0),
        current_step: item.current_step || "",
        last_activity: item.last_activity || "",
        highest_severity: getHighestSeverity(item) || "",
        severity_counts: getSeverityCounts(item),
        inconsistencias: (item.inconsistencias || []).map((entry) => ({
            id: entry.id, //  AGREGAR
            ui_id: entry.ui_id || "",
            campo: entry.campo || "",
            mensaje: entry.mensaje || "",
            estado: entry.estado || "",
            resolved_by_panel: entry.resolved_by_panel, //  AGREGAR
            resolved_by_siga: entry.resolved_by_siga,   //  AGREGAR
            requires_siga: entry.requires_siga,
            business_resolved: entry.business_resolved,
            severidad: normalizeSeverity(entry.severidad) || "",
            estado_origen: entry.estado_origen || "",
            elementos_faltantes: Array.isArray(entry.elementos_faltantes)
                ? entry.elementos_faltantes
                : [],
        })),
        siga_bridge: item.siga_bridge || null,
    });
}

function firstBridgeRecord(data, collectionKeys = []) {
    if (Array.isArray(data)) {
        return data.length && typeof data[0] === "object" ? data[0] : null;
    }

    if (!data || typeof data !== "object") {
        return null;
    }

    for (const key of collectionKeys) {
        const value = data[key];
        if (Array.isArray(value) && value.length && typeof value[0] === "object") {
            return value[0];
        }
        if (value && typeof value === "object" && !Array.isArray(value)) {
            return value;
        }
    }

    return data;
}

function firstBridgeValue(record, keys = []) {
    if (!record || typeof record !== "object") {
        return null;
    }

    for (const key of keys) {
        const value = record[key];
        if (value !== undefined && value !== null && value !== "") {
            return value;
        }
    }

    return null;
}

function bridgePaymentsCount(data) {
    if (Array.isArray(data)) {
        return data.length;
    }

    if (!data || typeof data !== "object") {
        return null;
    }

    for (const key of ["payments", "pagos", "items", "data"]) {
        if (Array.isArray(data[key])) {
            return data[key].length;
        }
    }

    return null;
}

function sigaBridgeStatusLabel(bridgeStatus) {
    const map = {
        ok: "SIGA actualizado",
        timeout: "Error SIGA",
        error: "Error SIGA",
        cache: "Cache",
        fallback_local: "Fallback local",
    };

    return map[bridgeStatus] || "Fallback local";
}

function sigaBridgeStatusClass(bridgeStatus) {
    const map = {
        ok: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
        cache: "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300",
        error: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300",
        timeout: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300",
        fallback_local: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
    };

    return map[bridgeStatus] || map.fallback_local;
}

function renderSigaBridgeSummary(item = {}) {
    const bridge = item.siga_bridge;
    if (!canUseSigaBridgeOps() || !bridge || typeof bridge !== "object" || !bridge.enabled) {
        return "";
    }

    const dataState = resolveDataState(bridge);
    const updatedAt = bridge.updated_at ? ui.formatDateTime(bridge.updated_at) : "-";
    const relativeUpdatedAt = relativeTime(bridge.updated_at || bridge.cached_at || bridge.last_updated_at);
    const sourceLabel = bridge.status_message || (dataState === "siga_fresh"
        ? `Datos actualizados ${relativeUpdatedAt} (SIGA)`
        : dataState === "cache"
            ? `Datos cacheados ${relativeUpdatedAt}`
            : dataState === "siga_error"
                ? "Mostrando datos anteriores"
                : "Mostrando datos locales (SIGA no disponible)");
    const isRefreshing = isVerificationDetailRequestActive(item.session_id);

    if (!bridge.available) {
        return `
            <div class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <div class="text-xs font-medium uppercase tracking-wide">SIGA</div>
                        <div class="mt-1">${ui.escapeHtml(sourceLabel)}</div>
                    </div>
                    ${renderDataStateBadge(bridge)}
                </div>
                <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <span class="text-xs">Actualizado: ${ui.escapeHtml(updatedAt)}</span>
                    <button
                        id="refreshSigaBridgeButton"
                        type="button"
                        class="inline-flex items-center justify-center rounded-lg bg-amber-500 px-3 py-2 text-xs font-medium text-white transition hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-60"
                        ${isRefreshing ? "disabled" : ""}
                    >
                        ${isRefreshing ? "Consultando SIGA..." : "Actualizar SIGA"}
                    </button>
                </div>
            </div>
        `;
    }

    const customer = firstBridgeRecord(bridge.customer, ["customers", "customer", "clientes", "cliente"]);
    const account = firstBridgeRecord(bridge.account, ["accounts", "account", "cuentas", "cuenta"]);

    const customerName = firstBridgeValue(customer, ["name", "nombre", "nombre_completo", "cliente"]) || item.name || "-";
    const accountStatus = firstBridgeValue(account, ["estatus", "estado", "status"]) || "-";
    const balance = firstBridgeValue(account, ["saldo", "balance", "saldo_actual"]) || "-";
    const plan = firstBridgeValue(account, ["plan", "periodicidad", "frecuencia_pago"]) || "-";
    const paymentsCount = bridgePaymentsCount(bridge.payments);

    return `
        <div class="rounded-lg border border-blue-100 bg-blue-50 p-4 shadow-sm dark:border-blue-950 dark:bg-blue-950/25">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h4 class="text-[11px] font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-300">Datos SIGA / cache</h4>
                    <div class="mt-1 text-xs text-blue-700/70 dark:text-blue-300/70">
                        ${ui.escapeHtml(sourceLabel)} | ${ui.escapeHtml(updatedAt)}
                    </div>
                </div>
                ${renderDataStateBadge(bridge)}
            </div>
            <div class="grid grid-cols-1 gap-3 text-sm md:grid-cols-4">
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Cliente</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(cleanText(customerName))}</p>
                </div>
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Estado</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(cleanText(accountStatus))}</p>
                </div>
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Saldo</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(cleanText(balance))}</p>
                </div>
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Plan / pagos</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(cleanText(plan))}${paymentsCount == null ? "" : ` / ${safeNonNegativeNumber(paymentsCount)}`}</p>
                </div>
            </div>
            <div class="mt-4 flex justify-end">
                <button
                    id="refreshSigaBridgeButton"
                    type="button"
                    class="inline-flex items-center justify-center rounded-lg bg-blue-500 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                    ${isRefreshing ? "disabled" : ""}
                >
                    ${isRefreshing ? "Consultando SIGA..." : "Actualizar SIGA"}
                </button>
            </div>
        </div>
    `;
}

function updateVerificationKpis(items) {
    const total = document.getElementById("kpiTotal");
    if (!total) return;

    const safeItems = Array.isArray(items) ? items : [];
    const inProgress = document.getElementById("kpiInProgress");
    const inconsistent = document.getElementById("kpiInconsistent");
    const completed = document.getElementById("kpiCompleted");

    total.textContent = safeItems.length;
    if (inProgress) {
        inProgress.textContent = safeItems.filter((item) => item?.status === "in_progress").length;
    }
    if (inconsistent) {
        inconsistent.textContent = safeItems.filter((item) => item?.status === "inconsistent").length;
    }
    if (completed) {
        completed.textContent = safeItems.filter((item) => item?.status === "completed").length;
    }
}

function closeVerificationDrawer() {
    const { drawer, overlay } = getDrawerElements();
    if (!drawer || !overlay) return;

    cancelStaleVerificationDetailRequests(null);

    dispatch({
        type: "verifications/select",
        payload: null,
    });

    drawer.classList.remove("translate-x-0");
    drawer.classList.add("translate-x-full");

    overlay.classList.remove("opacity-100");
    overlay.classList.add("opacity-0", "pointer-events-none");
}

window.closeVerificationDrawer = closeVerificationDrawer;

function setVerificationState(state) {
    const loadingEl = document.getElementById("verificationLoading");
    const errorEl = document.getElementById("verificationError");
    const emptyEl = document.getElementById("verificationEmpty");
    const tableWrapper = document.getElementById("verificationTableWrapper");

    if (!loadingEl || !errorEl || !emptyEl || !tableWrapper) return;

    loadingEl.classList.add("hidden");
    errorEl.classList.add("hidden");
    emptyEl.classList.add("hidden");
    tableWrapper.classList.add("hidden");

    switch (state.type) {
        case "loading":
            loadingEl.innerHTML = `
                <div class="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                    <div class="text-sm font-medium text-slate-600 dark:text-slate-300">${ui.escapeHtml(loadingEl.textContent || "Consultando datos...")}</div>
                    ${ui.renderSkeletonRows ? ui.renderSkeletonRows(4) : ""}
                </div>
            `;
            loadingEl.classList.remove("hidden");
            break;
        case "error":
            errorEl.textContent = state.message || "Error";
            errorEl.classList.remove("hidden");
            break;
        case "empty":
            emptyEl.innerHTML = ui.renderEmptyState
                ? ui.renderEmptyState({
                    title: "Sin verificaciones",
                    body: "No hay registros para el filtro seleccionado.",
                    icon: "clipboard-list",
                })
                : "No hay registros para mostrar.";
            emptyEl.classList.remove("hidden");
            break;
        case "success":
            tableWrapper.classList.remove("hidden");
            break;
    }
}

function clearVerificationLoadingTimers() {
    verificationLoadingTimers.forEach((timer) => window.clearTimeout(timer));
    verificationLoadingTimers = [];
}

function setVerificationLoadingProgress(requestId) {
    clearVerificationLoadingTimers();

    verificationLoadingTimers.push(window.setTimeout(() => {
        if (requestId === verificationRequestId) {
            setVerificationState({ type: "loading" });
        }
    }, 1000));

    verificationLoadingTimers.push(window.setTimeout(() => {
        if (requestId === verificationRequestId) {
            const loadingEl = document.getElementById("verificationLoading");
            if (loadingEl) loadingEl.textContent = "Actualizando datos...";
            setVerificationState({ type: "loading" });
        }
    }, 3000));

    verificationLoadingTimers.push(window.setTimeout(() => {
        if (requestId === verificationRequestId) {
            const loadingEl = document.getElementById("verificationLoading");
            if (loadingEl) loadingEl.textContent = "Mostrando datos anteriores si SIGA tarda mas de lo esperado...";
            setVerificationState({ type: "loading" });
            const state = getState();
            if (state.verifications?.order?.length) {
                renderVerificationsFromState(state);
            }
        }
    }, 6000));
}

function getInconsistenciaCardTone(item) {
    const severity = normalizeSeverity(item.severidad);
    const isOpen = String(item.estado || "").toUpperCase() === "ABIERTA";

    if (!isOpen) {
        return "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/25";
    }

    if (severity === "critica") {
        return "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/25";
    }

    if (severity === "moderada") {
        return "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/25";
    }

    if (severity === "leve") {
        return "border-sky-200 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/25";
    }

    return "border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60";
}

function renderMissingElements(item) {
    const elements = Array.isArray(item.elementos_faltantes)
        ? item.elementos_faltantes.filter(Boolean)
        : [];

    if (!elements.length) {
        return "";
    }

    return `
        <div class="mt-3 flex flex-wrap gap-2">
            ${elements.map((entry) => `
                <span class="inline-flex items-center rounded-full bg-white/80 px-2.5 py-1 text-xs text-gray-700 dark:bg-slate-900/70 dark:text-slate-200">
                    ${ui.escapeHtml(entry)}
                </span>
            `).join("")}
        </div>
    `;
}

function renderResolutionActions(entry, item) {
    if (!entry.id) {
        return "";
    }

    const isPanelResolved = Boolean(entry.resolved_by_panel);
    const isSigaResolved = Boolean(entry.resolved_by_siga);
    const requiresSiga = entry.requires_siga !== false;
    const nextPanelValue = !isPanelResolved;

    if (isSigaResolved) {
        return `
            <span class="inline-flex items-center rounded-lg bg-emerald-100 px-3 py-2 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                Validada en SIGA
            </span>
        `;
    }

    const sigaButton = requiresSiga
        ? `
            <button
                type="button"
                data-siga-url="${ui.escapeHtml(item.siga_url || "")}"
                class="inline-flex items-center justify-center rounded-lg bg-blue-500 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-600"
            >
                Ir a SIGA
            </button>
        `
        : "";

    const localButton = `
        <button
            type="button"
            data-inconsistencia-id="${ui.escapeHtml(entry.id)}"
            data-ui-id="${ui.escapeHtml(entry.ui_id)}"
            data-resolved-by-panel="${String(nextPanelValue)}"
            class="inline-flex items-center justify-center rounded-lg ${isPanelResolved ? "bg-slate-200 text-slate-700 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600" : "bg-amber-500 text-white hover:bg-amber-600"} px-3 py-2 text-xs font-medium transition"
        >
            ${isPanelResolved ? "Desmarcar" : "Marcar resuelto local"}
        </button>
    `;

    return `
        <div class="flex flex-wrap gap-2 md:justify-end">
            ${sigaButton}
            ${localButton}
        </div>
    `;
}

function renderStepTimeline(item = {}) {
    const currentStep = cleanText(item.current_step, "");
    const totalSteps = safeNonNegativeNumber(item.total_steps, 0);
    const confirmed = safeNonNegativeNumber(item.confirmed_count, 0, totalSteps || Number.POSITIVE_INFINITY);

    if (!currentStep && !totalSteps) return "";

    const pct = totalSteps
        ? Math.round((confirmed / totalSteps) * 100)
        : safeNonNegativeNumber(item.progress_pct, 0, 100);

    return `
        <div class="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/40">
            <div class="flex items-center justify-between gap-3 text-xs">
                <span class="font-medium text-slate-700 dark:text-slate-200">${ui.escapeHtml(currentStep || "Paso actual")}</span>
                <span class="text-slate-500 dark:text-slate-400">${totalSteps ? `${confirmed}/${totalSteps}` : `${pct}%`}</span>
            </div>
            <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                <div class="h-full rounded-full bg-blue-600 transition-all" style="width: ${pct}%"></div>
            </div>
        </div>
    `;
}

function renderDrawerBase(item) {
    const { body } = getDrawerElements();
    if (!body) return;

    try {
        body.innerHTML = `
            <div class="flex h-full flex-col text-gray-900 dark:text-white">
                <div id="drawerHeader"></div>

                <div class="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800">
                    <h4 class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Resumen local</h4>
                    <div id="drawerCliente" class="grid grid-cols-1 gap-3 text-sm md:grid-cols-3"></div>
                </div>

                <div id="drawerSigaBridge" class="mt-4 hidden"></div>

                <div class="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800">
                    <h4 class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Progreso</h4>
                    <div id="drawerProgressBar"></div>
                    <div id="drawerProgressMeta" class="mt-3 flex justify-between text-xs text-gray-500 dark:text-slate-400"></div>
                    <div id="drawerTimeline"></div>
                </div>

                <div class="mt-4 flex-1 overflow-y-auto rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800">
                    <div class="flex flex-col gap-3 border-b border-gray-200 pb-3 dark:border-slate-700">
                        <div class="flex items-center justify-between gap-3">
                            <h4 class="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Inconsistencias</h4>
                            <div id="drawerSeveritySummary" class="flex flex-wrap justify-end gap-2"></div>
                        </div>
                    </div>
                    <div id="drawerInconsistencias" class="mt-4"></div>
                </div>

                <div id="drawerFooter" class="mt-4"></div>
            </div>
        `;

        updateDrawer(item);
    } catch (error) {
        reportVerificationError("render_drawer_base_failed", error);
        body.innerHTML = `
            <div class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                No se pudo renderizar el detalle. El panel sigue disponible.
            </div>
        `;
    }
}

function updateDrawer(item) {
    try {
    const severityHeader = getSeverityCounts(item).total
        ? renderSeverityBadge(getHighestSeverity(item))
        : `<span class="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">Sin inconsistencias</span>`;
    const drawerDataStateBadge = canUseSigaBridgeOps() && item.siga_bridge?.enabled
        ? renderDataStateBadge(item.siga_bridge)
        : "";

    const header = document.getElementById("drawerHeader");
    if (header) {
        header.innerHTML = `
            <div class="flex items-start justify-between gap-4 border-b border-gray-200 pb-4 dark:border-slate-700">
                <div class="min-w-0">
                    <h2 class="text-2xl font-semibold">
                        Folio ${ui.escapeHtml(cleanText(item.folio))}
                    </h2>
                    <div class="mt-2 flex flex-wrap items-center gap-2">
                        <span class="${ui.statusClass(item.status)}">
                            ${ui.statusLabel(item.status)}
                        </span>
                        ${severityHeader}
                        ${drawerDataStateBadge}
                    </div>
                    <div class="mt-2 text-xs text-gray-500 dark:text-slate-400">
                        Ultima actividad: ${ui.formatDateTime(item.last_activity)}
                    </div>
                </div>
                <button
                    id="drawerCloseButton"
                    type="button"
                    class="h-10 w-10 rounded-lg bg-gray-100 text-gray-700 transition hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
                >
                    X
                </button>
            </div>
        `;

        const closeButton = document.getElementById("drawerCloseButton");
        if (closeButton) {
            closeButton.onclick = closeVerificationDrawer;
        }
    }

    const cliente = document.getElementById("drawerCliente");
    if (cliente) {
        cliente.innerHTML = `
            <div>
                <p class="text-gray-500 dark:text-slate-400">Nombre</p>
                <p>${ui.escapeHtml(cleanText(item.name))}</p>
            </div>
            <div>
                <p class="text-gray-500 dark:text-slate-400">Telefono</p>
                <p>${ui.escapeHtml(cleanText(item.phone))}</p>
            </div>
            <div>
                <p class="text-gray-500 dark:text-slate-400">Cuenta</p>
                <p>${ui.escapeHtml(cleanText(item.no_cuenta))}</p>
            </div>
        `;
    }

    const sigaBridgeEl = document.getElementById("drawerSigaBridge");
    if (sigaBridgeEl) {
        const bridgeHtml = renderSigaBridgeSummary(item);
        sigaBridgeEl.innerHTML = bridgeHtml;
        sigaBridgeEl.classList.toggle("hidden", !bridgeHtml);

        const refreshButton = document.getElementById("refreshSigaBridgeButton");
        if (refreshButton) {
            refreshButton.onclick = () => {
                void refreshVerificationDetail(item, { force: true });
            };
        }
    }

    const progressBar = document.getElementById("drawerProgressBar");
    if (progressBar) {
        progressBar.innerHTML = ui.renderProgressBar(item.progress_pct);
    }

    const progressMeta = document.getElementById("drawerProgressMeta");
    if (progressMeta) {
        progressMeta.innerHTML = `
            <span>${safeNonNegativeNumber(item.progress_pct, 0, 100)}%</span>
            <span>${ui.escapeHtml(cleanText(item.current_step))}</span>
        `;
    }

    const timeline = document.getElementById("drawerTimeline");
    if (timeline) {
        timeline.innerHTML = renderStepTimeline(item);
    }

    const severitySummary = document.getElementById("drawerSeveritySummary");
    if (severitySummary) {
        severitySummary.innerHTML = renderSeveritySummary(item);
    }

    const inconsistenciasEl = document.getElementById("drawerInconsistencias");
    if (inconsistenciasEl) {
        const inconsistencias = Array.isArray(item.inconsistencias)
            ? item.inconsistencias
            : [];

        inconsistenciasEl.innerHTML = inconsistencias.length
            ? inconsistencias.map((entry) => {
                const isOpen = String(entry.estado || "").toUpperCase() === "ABIERTA";

                return `
                    <div class="mb-3 rounded-lg border p-4 shadow-sm ${isOpen ? "border-l-4 border-l-red-500" : ""} ${getInconsistenciaCardTone(entry)}">
                        <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                            <div class="min-w-0">
                                <div class="flex flex-wrap items-center gap-2">
                                    <div class="text-sm font-semibold text-gray-900 dark:text-white">
                                        ${ui.escapeHtml(cleanText(entry.campo || entry.estado_origen, "General"))}
                                    </div>
                                    ${renderSeverityBadge(entry.severidad)}
                                    <span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${isOpen ? "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"}">
                                        ${ui.escapeHtml(isOpen ? "Abierta" : "Cerrada")}
                                    </span>
                                </div>
                                <div class="mt-2 text-sm text-gray-700 dark:text-slate-200">
                                    ${ui.escapeHtml(cleanText(entry.mensaje, "Sin detalle"))}
                                </div>
                                ${renderMissingElements(entry)}
                            </div>
                            ${renderResolutionActions(entry, item)}
                        </div>
                    </div>
                `;
            }).join("")
            : `<p class="text-sm font-medium text-green-600 dark:text-green-400">Sin inconsistencias</p>`;

        inconsistenciasEl.querySelectorAll("[data-siga-url]").forEach((button) => {
            button.onclick = () => {
                window.goToSiga(button.dataset.sigaUrl || "");
            };
        });

        inconsistenciasEl.querySelectorAll("[data-inconsistencia-id]").forEach((button) => {
                button.onclick = async () => {
                    const inconsistenciaId = Number(button.dataset.inconsistenciaId); 
                    const uiId = button.dataset.uiId; 

                    if (!Number.isFinite(inconsistenciaId) || !uiId) return;

                    const pendingKey = `${item.session_id}:${uiId}`;
                    if (pendingInconsistenciaUpdates.has(pendingKey)) return;

                    const nextValue = button.dataset.resolvedByPanel === "true";
                    const currentEntry = (item.inconsistencias || []).find((entry) => (
                        String(entry.ui_id || "") === String(uiId)
                    ));

                    pendingInconsistenciaUpdates.add(pendingKey);
                    button.disabled = true;

                    dispatch({
                        type: "verifications/update_inconsistencia",
                        payload: {
                            id: inconsistenciaId,
                            ui_id: uiId,
                            session_id: item.session_id,
                            resolved_by_panel: nextValue,
                            resolved_by_siga: Boolean(currentEntry?.resolved_by_siga),
                        }
                    });

                    try {
                        const result = await updateInconsistenciaPanelResolution(
                            inconsistenciaId,
                            nextValue,
                            uiId,
                        );

                        dispatch({
                            type: "verifications/update_inconsistencia",
                            payload: {
                                ...result,
                                id: result?.id ?? inconsistenciaId,
                                ui_id: result?.ui_id ?? uiId,
                                session_id: result?.session_id ?? item.session_id,
                            }
                        });

                        if (result?.verification) {
                            dispatch({
                                type: "verifications/upsert",
                                payload: result.verification,
                            });
                        } else {
                            try {
                                const latest = await getVerificationBySession(item.session_id);
                                dispatch({
                                    type: "verifications/upsert",
                                    payload: latest,
                                });
                            } catch (refreshError) {
                                console.warn("No se pudo refrescar la verificacion:", refreshError);
                            }
                        }
                    } catch (error) {
                        console.error("Error actualizando inconsistencia:", error);

                        dispatch({
                            type: "verifications/update_inconsistencia",
                            payload: {
                                id: inconsistenciaId,
                                ui_id: uiId,
                                session_id: item.session_id,
                                resolved_by_panel: Boolean(currentEntry?.resolved_by_panel),
                                resolved_by_siga: Boolean(currentEntry?.resolved_by_siga),
                            }
                        });
                    } finally {
                        pendingInconsistenciaUpdates.delete(pendingKey);
                        if (button.isConnected) {
                            button.disabled = false;
                        }
                    }
                };
            });
    }

    const footer = document.getElementById("drawerFooter");
    if (footer) {
        footer.innerHTML = `
            <button
                id="goToChat"
                type="button"
                class="w-full rounded-lg bg-blue-600 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900"
            >
                Abrir conversacion
            </button>
        `;

        const goToChatBtn = document.getElementById("goToChat");
        if (goToChatBtn) {
            goToChatBtn.onclick = async () => {
                try {
                    closeVerificationDrawer();

                    setSelectedSession({
                        sessionId: item.session_id,
                        phone: item.phone,
                        name: item.name,
                    });

                    await navigateTo("conversations");
                } catch (error) {
                    reportVerificationError("go_to_chat_failed", error);
                }
            };
        }
    }
    } catch (error) {
        reportVerificationError("update_drawer_failed", error);
    }
}

function openVerificationDetail(item) {
    try {
        const { drawer, overlay } = getDrawerElements();
        if (!drawer || !overlay) return;

        const sessionKey = String(item?.session_id || "");
        if (!sessionKey) return;

        cancelStaleVerificationDetailRequests(sessionKey);

        lastDrawerSessionId = sessionKey;
        lastDrawerSignature = buildDrawerSignature(item);

        dispatch({
            type: "verifications/select",
            payload: item.session_id,
        });

        renderDrawerBase(item);

        drawer.classList.remove("translate-x-full");
        drawer.classList.add("translate-x-0");

        overlay.classList.remove("opacity-0", "pointer-events-none");
        overlay.classList.add("opacity-100");

        void refreshVerificationDetail(item);
    } catch (error) {
        reportVerificationError("open_detail_failed", error);
        renderVerificationError("Error abriendo detalle");
    }
}

async function refreshVerificationDetail(item, options = {}) {
    const sessionKey = String(item?.session_id || "");
    if (!sessionKey) return;

    const activeRequest = pendingVerificationDetailRequests.get(sessionKey);
    if (activeRequest) {
        if (!options.force) {
            return activeRequest.promise;
        }

        activeRequest.cancelled = true;
        if (activeRequest.controller) {
            activeRequest.controller.abort();
        }
        pendingVerificationDetailRequests.delete(sessionKey);
    }

    const controller = new AbortController();
    const requestState = {
        cancelled: false,
        controller,
        promise: null,
    };

    requestState.promise = (async () => {
        const slowTimer = window.setTimeout(() => {
            if (!requestState.cancelled && String(lastDrawerSessionId || "") === sessionKey) {
                const current = getState().verifications.bySessionId[sessionKey] || item;
                updateDrawer({
                    ...current,
                    siga_bridge: {
                        ...(current.siga_bridge || {}),
                        status_message: "Sincronizando...",
                    },
                });
            }
        }, 3000);
        const fallbackTimer = window.setTimeout(() => {
            if (!requestState.cancelled && String(lastDrawerSessionId || "") === sessionKey) {
                const current = getState().verifications.bySessionId[sessionKey] || item;
                updateDrawer({
                    ...current,
                    siga_bridge: {
                        ...(current.siga_bridge || {}),
                        status: current.siga_bridge?.status || "fallback_local",
                        status_message: "Mostrando datos anteriores",
                    },
                });
            }
        }, 6000);

        try {
            const latest = await getVerificationBySession(item.session_id, {
                refreshSiga: Boolean(options.force),
                signal: controller.signal,
            });
            if (requestState.cancelled || String(lastDrawerSessionId || "") !== sessionKey) {
                return;
            }

            if (!latest?.session_id || String(latest.session_id) !== sessionKey) {
                return;
            }

            dispatch({
                type: "verifications/upsert",
                payload: latest,
            });
        } catch (error) {
            if (!requestState.cancelled) {
                console.warn("No se pudo refrescar detalle de verificacion:", error);
            }
        } finally {
            window.clearTimeout(slowTimer);
            window.clearTimeout(fallbackTimer);
            if (pendingVerificationDetailRequests.get(sessionKey) === requestState) {
                pendingVerificationDetailRequests.delete(sessionKey);
            }

            if (!requestState.cancelled && String(lastDrawerSessionId || "") === sessionKey) {
                const next = getState().verifications.bySessionId[sessionKey] || item;
                updateDrawer(next);
            }
        }
    })();

    pendingVerificationDetailRequests.set(sessionKey, requestState);
    if (String(lastDrawerSessionId || "") === sessionKey) {
        const current = getState().verifications.bySessionId[sessionKey] || item;
        updateDrawer(current);
    }

    return requestState.promise;
}

function updateVerificationRow(row, item) {
    row.className = "cursor-pointer border-b border-gray-100 transition hover:bg-gray-50 dark:border-slate-700 dark:hover:bg-slate-700/40";
    row.innerHTML = `
        <td data-label="No. cuenta" class="px-4 py-4">${ui.escapeHtml(cleanText(item.no_cuenta))}</td>
        <td data-label="Folio" class="px-4 py-4">${ui.escapeHtml(cleanText(item.folio))}</td>
        <td data-label="Telefono" class="px-4 py-4">${ui.escapeHtml(cleanText(item.phone))}</td>
        <td data-label="Estado" class="px-4 py-4">
            <span class="${ui.statusClass(item.status)}">${ui.statusLabel(item.status)}</span>
        </td>
        <td data-label="Progreso" class="px-4 py-4">${ui.renderProgressBar(safeNonNegativeNumber(item.progress_pct, 0, 100))}</td>
        <td data-label="Paso actual" class="px-4 py-4">${ui.escapeHtml(cleanText(item.current_step))}</td>
        <td data-label="Inconsistencias" class="px-4 py-4">${renderInconsistenciasCell(item)}</td>
        <td data-label="Ultima actividad" class="px-4 py-4 whitespace-nowrap">${ui.formatDateTime(item.last_activity)}</td>
    `;
}

function renderVerificationRows(items, validKeys) {
    const tbody = document.getElementById("verificationTableBody");
    if (!tbody) return;

    const fragment = document.createDocumentFragment();
    const safeItems = Array.isArray(items) ? items : [];

    safeItems.forEach((item) => {
        if (!item?.session_id) return;

        const sessionKey = String(item.session_id);
        const signature = buildRowSignature(item);
        const cached = verificationRowCache.get(sessionKey) || {
            node: document.createElement("tr"),
            signature: "",
        };

        if (cached.signature !== signature) {
            updateVerificationRow(cached.node, item);
            cached.signature = signature;
        }

        cached.node.onclick = () => openVerificationDetail(item);
        verificationRowCache.set(sessionKey, cached);
        fragment.appendChild(cached.node);
    });

    tbody.replaceChildren(fragment);

    for (const sessionKey of Array.from(verificationRowCache.keys())) {
        if (!validKeys.has(sessionKey)) {
            verificationRowCache.delete(sessionKey);
        }
    }
}

function renderVerificationsFromState(state) {
    if (isRenderingVerifications) {
        return;
    }

    isRenderingVerifications = true;

    try {
        const verifications = state?.verifications || {};
        const allItems = Array.isArray(verifications.order)
            ? verifications.order
                .map((id) => verifications.bySessionId?.[id])
                .filter(Boolean)
            : [];

        updateVerificationKpis(allItems);

        let items = allItems;

        if (currentVerificationStatus) {
            items = items.filter((item) => item?.status === currentVerificationStatus);
        }

        if (!items.length) {
            renderVerificationRows([], new Set());
            setVerificationState({ type: "empty" });
            return;
        }

        const validKeys = new Set(
            verifications.order
                .map(String)
                .filter((sessionKey) => {
                    if (!currentVerificationStatus) {
                        return true;
                    }

                    return verifications.bySessionId?.[sessionKey]?.status === currentVerificationStatus;
                })
        );

        renderVerificationRows(items, validKeys);
        setVerificationState({ type: "success" });
    } catch (error) {
        reportVerificationError("render_verifications_failed", error);
        renderVerificationError();
    } finally {
        isRenderingVerifications = false;
    }
}

async function loadVerifications(filterStatus = "") {
    const requestId = ++verificationRequestId;
    currentVerificationStatus = filterStatus;
    if (verificationListController) {
        verificationListController.abort();
    }
    verificationListController = new AbortController();
    document.getElementById("verificationLoading") && (document.getElementById("verificationLoading").textContent = "Consultando SIGA...");
    setVerificationLoadingProgress(requestId);

    try {
        const response = await fetchVerifications(filterStatus, 500, 0, {
            signal: verificationListController.signal,
        });
        if (requestId !== verificationRequestId) {
            return;
        }

        const items = Array.isArray(response?.data) ? response.data : [];

        dispatch({
            type: "verifications/loaded",
            payload: items,
        });
    } catch (error) {
        if (requestId !== verificationRequestId) {
            return;
        }
        if (verificationListController?.signal?.aborted) {
            return;
        }

        setVerificationState({
            type: "error",
            message: error?.isTimeout
                ? "Tiempo de espera agotado. Mostrando datos anteriores si estan disponibles."
                : error?.message || "No se pudieron cargar las verificaciones",
        });
    } finally {
        if (requestId === verificationRequestId) {
            clearVerificationLoadingTimers();
            verificationListController = null;
        }
    }
}

function bindVerificationFilters() {
    document.querySelectorAll(".filter-btn").forEach((button) => {
        button.onclick = () => {
            try {
                document.querySelectorAll(".filter-btn").forEach((item) => {
                    item.classList.remove("bg-blue-500", "text-white");
                    item.classList.add(
                        "bg-gray-100",
                        "text-gray-700",
                        "dark:bg-slate-700",
                        "dark:text-slate-200",
                    );
                });

                button.classList.remove(
                    "bg-gray-100",
                    "text-gray-700",
                    "dark:bg-slate-700",
                    "dark:text-slate-200",
                );
                button.classList.add("bg-blue-500", "text-white");

                void loadVerifications(button.dataset.status || "");
            } catch (error) {
                reportVerificationError("filter_click_failed", error);
                renderVerificationError("Error aplicando filtro");
            }
        };
    });
}

function bindDrawerCloseEvents() {
    if (drawerCloseEventsBound) return;

    const overlay = document.getElementById("drawerOverlay");
    if (overlay) {
        overlay.onclick = closeVerificationDrawer;
    }

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeVerificationDrawer();
        }
    });

    drawerCloseEventsBound = true;
}

export function initVerificationsPage() {
    try {
        bindVerificationFilters();
        bindDrawerCloseEvents();

        lastRenderedVerificationVersion = -1;
        lastRenderedVerificationFilter = null;
        lastDrawerSessionId = null;
        lastDrawerSignature = "";
        cancelStaleVerificationDetailRequests(null);

        void loadVerifications();

        if (unsubscribeVerificationStore) {
            unsubscribeVerificationStore();
        }

        unsubscribeVerificationStore = subscribeStore((state) => {
            try {
                const verificationVersion = Number(state?.verifications?._version || 0);

                if (
                    verificationVersion !== lastRenderedVerificationVersion
                    || currentVerificationStatus !== lastRenderedVerificationFilter
                ) {
                    renderVerificationsFromState(state);
                    lastRenderedVerificationVersion = verificationVersion;
                    lastRenderedVerificationFilter = currentVerificationStatus;
                }

                const selected = state?.verifications?.selected;
                if (!selected) {
                    cancelStaleVerificationDetailRequests(null);
                    lastDrawerSessionId = null;
                    lastDrawerSignature = "";
                    return;
                }

                const selectedKey = String(selected);
                const updated = state.verifications.bySessionId?.[selectedKey];
                if (!updated) return;

                const signature = buildDrawerSignature(updated);

                if (selectedKey !== lastDrawerSessionId) {
                    cancelStaleVerificationDetailRequests(selectedKey);
                    renderDrawerBase(updated);
                    lastDrawerSessionId = selectedKey;
                    lastDrawerSignature = signature;
                    return;
                }

                if (signature !== lastDrawerSignature) {
                    updateDrawer(updated);
                    lastDrawerSignature = signature;
                }
            } catch (error) {
                reportVerificationError("store_subscription_failed", error);
                renderVerificationError();
            }
        });
    } catch (error) {
        reportVerificationError("init_failed", error);
        renderVerificationError("Error iniciando verificaciones");
    }
}

window.goToSiga = function goToSiga(url) {
    if (!url) return false;

    window.open(url, "_blank", "noopener");
    return false;
};
