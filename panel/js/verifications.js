import { fetchVerifications, getVerificationBySession, updateInconsistenciaPanelResolution, verifyByCallApi } from "./api.js";
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
let verificationRealtimeBound = false;

const verificationRowCache = new Map();
const pendingInconsistenciaUpdates = new Set();
const pendingVerificationDetailRequests = new Map();
const pendingVerificationRowRequests = new Map();

async function refreshVerificationListItem(sessionId) {
    const sessionKey = String(sessionId || "");
    if (!sessionKey) return null;

    const activeRequest = pendingVerificationRowRequests.get(sessionKey);
    if (activeRequest) {
        return activeRequest;
    }

    const request = (async () => {
        try {
            const latest = await getVerificationBySession(sessionId);
            if (!latest?.session_id || String(latest.session_id) !== sessionKey) {
                return null;
            }

            dispatch({
                type: "verifications/upsert",
                payload: latest,
            });
            return latest;
        } catch (error) {
            console.warn("No se pudo refrescar verificacion activa:", error);
            return null;
        } finally {
            pendingVerificationRowRequests.delete(sessionKey);
        }
    })();

    pendingVerificationRowRequests.set(sessionKey, request);
    return request;
}

function setupVerificationRealtimeRecovery() {
    if (verificationRealtimeBound) return;

    window.addEventListener("panel:ws-reconnected", () => {
        if (!document.getElementById("verificationTableBody")) return;
        void loadVerifications(currentVerificationStatus);
    });

    window.addEventListener("panel:ws-message", (event) => {
        const data = event.detail || {};
        if (data.type === "verification_context_changed") {
            const sessionId = data.session_id || data.payload?.session_id;
            if (sessionId) {
                void refreshVerificationListItem(sessionId);
            }
            return;
        }

        if (!["siga_snapshot_updated", "inconsistency_created", "inconsistency_updated"].includes(data.type)) {
            return;
        }

        const sessionId = data.session_id || data.payload?.session_id;
        if (!sessionId || String(sessionId) !== String(lastDrawerSessionId || "")) {
            return;
        }

        const item = getState().verifications.bySessionId[String(sessionId)];
        if (item) {
            void refreshVerificationDetail(item);
        }
    });

    verificationRealtimeBound = true;
}

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

// Etiquetas de pasos de verificación para mostrar en el panel.
// Las claves son los identificadores técnicos del backend (STEP_MAP en verification_tracker.py).
const STEP_DISPLAY_LABELS = {
    folio: "Folio",
    nombre: "Nombre",
    domicilio: "Domicilio",
    fecha: "Fecha venta",
    producto: "Producto",
    componentes: "Componentes",
    pagoInicial: "Pago inicial",
    pagos: "Pagos",
    plan3meses: "Plan 3 meses",
    planes: "Otros planes",
    bancos: "Métodos de pago",
    comprobanteAcceso: "Datos de acceso para comprobante",
    beneficios: "Beneficios",
    finalizado: "Finalizado",
    inicio: "Inicio",
};

function stepLabel(key) {
    if (!key) return "-";
    return STEP_DISPLAY_LABELS[key] || key;
}

function hasAllowedCompany() {
    return [1, 8].includes(Number(window.currentUser?.empresa_id));
}

