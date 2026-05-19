import {
    getDashboardSummary,
    getDashboardFunnel,
    getDashboardStateTimes,
    getSigaBridgeMetrics
} from "./api.js";
import { dispatch, subscribeStore, getState } from "./store.js"

let funnelChartInstance = null;
let unsubscribeDashboardStore = null
let dashboardRealtimeBound = false

const DASHBOARD_STATE_LABELS = {
    folio: "Folio",
    nombre: "Nombre",
    domicilio: "Domicilio",
    fecha: "Fecha venta",
    producto: "Producto",
    componentes: "Componentes",
    pagoInicial: "Pago inicial",
    pagos: "Pagos",
    bancos: "Métodos de pago",
    comprobanteAcceso: "Datos de acceso para comprobante",
    plan3meses: "Plan 3 meses",
    planes: "Otros planes",
    beneficios: "Beneficios",
    finalizado: "Finalizado",
    INFO_PAGOS: "Pagos",
    INFO_METODOS_PAGO: "Métodos de pago",
    INFO_COMPROBANTE_ACCESO: "Datos de acceso para comprobante",
    INFO_PLAN_3_MESES: "Plan 3 meses",
    INFO_OTROS_PLANES: "Otros planes",
    INFO_BENEFICIOS: "Beneficios",
    FINALIZADO: "Finalizado",
}

function dashboardLabel(key) {
    return DASHBOARD_STATE_LABELS[key] || key || "-"
}

function hasAllowedCompany() {
    return [1, 8].includes(Number(window.currentUser?.empresa_id));
}

function canViewSigaBridgeMetrics() {
    return hasAllowedCompany() && ["admin", "jefe_operativo"].includes(window.currentUser?.role);
}

async function loadSummary() {
    try {
        const response = await getDashboardSummary()
        const data = response?.data ?? response ?? {}

        dispatch({
            type: "dashboard/loaded",
            payload: data,
        })
    } catch (e) {
        console.error("Error summary:", e)
    }
}

async function loadFunnel() {
    try {
        const response = await getDashboardFunnel();
        const data = response?.data ?? [];

        if (!Array.isArray(data)) {
            console.error("Funnel invalido:", data);
            return;
        }

        dispatch({
            type: "dashboard/funnel_loaded",
            payload: data,
        });
    } catch (e) {
        console.error("Error funnel:", e);
    }
}

function renderFunnelFromState(appState) {
    const canvas = document.getElementById("funnelChart");
    if (!canvas) return;

    const data = Array.isArray(appState.dashboard.funnel)
        ? appState.dashboard.funnel
        : [];

    if (!data.length) return;

    const labels = data.map(item => dashboardLabel(item.step));
    const values = data.map(item => item.total ?? 0);

    if (funnelChartInstance && funnelChartInstance.canvas !== canvas) {
        funnelChartInstance.destroy();
        funnelChartInstance = null;
    }

    if (!funnelChartInstance) {
        funnelChartInstance = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Usuarios",
                        data: values
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
        return;
    }

    funnelChartInstance.data.labels = labels;
    funnelChartInstance.data.datasets[0].data = values;
    funnelChartInstance.update();
}

async function loadStateTimes() {
    try {
        const response = await getDashboardStateTimes();
        const data = response?.data ?? [];

        const tbody = document.getElementById("stateTableBody");
        if (!tbody) return;

        tbody.innerHTML = "";

        if (!Array.isArray(data)) {
            console.error("StateTimes invalido:", data);
            return;
        }

        data.forEach(row => {
            const tr = document.createElement("tr");
            tr.className =
                "border-b border-gray-100 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-700/40 transition";

            const transitionLabel = row.from_state || row.to_state
                ? `${dashboardLabel(row.from_state)} → ${dashboardLabel(row.to_state)}`
                : (row.transition ?? "-");

            tr.innerHTML = `
                <td data-label="Transicion" class="px-4 py-4">${transitionLabel}</td>
                <td data-label="Promedio" class="px-4 py-4">${row.avg_minutes ?? 0}</td>
                <td data-label="Maximo" class="px-4 py-4">${row.max_minutes ?? 0}</td>
                <td data-label="Minimo" class="px-4 py-4">${row.min_minutes ?? 0}</td>
                <td data-label="Eventos" class="px-4 py-4">${row.count ?? 0}</td>
            `;

            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Error state times:", e);
    }
}

async function loadSigaBridgeMetrics() {
    const panel = document.getElementById("sigaBridgeMetricsPanel")
    if (!panel || !canViewSigaBridgeMetrics()) {
        return
    }

    panel.classList.remove("hidden")

    try {
        const metrics = await getSigaBridgeMetrics()
        renderSigaBridgeMetrics(metrics || {})
    } catch (e) {
        const errorEl = document.getElementById("sigaBridgeMetricsError")
        if (errorEl) {
            errorEl.textContent = "Metricas SIGA no disponibles"
            errorEl.classList.remove("hidden")
        }
        console.warn("Error SIGA Bridge metrics:", e)
    }
}

function renderMetricValue(id, value) {
    const el = document.getElementById(id)
    if (el) el.textContent = value
}

function renderSigaBridgeMetrics(metrics) {
    const errors = metrics.errors || {}
    const hitRatio = Number(metrics.cache_hit_ratio || 0)

    renderMetricValue("sigaBridgeLatency", `${Number(metrics.avg_latency_ms || 0).toFixed(2)} ms`)
    renderMetricValue("sigaBridgeCacheHit", `${Math.round(hitRatio * 100)}%`)
    renderMetricValue("sigaBridgeTimeouts", metrics.timeouts ?? 0)
    renderMetricValue("sigaBridgeRateLimits", metrics.rate_limit_hits ?? errors["429"] ?? 0)
    renderMetricValue("sigaBridge400", errors["400"] ?? 0)
    renderMetricValue("sigaBridge401", errors["401"] ?? 0)
    renderMetricValue("sigaBridge429", errors["429"] ?? 0)
    renderMetricValue("sigaBridge500", errors["500"] ?? 0)
}

export function initDashboardPage() {
    setupDashboardRealtimeRecovery()
    loadSummary()
    loadFunnel()
    loadStateTimes()
    loadSigaBridgeMetrics()

    if (unsubscribeDashboardStore) unsubscribeDashboardStore()

    unsubscribeDashboardStore = subscribeStore((appState) => {
        renderDashboardFromState(appState)
    })

    renderDashboardFromState(getState())
}

function setupDashboardRealtimeRecovery() {
    if (dashboardRealtimeBound) return

    window.addEventListener("panel:ws-reconnected", () => {
        if (!document.getElementById("kpi-sessions")) return
        loadSummary()
        loadFunnel()
        loadStateTimes()
        loadSigaBridgeMetrics()
    })

    dashboardRealtimeBound = true
}

function renderDashboardFromState(appState) {
    const d = appState.dashboard

    if (d.loaded) {
        const sessionsEl = document.getElementById("kpi-sessions")
        const activeEl = document.getElementById("kpi-active")
        const inEl = document.getElementById("kpi-in")
        const outEl = document.getElementById("kpi-out")
        const issuesEl = document.getElementById("kpi-issues")

        if (sessionsEl) sessionsEl.textContent = d.total_sessions ?? 0
        if (activeEl) activeEl.textContent = d.active_sessions ?? 0
        if (inEl) inEl.textContent = d.messages_in ?? 0
        if (outEl) outEl.textContent = d.messages_out ?? 0
        if (issuesEl) issuesEl.textContent = d.issues_open ?? 0
    }

    renderFunnelFromState(appState)
}
