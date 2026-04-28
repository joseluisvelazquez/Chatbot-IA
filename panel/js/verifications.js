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

function canUseSigaBridgeOps() {
    return ["admin", "jefe_operativo"].includes(window.currentUser?.role);
}

function isVerificationDetailRequestActive(sessionId) {
    return pendingVerificationDetailRequests.has(String(sessionId || ""));
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
    const critica = Number(counts.critica || 0);
    const moderada = Number(counts.moderada || 0);
    const leve = Number(counts.leve || 0);
    const total = Number(
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

function sigaBridgeStatusLabel(status) {
    const map = {
        ok: "SIGA OK",
        timeout: "SIGA timeout",
        fallback_local: "SIGA fallback local",
    };

    return map[status] || "SIGA fallback local";
}

function sigaBridgeStatusClass(status) {
    const map = {
        ok: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
        timeout: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300",
        fallback_local: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
    };

    return map[status] || map.fallback_local;
}

function renderSigaBridgeSummary(item = {}) {
    const bridge = item.siga_bridge;
    if (!canUseSigaBridgeOps() || !bridge?.enabled) {
        return "";
    }

    const status = bridge.status || (bridge.available ? "ok" : "fallback_local");
    const statusLabel = sigaBridgeStatusLabel(status);
    const statusClass = sigaBridgeStatusClass(status);
    const updatedAt = bridge.updated_at ? ui.formatDateTime(bridge.updated_at) : "-";
    const sourceLabel = bridge.source === "siga_bridge" && bridge.available
        ? "Datos desde SIGA"
        : "Datos locales";
    const isRefreshing = isVerificationDetailRequestActive(item.session_id);

    if (!bridge.available) {
        return `
            <div class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <div class="text-xs font-medium uppercase tracking-wide">SIGA</div>
                        <div class="mt-1">${ui.escapeHtml(sourceLabel)}</div>
                    </div>
                    <span class="rounded-full px-2.5 py-1 text-xs font-medium ${statusClass}">
                        ${ui.escapeHtml(statusLabel)}
                    </span>
                </div>
                <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <span class="text-xs">Actualizado: ${ui.escapeHtml(updatedAt)}</span>
                    <button
                        id="refreshSigaBridgeButton"
                        type="button"
                        class="inline-flex items-center justify-center rounded-lg bg-amber-500 px-3 py-2 text-xs font-medium text-white transition hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-60"
                        ${isRefreshing ? "disabled" : ""}
                    >
                        ${isRefreshing ? "Actualizando..." : "Actualizar datos SIGA"}
                    </button>
                </div>
            </div>
        `;
    }

    const customer = firstBridgeRecord(bridge.customer, ["customers", "customer", "clientes", "cliente"]);
    const account = firstBridgeRecord(bridge.account, ["accounts", "account", "cuentas", "cuenta"]);

    const customerName = firstBridgeValue(customer, ["name", "nombre", "nombre_completo", "cliente"]) || item.name || "-";
    const status = firstBridgeValue(account, ["estatus", "estado", "status"]) || "-";
    const balance = firstBridgeValue(account, ["saldo", "balance", "saldo_actual"]) || "-";
    const plan = firstBridgeValue(account, ["plan", "periodicidad", "frecuencia_pago"]) || "-";
    const paymentsCount = bridgePaymentsCount(bridge.payments);

    return `
        <div class="rounded-xl border border-blue-100 bg-blue-50 p-4 dark:border-blue-950 dark:bg-blue-950/25">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h4 class="text-xs font-medium uppercase tracking-wide text-blue-700 dark:text-blue-300">SIGA</h4>
                    <div class="mt-1 text-xs text-blue-700/70 dark:text-blue-300/70">
                        ${ui.escapeHtml(sourceLabel)} | Actualizado: ${ui.escapeHtml(updatedAt)}
                    </div>
                </div>
                <span class="rounded-full px-2.5 py-1 text-xs font-medium ${statusClass}">
                    ${ui.escapeHtml(statusLabel)}
                </span>
            </div>
            <div class="grid grid-cols-1 gap-3 text-sm md:grid-cols-4">
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Cliente</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(customerName)}</p>
                </div>
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Estado</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(status)}</p>
                </div>
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Saldo</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(balance)}</p>
                </div>
                <div>
                    <p class="text-blue-700/70 dark:text-blue-300/70">Plan / pagos</p>
                    <p class="font-medium text-gray-900 dark:text-white">${ui.escapeHtml(plan)}${paymentsCount == null ? "" : ` / ${paymentsCount}`}</p>
                </div>
            </div>
            <div class="mt-4 flex justify-end">
                <button
                    id="refreshSigaBridgeButton"
                    type="button"
                    class="inline-flex items-center justify-center rounded-lg bg-blue-500 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                    ${isRefreshing ? "disabled" : ""}
                >
                    ${isRefreshing ? "Actualizando..." : "Actualizar datos SIGA"}
                </button>
            </div>
        </div>
    `;
}

function updateVerificationKpis(items) {
    const total = document.getElementById("kpiTotal");
    if (!total) return;

    document.getElementById("kpiTotal").textContent = items.length;
    document.getElementById("kpiInProgress").textContent =
        items.filter((item) => item.status === "in_progress").length;
    document.getElementById("kpiInconsistent").textContent =
        items.filter((item) => item.status === "inconsistent").length;
    document.getElementById("kpiCompleted").textContent =
        items.filter((item) => item.status === "completed").length;
}

function closeVerificationDrawer() {
    const { drawer, overlay } = getDrawerElements();
    if (!drawer || !overlay) return;

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
            loadingEl.classList.remove("hidden");
            break;
        case "error":
            errorEl.textContent = state.message || "Error";
            errorEl.classList.remove("hidden");
            break;
        case "empty":
            emptyEl.classList.remove("hidden");
            break;
        case "success":
            tableWrapper.classList.remove("hidden");
            break;
    }
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

function renderDrawerBase(item) {
    const { body } = getDrawerElements();
    if (!body) return;

    body.innerHTML = `
        <div class="flex h-full flex-col text-gray-900 dark:text-white">
            <div id="drawerHeader"></div>

            <div class="mt-4 rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                <h4 class="mb-2 text-xs text-gray-500 dark:text-slate-400">CLIENTE</h4>
                <div id="drawerCliente" class="grid grid-cols-1 gap-3 text-sm md:grid-cols-3"></div>
            </div>

            <div id="drawerSigaBridge" class="mt-4 hidden"></div>

            <div class="mt-4 rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                <h4 class="mb-2 text-xs text-gray-500 dark:text-slate-400">PROGRESO</h4>
                <div id="drawerProgressBar"></div>
                <div id="drawerProgressMeta" class="mt-3 flex justify-between text-xs text-gray-500 dark:text-slate-400"></div>
            </div>

            <div class="mt-4 flex-1 overflow-y-auto rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
                <div class="flex flex-col gap-3 border-b border-gray-200 pb-3 dark:border-slate-700">
                    <div class="flex items-center justify-between gap-3">
                        <h4 class="text-xs text-gray-500 dark:text-slate-400">INCONSISTENCIAS</h4>
                        <div id="drawerSeveritySummary" class="flex flex-wrap justify-end gap-2"></div>
                    </div>
                </div>
                <div id="drawerInconsistencias" class="mt-4"></div>
            </div>

            <div id="drawerFooter" class="mt-4"></div>
        </div>
    `;

    updateDrawer(item);
}

function updateDrawer(item) {
    const severityHeader = getSeverityCounts(item).total
        ? renderSeverityBadge(getHighestSeverity(item))
        : `<span class="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">Sin inconsistencias</span>`;

    const header = document.getElementById("drawerHeader");
    if (header) {
        header.innerHTML = `
            <div class="flex items-start justify-between gap-4 border-b border-gray-200 pb-4 dark:border-slate-700">
                <div class="min-w-0">
                    <h2 class="text-2xl font-semibold">
                        Folio ${ui.escapeHtml(item.folio || "-")}
                    </h2>
                    <div class="mt-2 flex flex-wrap items-center gap-2">
                        <span class="${ui.statusClass(item.status)}">
                            ${ui.statusLabel(item.status)}
                        </span>
                        ${severityHeader}
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
                <p>${ui.escapeHtml(item.name || "-")}</p>
            </div>
            <div>
                <p class="text-gray-500 dark:text-slate-400">Telefono</p>
                <p>${ui.escapeHtml(item.phone || "-")}</p>
            </div>
            <div>
                <p class="text-gray-500 dark:text-slate-400">Cuenta</p>
                <p>${ui.escapeHtml(item.no_cuenta || "-")}</p>
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
            refreshButton.onclick = () => refreshVerificationDetail(item, { force: true });
        }
    }

    const progressBar = document.getElementById("drawerProgressBar");
    if (progressBar) {
        progressBar.innerHTML = ui.renderProgressBar(item.progress_pct);
    }

    const progressMeta = document.getElementById("drawerProgressMeta");
    if (progressMeta) {
        progressMeta.innerHTML = `
            <span>${Number(item.progress_pct || 0)}%</span>
            <span>${ui.escapeHtml(item.current_step || "-")}</span>
        `;
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
                    <div class="mb-3 rounded-xl border p-4 ${getInconsistenciaCardTone(entry)}">
                        <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                            <div class="min-w-0">
                                <div class="flex flex-wrap items-center gap-2">
                                    <div class="text-sm font-semibold text-gray-900 dark:text-white">
                                        ${ui.escapeHtml(entry.campo || entry.estado_origen || "General")}
                                    </div>
                                    ${renderSeverityBadge(entry.severidad)}
                                    <span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${isOpen ? "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"}">
                                        ${ui.escapeHtml(isOpen ? "Abierta" : "Cerrada")}
                                    </span>
                                </div>
                                <div class="mt-2 text-sm text-gray-700 dark:text-slate-200">
                                    ${ui.escapeHtml(entry.mensaje || "Sin detalle")}
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
                class="w-full rounded-lg bg-blue-500 py-3 text-white transition hover:bg-blue-600"
            >
                Abrir conversacion
            </button>
        `;

        const goToChatBtn = document.getElementById("goToChat");
        if (goToChatBtn) {
            goToChatBtn.onclick = async () => {
                closeVerificationDrawer();

                setSelectedSession({
                    sessionId: item.session_id,
                    phone: item.phone,
                    name: item.name,
                });

                await navigateTo("conversations");
            };
        }
    }
}

function openVerificationDetail(item) {
    const { drawer, overlay } = getDrawerElements();
    if (!drawer || !overlay) return;

    lastDrawerSessionId = String(item.session_id);
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

    refreshVerificationDetail(item);
}

async function refreshVerificationDetail(item, options = {}) {
    const sessionKey = String(item?.session_id || "");
    if (!sessionKey) return;

    const activeRequest = pendingVerificationDetailRequests.get(sessionKey);
    if (activeRequest) {
        return activeRequest;
    }

    const request = (async () => {
        try {
            const latest = await getVerificationBySession(item.session_id, {
                refreshSiga: Boolean(options.force),
            });
            if (!latest?.session_id || String(latest.session_id) !== sessionKey) {
                return;
            }

            dispatch({
                type: "verifications/upsert",
                payload: latest,
            });
        } catch (error) {
            console.warn("No se pudo refrescar detalle de verificacion:", error);
        } finally {
            pendingVerificationDetailRequests.delete(sessionKey);
            if (String(lastDrawerSessionId || "") === sessionKey) {
                const next = getState().verifications.bySessionId[sessionKey] || item;
                updateDrawer(next);
            }
        }
    })();

    pendingVerificationDetailRequests.set(sessionKey, request);
    if (String(lastDrawerSessionId || "") === sessionKey) {
        const current = getState().verifications.bySessionId[sessionKey] || item;
        updateDrawer(current);
    }

    return request;
}

function updateVerificationRow(row, item) {
    row.className = "cursor-pointer border-b border-gray-100 transition hover:bg-gray-50 dark:border-slate-700 dark:hover:bg-slate-700/40";
    row.innerHTML = `
        <td data-label="No. cuenta" class="px-4 py-4">${ui.escapeHtml(item.no_cuenta || "-")}</td>
        <td data-label="Folio" class="px-4 py-4">${ui.escapeHtml(item.folio || "-")}</td>
        <td data-label="Telefono" class="px-4 py-4">${ui.escapeHtml(item.phone || "-")}</td>
        <td data-label="Estado" class="px-4 py-4">
            <span class="${ui.statusClass(item.status)}">${ui.statusLabel(item.status)}</span>
        </td>
        <td data-label="Progreso" class="px-4 py-4">${ui.renderProgressBar(item.progress_pct)}</td>
        <td data-label="Paso actual" class="px-4 py-4">${ui.escapeHtml(item.current_step || "-")}</td>
        <td data-label="Inconsistencias" class="px-4 py-4">${renderInconsistenciasCell(item)}</td>
        <td data-label="Ultima actividad" class="px-4 py-4 whitespace-nowrap">${ui.formatDateTime(item.last_activity)}</td>
    `;
}

function renderVerificationRows(items, validKeys) {
    const tbody = document.getElementById("verificationTableBody");
    if (!tbody) return;

    const fragment = document.createDocumentFragment();

    items.forEach((item) => {
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
    const allItems = state.verifications.order
        .map((id) => state.verifications.bySessionId[id])
        .filter(Boolean);

    updateVerificationKpis(allItems);

    let items = allItems;

    if (currentVerificationStatus) {
        items = items.filter((item) => item.status === currentVerificationStatus);
    }

    if (!items.length) {
        renderVerificationRows([], new Set());
        setVerificationState({ type: "empty" });
        return;
    }

    const validKeys = new Set(
        state.verifications.order
            .map(String)
            .filter((sessionKey) => {
                if (!currentVerificationStatus) {
                    return true;
                }

                return state.verifications.bySessionId[sessionKey]?.status === currentVerificationStatus;
            })
    );

    renderVerificationRows(items, validKeys);
    setVerificationState({ type: "success" });
}

async function loadVerifications(status = "") {
    const requestId = ++verificationRequestId;
    currentVerificationStatus = status;
    setVerificationState({ type: "loading" });

    try {
        const response = await fetchVerifications(status);
        if (requestId !== verificationRequestId) {
            return;
        }

        const items = response?.data ?? [];

        dispatch({
            type: "verifications/loaded",
            payload: items,
        });
    } catch (error) {
        if (requestId !== verificationRequestId) {
            return;
        }

        setVerificationState({
            type: "error",
            message: error?.message || "Error cargando verificaciones",
        });
    }
}

function bindVerificationFilters() {
    document.querySelectorAll(".filter-btn").forEach((button) => {
        button.onclick = () => {
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

            loadVerifications(button.dataset.status || "");
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
    bindVerificationFilters();
    bindDrawerCloseEvents();

    lastRenderedVerificationVersion = -1;
    lastRenderedVerificationFilter = null;
    lastDrawerSessionId = null;
    lastDrawerSignature = "";

    loadVerifications();

    if (unsubscribeVerificationStore) {
        unsubscribeVerificationStore();
    }

    unsubscribeVerificationStore = subscribeStore((state) => {
        const verificationVersion = Number(state.verifications._version || 0);

        if (
            verificationVersion !== lastRenderedVerificationVersion
            || currentVerificationStatus !== lastRenderedVerificationFilter
        ) {
            renderVerificationsFromState(state);
            lastRenderedVerificationVersion = verificationVersion;
            lastRenderedVerificationFilter = currentVerificationStatus;
        }

        const selected = state.verifications.selected;
        if (!selected) {
            lastDrawerSessionId = null;
            lastDrawerSignature = "";
            return;
        }

        const updated = state.verifications.bySessionId[String(selected)];
        if (!updated) return;

        const signature = buildDrawerSignature(updated);

        if (String(selected) !== lastDrawerSessionId) {
            renderDrawerBase(updated);
            lastDrawerSessionId = String(selected);
            lastDrawerSignature = signature;
            return;
        }

        if (signature !== lastDrawerSignature) {
            updateDrawer(updated);
            lastDrawerSignature = signature;
        }
    });
}

window.goToSiga = function goToSiga(url) {
    if (!url) return false;

    window.open(url, "_blank", "noopener");
    return false;
};