function canUseSigaBridgeOps() {
    return hasAllowedCompany() && ["admin", "jefe_operativo", "sistemas"].includes(window.currentUser?.role);
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

// ---------------------------------------------------------------------------
// Helpers: mapas de recordatorio a texto legible
// ---------------------------------------------------------------------------
const REMINDER_LABELS = {
    RECORDATORIO_1H: "Recordatorio de 1 hora enviado",
    RECORDATORIO_2H: "Recordatorio de 2 horas enviado",
    RECORDATORIO_24H: "Recordatorio de 24 horas enviado",
    RECORDATORIO: "Recordatorio enviado",
};

// ---------------------------------------------------------------------------
// Chip visual: mismo ancho y forma que el badge de Estado
// ---------------------------------------------------------------------------
function makeObservationChip(colorClasses, icon, text) {
    return `<span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${colorClasses}">
        <span>${icon}</span><span>${ui.escapeHtml(text)}</span>
    </span>`;
}

// ---------------------------------------------------------------------------
// Celda "Observaciones" de la tabla
// ---------------------------------------------------------------------------
function renderInconsistenciasCell(item) {
    const counts = getSeverityCounts(item);
    const status = item?.status || "";
    const sessionState = String(item?.session_state || "").toUpperCase();
    const parts = [];

    // --- 🔴 INCONSISTENCIAS: siempre visibles si hay alguna abierta ---
    // (independiente del status: puede estar en_progreso y aún tener inconsistencias)
    const sev = item.severity_counts || {};
    const incCritica = Number(sev.critica || 0);
    const incModerada = Number(sev.moderada || 0);
    const incLeve = Number(sev.leve || 0);
    const incTotal = Number(item.inconsistencias_count || sev.total || (incCritica + incModerada + incLeve));

    if (incTotal > 0) {
        const parts_sev = [];
        if (incLeve > 0) parts_sev.push(`${incLeve} leve${incLeve > 1 ? "s" : ""}`);
        if (incModerada > 0) parts_sev.push(`${incModerada} moderada${incModerada > 1 ? "s" : ""}`);
        if (incCritica > 0) parts_sev.push(`${incCritica} crítica${incCritica > 1 ? "s" : ""}`);
        if (parts_sev.length === 0) parts_sev.push(`${incTotal} sin grado`);

        parts.push(makeObservationChip(
            "bg-red-500/20 text-red-400",
            "", parts_sev.join(" / ")
        ));
    }

    // --- 🟠 DUDA: asesor debe revisar la pregunta ---
    if (status === "doubts") {
        parts.push(makeObservationChip(
            "bg-orange-500/20 text-orange-400",
            "", "Asesor debe revisar el caso"
        ));
    }

    // --- 💤 INACTIVA: mostrar qué recordatorios se han enviado ---
    if (status === "stalled") {
        const reminderLabel = REMINDER_LABELS[sessionState];
        if (reminderLabel) {
            parts.push(makeObservationChip(
                "bg-gray-500/20 text-gray-400",
                "", reminderLabel
            ));
        } else {
            parts.push(makeObservationChip(
                "bg-gray-500/20 text-gray-400",
                "", "Sin actividad reciente"
            ));
        }
    }

    // --- 🟣 LLAMADA: distinguir voluntaria (LLAMADA) vs 24h sin respuesta ---
    if (status === "calls") {
        const prev = String(item?.previous_state || "").toUpperCase();
        const isTimeout = prev.includes("RECORDATORIO");

        if (isTimeout) {
            parts.push(makeObservationChip(
                "bg-purple-500/20 text-purple-400",
                "", "Se necesita contactar, no contestó mensajes"
            ));
        } else {
            parts.push(makeObservationChip(
                "bg-purple-500/20 text-purple-400",
                "", "Cliente solicitó llamada"
            ));
        }
    }

    // --- Sin nada relevante ---
    if (parts.length === 0) {
        return `<span class="text-sm font-medium text-gray-900 dark:text-white">Ninguna</span>`;
    }

    return `<div class="flex min-w-0 flex-col gap-1.5">${parts.join("")}</div>`;
}

function buildRowSignature(item) {
    const counts = getSeverityCounts(item);

    return JSON.stringify([
        item.no_cuenta || "",
        item.folio || "",
        item.phone || "",
        item.status || "",
        item.session_state || "",
        item.previous_state || "",
        Number(item.progress_pct || 0),
        item.current_step || "",
        Number(item.inconsistencias_count || 0),
        counts.critica,
        counts.moderada,
        counts.leve,
        counts.unknown,
        getHighestSeverity(item) || "",
        item.last_activity || "",
        item.siga?.available ?? "",
        item.siga?.fetched_at || "",
    ]);
}

function verificationRenderKey(item = {}) {
    if (item.verification_id != null && item.verification_id !== "") {
        return `verification:${item.verification_id}`;
    }
    return `${item.session_id || ""}:${item.folio || ""}`;
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
        siga: item.siga || null,
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
        ok: "SIGA OK",
        timeout: "SIGA timeout",
        fallback_local: "SIGA fallback local",
    };

    return map[bridgeStatus] || "SIGA fallback local";
}

