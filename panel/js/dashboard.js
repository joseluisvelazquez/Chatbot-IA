import {
    getDashboardSummary,
    getDashboardFunnel,
    getDashboardStateTimes,
    getSigaBridgeMetrics
} from "./api.js";
import { dispatch, subscribeStore, getState } from "./store.js"

let funnelChartInstance = null;
let unsubscribeDashboardStore = null
const dashboardWidgetState = {
    summaryUpdatedAt: null,
    funnelUpdatedAt: null,
    stateTimesUpdatedAt: null,
    summaryError: null,
    funnelError: null,
    stateTimesError: null,
}

function canViewSigaBridgeMetrics() {
    return ["admin", "jefe_operativo"].includes(window.currentUser?.role)
}

async function loadSummary() {
    try {
        const response = await getDashboardSummary()
        const data = response?.data ?? response ?? {}
        dashboardWidgetState.summaryUpdatedAt = new Date()
        dashboardWidgetState.summaryError = null

        dispatch({
            type: "dashboard/loaded",
            payload: data,
        })
    } catch (e) {
        dashboardWidgetState.summaryError = e?.message || "No se pudo actualizar resumen"
        renderDashboardFromState(getState())
        console.error("Error summary:", e)
    }
}

async function loadFunnel() {
    try {
        const response = await getDashboardFunnel();
        const data = response?.data ?? [];

        if (!Array.isArray(data)) {
            dashboardWidgetState.funnelError = "Funnel no disponible"
            renderFunnelPartialError(dashboardWidgetState.funnelError)
            console.error("Funnel invalido:", data);
            return;
        }

        dashboardWidgetState.funnelUpdatedAt = new Date()
        dashboardWidgetState.funnelError = null
        dispatch({
            type: "dashboard/funnel_loaded",
            payload: data,
        });
    } catch (e) {
        dashboardWidgetState.funnelError = e?.message || "No se pudo actualizar funnel"
        renderFunnelPartialError(dashboardWidgetState.funnelError)
        console.error("Error funnel:", e);
    }
}

function formatWidgetTime(value) {
    if (!value) return "Sin actualizar"
    return `Actualizado localmente ${value.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}`
}

function setText(id, value) {
    const el = document.getElementById(id)
    if (el) el.textContent = value
}

function clearKpiLoading(el) {
    if (!el) return
    el.classList.remove("animate-pulse", "rounded", "bg-slate-100", "text-transparent", "dark:bg-slate-700")
}

function renderFunnelFromState(appState) {
    const canvas = document.getElementById("funnelChart");
    if (!canvas) return;

    const data = Array.isArray(appState.dashboard.funnel)
        ? appState.dashboard.funnel
        : [];

    if (!data.length || data.every(item => sanitizeCount(item.total) === 0)) {
        renderFunnelEmptyState()
        setText("funnelUpdatedAt", formatWidgetTime(dashboardWidgetState.funnelUpdatedAt))
        renderFunnelPartialError("")
        return;
    }

    const labels = data.map(item => item.step ?? "-");
    const values = data.map(item => sanitizeCount(item.total));

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
        renderFunnelBreakdown(data)
        setText("funnelUpdatedAt", formatWidgetTime(dashboardWidgetState.funnelUpdatedAt))
        renderFunnelPartialError("")
        return;
    }

    funnelChartInstance.data.labels = labels;
    funnelChartInstance.data.datasets[0].data = values;
    funnelChartInstance.update();
    renderFunnelBreakdown(data)
    setText("funnelUpdatedAt", formatWidgetTime(dashboardWidgetState.funnelUpdatedAt))
    renderFunnelPartialError("")
}

function sanitizeCount(value) {
    const number = Number(value)
    return Number.isFinite(number) && number > 0 ? number : 0
}

function clampPercent(value) {
    const number = Number(value)
    if (!Number.isFinite(number) || number < 0) return 0
    return Math.min(100, Math.round(number))
}

function renderFunnelEmptyState() {
    const target = document.getElementById("funnelBreakdown")
    if (funnelChartInstance) {
        funnelChartInstance.data.labels = []
        funnelChartInstance.data.datasets[0].data = []
        funnelChartInstance.update()
    }
    if (target) {
        target.innerHTML = `
            <div class="md:col-span-2 xl:col-span-4 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-5 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300">
                Sin actividad del funnel en este periodo. Ajusta el rango de fechas o espera nuevas verificaciones.
            </div>
        `
    }
}

function renderFunnelBreakdown(data = []) {
    const target = document.getElementById("funnelBreakdown")
    if (!target) return

    const first = Math.max(sanitizeCount(data[0]?.total), 1)
    target.innerHTML = data.map((item, index) => {
        const total = sanitizeCount(item.total)
        const previous = index > 0 ? sanitizeCount(data[index - 1]?.total) : total
        const pct = clampPercent((total / first) * 100)
        const drop = index > 0 ? Math.max(previous - total, 0) : 0

        return `
            <div class="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/40">
                <div class="truncate text-xs font-medium text-slate-500 dark:text-slate-400">${item.step ?? "-"}</div>
                <div class="mt-1 flex items-end justify-between gap-3">
                    <span class="text-lg font-semibold text-slate-900 dark:text-slate-100">${total}</span>
                    <span class="text-xs text-slate-500 dark:text-slate-400">${pct}%</span>
                </div>
                <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                    <div class="h-full rounded-full bg-blue-600" style="width: ${pct}%"></div>
                </div>
                <div class="mt-2 text-[11px] text-slate-500 dark:text-slate-400">${index ? `Caida: ${drop}` : "Entrada del funnel"}</div>
            </div>
        `
    }).join("")
}

