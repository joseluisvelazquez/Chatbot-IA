import {
    getDashboardSummary,
    getDashboardFunnel,
    getDashboardStateTimes
} from "./api.js";

let funnelChartInstance = null;

async function loadSummary() {
    try {
        const response = await getDashboardSummary();
        const data = response?.data ?? response ?? {};

        document.getElementById("kpi-sessions").textContent = data.total_sessions ?? 0;
        document.getElementById("kpi-active").textContent = data.active_sessions ?? 0;
        document.getElementById("kpi-in").textContent = data.messages_in ?? 0;
        document.getElementById("kpi-out").textContent = data.messages_out ?? 0;
        document.getElementById("kpi-issues").textContent = data.issues_open ?? 0;
    } catch (e) {
        console.error("Error summary:", e);
    }
}

async function loadFunnel() {
    try {
        const response = await getDashboardFunnel();
        const data = response?.data ?? [];

        const canvas = document.getElementById("funnelChart");
        if (!canvas) return;

        if (!Array.isArray(data)) {
            console.error("Funnel inválido:", data);
            return;
        }

        const labels = data.map(item => item.state ?? "-");
        const values = data.map(item => item.total ?? 0);

        if (funnelChartInstance) {
            funnelChartInstance.destroy();
        }

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
    } catch (e) {
        console.error("Error funnel:", e);
    }
}

async function loadStateTimes() {
    try {
        const response = await getDashboardStateTimes();
        const data = response?.data ?? [];

        const tbody = document.getElementById("stateTableBody");
        if (!tbody) return;

        tbody.innerHTML = "";

        if (!Array.isArray(data)) {
            console.error("StateTimes inválido:", data);
            return;
        }

        data.forEach(row => {
            const tr = document.createElement("tr");
            tr.className =
                "border-b border-gray-100 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-700/40 transition";

            tr.innerHTML = `
                <td class="px-4 py-4">${row.transition ?? "-"}</td>
                <td class="px-4 py-4">${row.avg_minutes ?? 0}</td>
                <td class="px-4 py-4">${row.max_minutes ?? 0}</td>
                <td class="px-4 py-4">${row.min_minutes ?? 0}</td>
                <td class="px-4 py-4">${row.count ?? 0}</td>
            `;

            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Error state times:", e);
    }
}

export function initDashboardPage() {
    loadSummary();
    loadFunnel();
    loadStateTimes();
}