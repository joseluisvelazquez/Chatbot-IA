// =========================
// UTILIDADES
// =========================
function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// =========================
// NAV ITEMS (FUENTE ÚNICA)
// =========================
const NAV_ITEMS = [
    { page: "dashboard", icon: "home", label: "Dashboard" },
    { page: "conversations", icon: "message-circle", label: "Conversaciones" },
    { page: "verifications", icon: "clipboard-list", label: "Verificaciones" },
    { page: "cobranza", icon: "wallet", label: "Cobranza" }
];

// =========================
// HEADER DINÁMICO
// =========================
export function renderHeader(layout = "default") {
    const header = document.getElementById("header");
    if (!header) return;

    // =====================
    // DEFAULT (HEADER NORMAL)
    // =====================
    if (layout === "default") {
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

    // =====================
    // CHAT MODE (🔥 NAVBAR)
    // =====================
    if (layout === "chat") {
        header.innerHTML = `
            <div class="header-left">

                <div class="logo">MXCOMP</div>

                <div class="nav-horizontal">
                    ${NAV_ITEMS.map(item => `
                        <div class="nav-item" data-page="${item.page}">
                            <i data-lucide="${item.icon}"></i>
                            <span>${item.label}</span>
                        </div>
                    `).join("")}
                </div>

            </div>

            <div class="header-right">
                <div class="icon-btn">🔍</div>
                <div class="icon-btn">🔔</div>
                <div class="icon-btn">👤</div>
            </div>
        `;
    }

    // 🔥 re-render iconos
    if (window.lucide) {
        lucide.createIcons();
    }

    // 🔥 bind navegación
    bindHeaderNavigation();
}

// =========================
// SIDEBAR GLOBAL
// =========================
export function renderSidebar() {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;

    sidebar.innerHTML = `
        <div class="sidebar">

            <div class="sidebar-header">
                <span class="logo">MXCOMP</span>
                <button id="toggleSidebar">☰</button>
            </div>

            <div class="sidebar-menu">
                ${NAV_ITEMS.map(item => `
                    <div class="nav-item" data-page="${item.page}">
                        <i data-lucide="${item.icon}"></i>
                        <span>${item.label}</span>
                    </div>
                `).join("")}
            </div>

        </div>
    `;

    if (window.lucide) {
        lucide.createIcons();
    }
}

// =========================
// NAVIGATION (HEADER + SIDEBAR)
// =========================
function bindHeaderNavigation() {
    const items = document.querySelectorAll(".nav-item");

    items.forEach(item => {
        item.onclick = () => {
            const page = item.dataset.page;

            // lazy import para evitar circular deps
            import("./app.js").then(({ navigateTo }) => {
                navigateTo(page);
            });
        };
    });
}

// =========================
// UTILIDADES UI
// =========================
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

// =========================
// EXPORT GLOBAL UI
// =========================
window.ui = {
    escapeHtml,
    formatDateTime,
    statusLabel,
    statusClass,
    renderProgressBar
};