function sigaBridgeStatusClass(bridgeStatus) {
    const map = {
        ok: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
        timeout: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300",
        fallback_local: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
    };

    return map[bridgeStatus] || map.fallback_local;
}

function getSigaBridgeData(item = {}) {
    const bridge = ui.isPlainObject(item.siga_bridge) ? item.siga_bridge : {};
    const siga = ui.isPlainObject(item.siga)
        ? item.siga
        : (ui.isPlainObject(bridge.normalized) ? bridge.normalized : {});

    return { bridge, siga };
}

function renderPaymentLabel(payment = {}) {
    if (!ui.isPlainObject(payment) || !payment.available) {
        return "No disponible";
    }

    const parts = [];
    const planLabel = ui.safeText(payment.plan_label, "");
    const paymentsCount = Number(payment.payments_count || 0);

    if (planLabel) {
        parts.push(planLabel);
    }
    if (Number.isFinite(paymentsCount) && paymentsCount > 0) {
        parts.push(`${paymentsCount} pagos`);
    }

    return parts.join(" / ") || "Disponible";
}

function renderObjectGrid(record = {}, columns = "sm:grid-cols-2") {
    if (!ui.isPlainObject(record)) {
        return "";
    }

    const items = Object.entries(record)
        .map(([key, value]) => ({
            label: key.replace(/_/g, " "),
            value: ui.safeText(value, ""),
        }))
        .filter((item) => item.value);

    return items.length
        ? ui.renderKeyValueGrid(items, columns)
        : `<p class="text-sm text-gray-500 dark:text-slate-400">No disponible</p>`;
}

function renderComponentItem(component, index) {
    if (ui.isPlainObject(component)) {
        return `
            <div class="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-slate-700 dark:bg-slate-900/60">
                <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">
                    Componente ${index + 1}
                </div>
                ${renderObjectGrid(component)}
            </div>
        `;
    }

    const text = ui.safeText(component, "");
    if (!text) {
        return "";
    }

    return `
        <div class="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
            ${ui.escapeHtml(text)}
        </div>
    `;
}

function renderSigaBridgeSummary(item = {}) {
    const { bridge, siga } = getSigaBridgeData(item);
    if (!canUseSigaBridgeOps() && !siga.available) {
        return "";
    }

    const available = Boolean(siga.available ?? bridge.available);
    const bridgeHealthStatus = bridge.status || (available ? "ok" : "fallback_local");
    const bridgeStatusLabel = sigaBridgeStatusLabel(bridgeHealthStatus);
    const bridgeStatusClass = sigaBridgeStatusClass(bridgeHealthStatus);
    const updatedAt = ui.formatDateTime(siga.fetched_at || bridge.updated_at);
    const sourceLabel = bridge.source === "siga_bridge" && available
        ? "Datos desde SIGA"
        : "Datos locales";
    const customer = ui.isPlainObject(siga.customer) ? siga.customer : {};
    const sale = ui.isPlainObject(siga.sale) ? siga.sale : {};
    const payment = ui.isPlainObject(siga.payment) ? siga.payment : {};
    const sourceTable = ui.safeText(siga.source_table, "SIGA");
    const customerName = ui.safeText(customer.name, ui.safeText(item.name));
    const product = ui.safeText(sale.product, "No disponible");
    const balance = payment.available ? ui.formatMoney(payment.saldo, "No disponible") : "No disponible";
    const plan = renderPaymentLabel(payment);
    const cacheBadge = siga.cache_valid === false ? ui.renderBadge("Snapshot vencido", "warning") : "";

    return `
        <section class="drawer-section ${available ? "" : "drawer-section-warning"}">
            <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                    <h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">SIGA</h4>
                    <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                        <span>${ui.escapeHtml(ui.safeText(sourceLabel))}</span>
                        ${cacheBadge}
                    </div>
                </div>
                <span class="rounded-full px-2.5 py-1 text-xs font-medium ${bridgeStatusClass}">
                    ${ui.escapeHtml(ui.safeText(bridgeStatusLabel))}
                </span>
            </div>
            ${ui.renderKeyValueGrid([
        { label: "Cliente", value: customerName },
        { label: "Cuenta", value: item.no_cuenta },
        { label: "Telefono", value: item.phone },
        { label: "Saldo", value: balance },
        { label: "Plan / pagos", value: plan },
        { label: "Fuente", value: sourceTable },
        { label: "Actualizado", value: updatedAt },
    ])}
            <div class="mt-4">
                <p class="text-xs text-gray-500 dark:text-slate-400">Producto</p>
                <p class="drawer-clamp-3 mt-1 break-words text-sm font-medium text-gray-900 dark:text-white">
                    ${ui.escapeHtml(product)}
                </p>
            </div>
        </section>
    `;
}