function renderFunnelPartialError(message = "") {
    const errorEl = document.getElementById("funnelError")
    if (!errorEl) return
    errorEl.textContent = message
    errorEl.classList.toggle("hidden", !message)
}

async function loadStateTimes() {
    try {
        const response = await getDashboardStateTimes();
        const data = response?.data ?? [];

        const tbody = document.getElementById("stateTableBody");
        if (!tbody) return;

        tbody.innerHTML = "";

        if (!Array.isArray(data)) {
            dashboardWidgetState.stateTimesError = "Tiempos no disponibles"
            renderStateTimesPartialError(dashboardWidgetState.stateTimesError)
            console.error("StateTimes invalido:", data);
            return;
        }

        dashboardWidgetState.stateTimesUpdatedAt = new Date()
        dashboardWidgetState.stateTimesError = null
        setText("stateTimesUpdatedAt", formatWidgetTime(dashboardWidgetState.stateTimesUpdatedAt))
        renderStateTimesPartialError("")
        data.forEach(row => {
            const tr = document.createElement("tr");
            tr.className =
                "border-b border-gray-100 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-700/40 transition";

            tr.innerHTML = `
                <td data-label="Transicion" class="px-4 py-4">${row.transition ?? "-"}</td>
                <td data-label="Promedio" class="px-4 py-4">${row.avg_minutes ?? 0}</td>
                <td data-label="Maximo" class="px-4 py-4">${row.max_minutes ?? 0}</td>
                <td data-label="Minimo" class="px-4 py-4">${row.min_minutes ?? 0}</td>
                <td data-label="Eventos" class="px-4 py-4">${row.count ?? 0}</td>
            `;

            tbody.appendChild(tr);
        });
    } catch (e) {
        dashboardWidgetState.stateTimesError = e?.message || "No se pudieron actualizar tiempos"
        renderStateTimesPartialError(dashboardWidgetState.stateTimesError)
        console.error("Error state times:", e);
    }
}

function renderStateTimesPartialError(message = "") {
    const errorEl = document.getElementById("stateTimesError")
    if (!errorEl) return
    errorEl.textContent = message
    errorEl.classList.toggle("hidden", !message)
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

function renderDashboardFromState(appState) {
    const d = appState.dashboard
    const summaryMeta = dashboardWidgetState.summaryError || formatWidgetTime(dashboardWidgetState.summaryUpdatedAt)

    if (d.loaded) {
        const sessionsEl = document.getElementById("kpi-sessions")
        const activeEl = document.getElementById("kpi-active")
        const inEl = document.getElementById("kpi-in")
        const outEl = document.getElementById("kpi-out")
        const issuesEl = document.getElementById("kpi-issues")

        if (sessionsEl) { clearKpiLoading(sessionsEl); sessionsEl.textContent = d.total_sessions ?? 0 }
        if (activeEl) { clearKpiLoading(activeEl); activeEl.textContent = d.active_sessions ?? 0 }
        if (inEl) { clearKpiLoading(inEl); inEl.textContent = d.messages_in ?? 0 }
        if (outEl) { clearKpiLoading(outEl); outEl.textContent = d.messages_out ?? 0 }
        if (issuesEl) { clearKpiLoading(issuesEl); issuesEl.textContent = d.issues_open ?? 0 }

        setText("kpi-sessions-meta", summaryMeta)
        setText("kpi-active-meta", summaryMeta)
        setText("kpi-in-meta", summaryMeta)
        setText("kpi-out-meta", summaryMeta)
        setText("kpi-issues-meta", summaryMeta)
        renderOperationalAlerts(d)
    } else if (dashboardWidgetState.summaryError) {
        setText("kpi-sessions-meta", summaryMeta)
        setText("kpi-active-meta", summaryMeta)
        setText("kpi-in-meta", summaryMeta)
        setText("kpi-out-meta", summaryMeta)
        setText("kpi-issues-meta", summaryMeta)
    }

    renderFunnelFromState(appState)
}

function renderOperationalAlerts(d = {}) {
    const body = document.getElementById("dashboardAlertsBody")
    if (!body) return

    const active = Number(d.active_sessions || 0)
    const total = Number(d.total_sessions || 0)
    const issues = Number(d.issues_open || 0)
    const inMessages = Number(d.messages_in || 0)
    const outMessages = Number(d.messages_out || 0)
    const responseGap = Math.max(inMessages - outMessages, 0)

    const alerts = [
        {
            title: issues > 0 ? "Inconsistencias abiertas" : "Inconsistencias bajo control",
            value: issues,
            tone: issues > 0 ? "amber" : "emerald",
            body: issues > 0 ? "Calculado con datos visibles del panel." : "Sin alertas abiertas en el resumen visible.",
        },
        {
            title: "Actividad reciente",
            value: active,
            tone: active > 0 ? "sky" : "slate",
            body: total ? `${clampPercent((active / Math.max(total, 1)) * 100)}% de sesiones visibles activas.` : "Sin sesiones visibles registradas.",
        },
        {
            title: "Brecha de mensajes",
            value: responseGap,
            tone: responseGap > 10 ? "amber" : "slate",
            body: responseGap > 0 ? "Entrantes visibles superan salientes." : "Flujo visible de mensajes equilibrado.",
        },
    ]

    const toneClasses = {
        amber: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200",
        emerald: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200",
        sky: "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-200",
        slate: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200",
    }

    body.innerHTML = alerts.map((item) => `
        <div class="rounded-lg border p-3 ${toneClasses[item.tone] || toneClasses.slate}">
            <div class="text-xs font-medium opacity-80">${item.title}</div>
            <div class="mt-1 text-xl font-semibold">${item.value}</div>
            <div class="mt-1 text-xs opacity-80">${item.body}</div>
        </div>
    `).join("")
}
