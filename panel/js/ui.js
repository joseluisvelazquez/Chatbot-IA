function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// 🔥 HEADER
export function renderHeader() {
    const header = document.getElementById("header");

    if (!header) {
        console.warn("Header no encontrado en DOM");
        return;
    }

    header.innerHTML = `
        <div class="header-left">
            <div class="logo">MXCOMP</div>
            <div class="subtitle">Sistema Operativo</div>
        </div>

        <div class="header-right">
            <div class="icon-btn">🔍</div>
            <div class="icon-btn">🔔</div>
            <div class="icon-btn">👤 Admin</div>
        </div>
    `;

}

// 🔥 SIDEBAR
export function renderSidebar() {
    const sidebar = document.getElementById("sidebar");

    sidebar.innerHTML = `
        <div class="sidebar">

            <div class="sidebar-header">
                <span class="logo">MXCOMP</span>
                <button id="toggleSidebar">☰</button>
            </div>

            <div class="sidebar-menu" d>

                <div class="nav-item" data-page="dashboard">
                    <i data-lucide="home"></i>
                    <span>Dashboard</span>
                </div>

                <div class="nav-item"  data-page="conversations">
                    <i data-lucide="message-circle"></i>
                    <span>Conversaciones</span>
                </div>

                <div class="nav-item"  data-page="verifications">
                    <i data-lucide="clipboard-list"></i>
                    <span>Verificaciones</span>
                </div>

                <div class="nav-item" data-page="cobranza">
                    <i data-lucide="wallet"></i>
                    <span>Cobranza</span>
                </div>

            </div>

        </div>
    `;

    // 🔥 render iconos
    if (window.lucide) {
        lucide.createIcons();
    }
}
// 🔥 UTILIDADES UI
function formatDateTime(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return date.toLocaleString("es-MX");
}

function statusLabel(status) {
    const map = {
        in_progress: "En proceso",
        inconsistent: "Inconsistencias",
        human_required: "Asesor",
        stalled: "Inactiva",
        completed: "Finalizada"
    };
    return map[status] || status || "-";
}

function statusClass(status) {
    const map = {
        in_progress: "badge warning",
        inconsistent: "badge danger",
        human_required: "badge info",
        stalled: "badge muted",
        completed: "badge success"
    };
    return map[status] || "badge";
}

function renderProgressBar(percent) {
    const safe = Math.max(0, Math.min(100, percent || 0));

    return `
        <div class="progress-cell">
            <div class="progress-track">
                <div class="progress-fill" style="width: ${safe}%"></div>
            </div>
            <span>${safe}%</span>
        </div>
    `;
}

window.ui = {
    escapeHtml,
    formatDateTime,
    statusLabel,
    statusClass,
    renderProgressBar
};