function renderSigaDetails(item = {}) {
    if (!canUseSigaBridgeOps()) {
        return "";
    }

    const { siga } = getSigaBridgeData(item);
    if (!siga.available) {
        return "";
    }

    const sale = ui.isPlainObject(siga.sale) ? siga.sale : {};
    const payment = ui.isPlainObject(siga.payment) ? siga.payment : {};
    const components = ui.isPlainObject(siga.components) ? siga.components : {};
    const componentItems = Array.isArray(components.items) ? components.items : [];
    const product = ui.safeText(sale.product, "");
    const sections = [];

    if (product && product.length > 120) {
        sections.push(ui.renderAccordionSection({
            id: `siga-product-${item.session_id}`,
            title: "Producto completo",
            body: `<p class="whitespace-pre-wrap break-words text-sm text-gray-700 dark:text-slate-200">${ui.escapeHtml(product)}</p>`,
        }));
    }

    if (componentItems.length) {
        sections.push(ui.renderAccordionSection({
            id: `siga-components-${item.session_id}`,
            title: "Componentes",
            count: componentItems.length,
            body: `
                <div class="space-y-3">
                    ${componentItems.map(renderComponentItem).filter(Boolean).join("")}
                </div>
            `,
        }));
    }

    if (payment.available) {
        sections.push(ui.renderAccordionSection({
            id: `siga-payment-${item.session_id}`,
            title: "Pago y plan",
            body: ui.renderKeyValueGrid([
                { label: "Saldo", value: ui.formatMoney(payment.saldo, "No disponible") },
                { label: "Pago inicial", value: ui.formatMoney(payment.pago_inicial, "No disponible") },
                { label: "Pago minimo", value: ui.formatMoney(payment.pago_minimo, "No disponible") },
                { label: "Importe quincenal", value: ui.formatMoney(payment.importe_quincenal, "No disponible") },
                { label: "Importe mensual", value: ui.formatMoney(payment.importe_mensual, "No disponible") },
                { label: "Pagos registrados", value: payment.payments_count },
            ]),
        }));
    }

    return sections.join("");
}

function updateVerificationKpis(items) {
    const total = document.getElementById("kpiTotal");
    if (!total) return;

    const safeItems = Array.isArray(items) ? items : [];
    const inProgress = document.getElementById("kpiInProgress");
    const needsAttention = document.getElementById("kpiInconsistent");
    const completed = document.getElementById("kpiCompleted");

    // Statuses que requieren atención de un asesor
    const ATTENTION_STATUSES = new Set(["inconsistent", "doubts", "stalled", "calls"]);

    total.textContent = safeItems.length;
    if (inProgress) {
        inProgress.textContent = safeItems.filter((item) => item?.status === "in_progress").length;
    }
    if (needsAttention) {
        needsAttention.textContent = safeItems.filter(
            (item) => ATTENTION_STATUSES.has(item?.status)
        ).length;
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
        ? item.elementos_faltantes.map((entry) => ui.safeText(entry, "")).filter(Boolean)
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

    try {
        body.innerHTML = `
            <div class="flex h-full min-h-0 flex-col text-gray-900 dark:text-white">
                <div id="drawerHeader" class="flex-none border-b border-gray-200 bg-gray-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-900 md:px-5"></div>

                <div class="drawer-scroll space-y-4 px-4 py-4 md:px-5">
                    <section class="drawer-section">
                        <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Cliente</h4>
                        <div id="drawerCliente"></div>
                    </section>

                    <div id="drawerSigaBridge" class="hidden"></div>

                    <section class="drawer-section">
                        <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Progreso</h4>
                        <div id="drawerProgressBar"></div>
                        <div id="drawerProgressMeta" class="mt-3 flex justify-between gap-3 text-xs text-gray-500 dark:text-slate-400"></div>
                    </section>

                    <section class="drawer-section">
                        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 pb-3 dark:border-slate-700">
                            <div>
                                <h4 class="text-sm font-semibold text-gray-900 dark:text-white">Inconsistencias</h4>
                                <p id="drawerInconsistenciasMeta" class="mt-1 text-xs text-gray-500 dark:text-slate-400"></p>
                            </div>
                            <div id="drawerSeveritySummary" class="flex flex-wrap justify-end gap-2"></div>
                        </div>
                        <div id="drawerInconsistencias" class="mt-4"></div>
                    </section>

                    <div id="drawerSigaDetails" class="space-y-3"></div>
                </div>

                <div id="drawerFooter" class="flex-none border-t border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900 md:p-5"></div>
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
        const { siga } = getSigaBridgeData(item);
        const customer = ui.isPlainObject(siga.customer) ? siga.customer : {};
        const counts = getSeverityCounts(item);
        const severityHeader = counts.total
            ? renderSeverityBadge(getHighestSeverity(item), counts.total)
            : `<span class="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">Sin inconsistencias</span>`;

        const header = document.getElementById("drawerHeader");
        if (header) {
            header.innerHTML = `
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                        <h2 class="truncate text-lg font-semibold md:text-xl">
                            Folio ${ui.escapeHtml(ui.safeText(item.folio))}
                        </h2>
                        <div class="mt-2 flex flex-wrap items-center gap-2">
                            <span class="${ui.statusClass(item.status)}">
                                ${ui.escapeHtml(ui.statusLabel(item.status))}
                            </span>
                            ${severityHeader}
                        </div>
                        <div class="mt-2 text-xs text-gray-500 dark:text-slate-400">
                            Ultima actividad: ${ui.escapeHtml(ui.safeText(ui.formatDateTime(item.last_activity)))}
                        </div>
                    </div>
                    <button
                        id="drawerCloseButton"
                        type="button"
                        class="h-10 w-10 shrink-0 rounded-lg bg-gray-100 text-gray-700 transition hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
                        aria-label="Cerrar"
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
            const addressText = ui.safeText(customer.address_text, "");
            const rows = [
                { label: "Nombre", value: item.name || customer.name },
                { label: "Telefono", value: item.phone },
                { label: "Cuenta", value: item.no_cuenta },
                { label: "Folio", value: item.folio },
            ];
            if (addressText) {
                rows.push({ label: "Domicilio", value: addressText });
            }
            cliente.innerHTML = ui.renderKeyValueGrid(rows);
        }

        const sigaBridgeEl = document.getElementById("drawerSigaBridge");
        if (sigaBridgeEl) {
            const bridgeHtml = renderSigaBridgeSummary(item);
            sigaBridgeEl.innerHTML = bridgeHtml;
            sigaBridgeEl.classList.toggle("hidden", !bridgeHtml);
        }

        const sigaDetailsEl = document.getElementById("drawerSigaDetails");
        if (sigaDetailsEl) {
            const detailsHtml = renderSigaDetails(item);
            sigaDetailsEl.innerHTML = detailsHtml;
            sigaDetailsEl.classList.toggle("hidden", !detailsHtml);
        }

        const progressBar = document.getElementById("drawerProgressBar");
        if (progressBar) {
            progressBar.innerHTML = ui.renderProgressBar(item.progress_pct);
        }

        const progressMeta = document.getElementById("drawerProgressMeta");
        if (progressMeta) {
            progressMeta.innerHTML = `
                <span>${Number(item.progress_pct || 0)}%</span>
                <span class="text-right">${ui.escapeHtml(ui.safeText(item.current_step))}</span>
            `;
        }

        const inconsistenciasMeta = document.getElementById("drawerInconsistenciasMeta");
        if (inconsistenciasMeta) {
            inconsistenciasMeta.textContent = counts.total
                ? `${counts.total} registradas`
                : "Validacion sin inconsistencias abiertas";
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

            inconsistenciasEl.className = inconsistencias.length > 4
                ? "drawer-inconsistencias-list mt-4 space-y-3 pr-1"
                : "mt-4 space-y-3";

            inconsistenciasEl.innerHTML = inconsistencias.length
                ? inconsistencias.map((entry) => {
                    const isOpen = String(entry.estado || "").toUpperCase() === "ABIERTA";
                    const origin = ui.safeText(entry.estado_origen, "");

                    return `
                        <div class="rounded-lg border p-4 ${getInconsistenciaCardTone(entry)}">
                            <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                                <div class="min-w-0">
                                    <div class="flex flex-wrap items-center gap-2">
                                        <div class="text-sm font-semibold text-gray-900 dark:text-white">
                                            ${ui.escapeHtml(ui.safeText(entry.campo || entry.estado_origen, "General"))}
                                        </div>
                                        ${renderSeverityBadge(entry.severidad)}
                                        <span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${isOpen ? "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"}">
                                            ${ui.escapeHtml(isOpen ? "Abierta" : "Cerrada")}
                                        </span>
                                    </div>
                                    <div class="mt-2 whitespace-pre-wrap break-words text-sm text-gray-700 dark:text-slate-200">
                                        ${ui.escapeHtml(ui.safeText(entry.mensaje, "Sin detalle"))}
                                    </div>
                                    ${origin ? `
                                        <div class="mt-2 text-xs text-gray-500 dark:text-slate-400">
                                            Origen: ${ui.escapeHtml(origin)}
                                        </div>
                                    ` : ""}
                                    ${renderMissingElements(entry)}
                                </div>
                                ${renderResolutionActions(entry, item)}
                            </div>
                        </div>
                    `;
                }).join("")
                : `
                    <div class="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-300">
                        Sin inconsistencias
                    </div>
                `;

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
            const isRefreshing = isVerificationDetailRequestActive(item.session_id);
            const sigaUrl = ui.safeText(item.siga_url, "");
            const refreshButton = canUseSigaBridgeOps()
                ? `
                    <button
                        id="refreshSigaBridgeFooterButton"
                        type="button"
                        class="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
                        ${isRefreshing ? "disabled" : ""}
                    >
                        ${isRefreshing ? "Actualizando..." : "Actualizar SIGA"}
                    </button>
                `
                : "";
            const sigaButton = sigaUrl
                ? `
                    <button
                        id="goToSigaFooter"
                        type="button"
                        class="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
                    >
                        Ir a SIGA
                    </button>
                `
                : "";

            const verifyByCallButton = (item.session_state === "LLAMADA" || item.session_state === "ACLARACION")
                ? `
                    <button
                        id="verifyByCallFooterBtn"
                        type="button"
                        class="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-white transition hover:bg-emerald-600 shadow-sm"
                    >
                        ✔️ Verificar por llamada
                    </button>
                `
                : "";

            footer.innerHTML = `
                <div class="flex flex-col gap-2">
                    <div class="flex flex-col gap-2 sm:flex-row">
                        <button
                            id="goToChat"
                            type="button"
                            class="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-lg bg-blue-500 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-600"
                        >
                            Abrir conversacion
                        </button>
                        ${refreshButton}
                        ${sigaButton}
                    </div>
                    ${verifyByCallButton ? `<div class="flex">${verifyByCallButton}</div>` : ""}
                </div>
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

            const refreshBtn = document.getElementById("refreshSigaBridgeFooterButton");
            if (refreshBtn) {
                refreshBtn.onclick = () => {
                    void refreshVerificationDetail(item, { force: true });
                };
            }

            const sigaBtn = document.getElementById("goToSigaFooter");
            if (sigaBtn) {
                sigaBtn.onclick = () => {
                    window.goToSiga(sigaUrl);
                };
            }

            const verifyByCallBtn = document.getElementById("verifyByCallFooterBtn");
            if (verifyByCallBtn) {
                verifyByCallBtn.onclick = async () => {
                    const confirmed = await new Promise((resolve) => {
                        const overlay = document.createElement("div");
                        overlay.className = "fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm transition-opacity";

                        const modal = document.createElement("div");
                        modal.className = "bg-white dark:bg-slate-800 rounded-xl shadow-2xl p-6 w-full max-w-sm mx-4 transform scale-95 transition-transform";

                        modal.innerHTML = `
                            <div class="flex items-center gap-3 mb-4 text-emerald-600 dark:text-emerald-500">
                                <h3 class="text-lg font-bold text-slate-900 dark:text-white">Verificación por Llamada</h3>
                            </div>
                            <p class="text-sm text-slate-600 dark:text-slate-300 mb-6">
                                ¿Deseas marcar esta venta como verificada manualmente por llamada telefónica?
                            </p>
                            <div class="flex justify-end gap-3">
                                <button id="cancelCallBtn" class="px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg transition-colors">
                                    Cancelar
                                </button>
                                <button id="confirmCallBtn" class="px-4 py-2 text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-colors flex items-center shadow-sm">
                                    Confirmar
                                </button>
                            </div>
                        `;

                        overlay.appendChild(modal);
                        document.body.appendChild(overlay);

                        requestAnimationFrame(() => {
                            modal.classList.remove("scale-95");
                            modal.classList.add("scale-100");
                        });

                        const cleanup = (result) => {
                            overlay.classList.add("opacity-0");
                            setTimeout(() => {
                                if (document.body.contains(overlay)) document.body.removeChild(overlay);
                                resolve(result);
                            }, 200);
                        };

                        modal.querySelector("#cancelCallBtn").addEventListener("click", () => cleanup(false));
                        modal.querySelector("#confirmCallBtn").addEventListener("click", () => cleanup(true));
                        overlay.addEventListener("click", (e) => {
                            if (e.target === overlay) cleanup(false);
                        });
                    });

                    if (!confirmed) return;

                    verifyByCallBtn.disabled = true;
                    verifyByCallBtn.textContent = "Verificando...";

                    try {
                        await verifyByCallApi(item.session_id);
                        closeVerificationDrawer();
                    } catch (error) {
                        alert("Error al verificar por llamada: " + error.message);
                        verifyByCallBtn.disabled = false;
                        verifyByCallBtn.innerHTML = "✔️ Verificar por llamada";
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
        return activeRequest.promise;
    }

    const requestState = {
        cancelled: false,
        promise: null,
    };

    requestState.promise = (async () => {
        try {
            const latest = await getVerificationBySession(item.session_id, {
                refreshSiga: Boolean(options.force),
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
            console.warn("No se pudo refrescar detalle de verificacion:", error);
        } finally {
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
        <td data-label="No. cuenta" class="px-4 py-4">${ui.escapeHtml(ui.safeText(item.no_cuenta))}</td>
        <td data-label="Folio" class="px-4 py-4">${ui.escapeHtml(ui.safeText(item.folio))}</td>
        <td data-label="Telefono" class="px-4 py-4">${ui.escapeHtml(ui.safeText(item.phone))}</td>
        <td data-label="Estado" class="px-4 py-4">
            <span class="${ui.statusClass(item.status)}">${ui.escapeHtml(ui.statusLabel(item.status))}</span>
        </td>
        <td data-label="Progreso" class="px-4 py-4">${ui.renderProgressBar(item.progress_pct)}</td>
        <td data-label="Pregunta actual" class="px-4 py-4">${ui.escapeHtml(stepLabel(item.current_step))}</td>
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

        const rowKey = verificationRenderKey(item);
        const signature = buildRowSignature(item);
        const cached = verificationRowCache.get(rowKey) || {
            node: document.createElement("tr"),
            signature: "",
        };

        if (cached.signature !== signature) {
            updateVerificationRow(cached.node, item);
            cached.signature = signature;
        }

        cached.node.onclick = () => openVerificationDetail(item);
        verificationRowCache.set(rowKey, cached);
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

        const validKeys = new Set(items.map(verificationRenderKey).filter(Boolean));

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
    setVerificationState({ type: "loading" });

    try {
        const response = await fetchVerifications(filterStatus);
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

        setVerificationState({
            type: "error",
            message: error?.message || "Error cargando verificaciones",
        });
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
        setupVerificationRealtimeRecovery();

        lastRenderedVerificationVersion = -1;
        lastRenderedVerificationFilter = null;
        lastDrawerSessionId = null;
        lastDrawerSignature = "";
        cancelStaleVerificationDetailRequests(null);

        // Carga inicial
        void loadVerifications();

        if (unsubscribeVerificationStore) {
            unsubscribeVerificationStore();
        }

        const storeUnsubscribe = subscribeStore((state) => {
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
            }
        });

        unsubscribeVerificationStore = () => {
            storeUnsubscribe();
        };

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
