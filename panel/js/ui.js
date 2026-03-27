import { navigateTo } from "./app.js";

// =========================
// UTILIDADES
// =========================
function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function loadTheme() {
    const saved = localStorage.getItem("theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;

    if (saved === "dark" || (!saved && prefersDark)) {
        document.documentElement.classList.add("dark");
    } else {
        document.documentElement.classList.remove("dark");
    }
}

function toggleTheme() {
    const root = document.documentElement;
    const isDark = root.classList.toggle("dark");
    localStorage.setItem("theme", isDark ? "dark" : "light");
}

// hacerlo global porque lo llamas inline desde header
window.toggleTheme = toggleTheme;

// cargar tema al importar módulo
loadTheme();

// =========================
// NAV ITEMS
// =========================
const NAV_ITEMS = [
    { page: "dashboard", icon: "home", label: "Dashboard" },
    { page: "conversations", icon: "message-circle", label: "Conversaciones" },
    { page: "verifications", icon: "clipboard-list", label: "Verificaciones" },
    { page: "cobranza", icon: "wallet", label: "Cobranza" }
];

// =========================
// HEADER
// =========================
export function renderHeader(layout = "default") {
    const header = document.getElementById("header");
    if (!header) return;

    if (layout === "chat") {
        header.className =
            "h-14 flex items-center justify-between px-4 md:px-6 bg-white dark:bg-slate-900 border-b border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white transition-colors duration-300";

        header.innerHTML = `
            <div class="flex items-center gap-6">
                <div class="font-bold text-sky-500 transition-transform duration-200 hover:scale-105">MXCOMP</div>

                <nav class="flex items-center gap-3">
                    ${NAV_ITEMS.map(item => `
                        <button
                            type="button"
                            data-page="${item.page}"
                            class="flex items-center justify-center rounded-lg p-2
                            hover:bg-gray-100 dark:hover:bg-slate-700
                            active:scale-95 transition-all duration-200"
                            title="${item.label}"
                        >
                            <i data-lucide="${item.icon}" class="w-5 h-5"></i>
                        </button>
                    `).join("")}
                </nav>
            </div>

            <div class="flex items-center gap-3">
                <button
                    type="button"
                    onclick="toggleTheme()"
                    class="inline-flex h-8 w-10 items-center justify-center rounded-md
                    hover:bg-gray-100 dark:hover:bg-slate-700 active:scale-95
                    transition-all duration-200"
                >
                    🌙
                </button>

                <div class="text-sm text-gray-700 dark:text-slate-300">
                    Admin
                </div>
            </div>
        `;
    } else {
        header.className =
            "h-14 flex items-center justify-between px-6 bg-white dark:bg-slate-800 border-b border-gray-200 dark:border-slate-700 transition-colors duration-300";

        header.innerHTML = `
            <div class="flex items-center gap-4">
                <div class="font-bold text-blue-500 transition-transform duration-200 hover:scale-105">MXCOMP</div>
                <div class="text-sm text-gray-500 dark:text-slate-400">Sistema Operativo</div>
            </div>

            <div class="flex items-center gap-3">
                <button onclick="toggleTheme()"
                    class="inline-flex h-8 w-10 items-center justify-center rounded-md
                    text-gray-700 dark:text-slate-200
                        hover:bg-gray-100 dark:hover:bg-slate-700 active:scale-95 transition-all duration-200">
                    🌙
                </button>
                <div class="text-sm text-gray-700 dark:text-slate-200">Admin</div>
            </div>
        `;
    }

    if (window.lucide) lucide.createIcons();
    bindHeaderNavigation();
}

// =========================
// SIDEBAR
// =========================
export function renderSidebar() {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;

    sidebar.innerHTML = `
        <div class="h-full flex flex-col p-4 gap-2 bg-white dark:bg-slate-800 border-r border-gray-200 dark:border-slate-700 transition-colors duration-300">
            <div class="mb-2 flex items-center justify-between">
                <span class="font-bold text-sky-500 transition-transform duration-200 hover:scale-105">MXCOMP</span>
                <button
                    id="toggleSidebar"
                    type="button"
                    class="rounded-lg p-2 hover:bg-gray-100 dark:hover:bg-slate-700 active:scale-95 transition-all duration-200"
                >
                    <i data-lucide="panel-left-close" class="w-5 h-5"></i>
                </button>
            </div>

            <nav class="flex flex-col gap-1">
                ${NAV_ITEMS.map(item => `
                    <button
                        type="button"
                        class="nav-item flex items-center gap-3 rounded-lg px-3 py-2 text-left
                        text-gray-700 dark:text-slate-200
                        hover:bg-gray-100 dark:hover:bg-slate-700
                        active:scale-[0.98]
                        transition-all duration-200"
                        data-page="${item.page}"
                    >
                        <i data-lucide="${item.icon}" class="w-5 h-5"></i>
                        <span>${item.label}</span>
                    </button>
                `).join("")}
            </nav>
        </div>
    `;

    if (window.lucide) {
        lucide.createIcons();
    }
}
// =========================
// NAVIGATION
// =========================
function bindHeaderNavigation() {
    document.querySelectorAll("[data-page]").forEach((item) => {
        item.onclick = () => {
            const page = item.dataset.page;
            if (page) navigateTo(page);
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
        in_progress: "bg-yellow-500/20 text-yellow-400",
        inconsistent: "bg-red-500/20 text-red-400",
        human_required: "bg-blue-500/20 text-blue-400",
        stalled: "bg-gray-500/20 text-gray-400",
        completed: "bg-green-500/20 text-green-400"
    };

    return `inline-flex items-center px-2.5 py-1 text-xs rounded-full font-medium ${map[status] || "bg-gray-400/20 text-gray-300"}`;
}
function kpiCard(icon, id, label) {
    return `
        <div class="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-xl p-4 flex flex-col gap-2">
            <i data-lucide="${icon}" class="w-5 h-5 text-blue-500"></i>
            <h3 id="${id}" class="text-xl font-semibold">0</h3>
            <p class="text-sm text-gray-500 dark:text-slate-400">${label}</p>
        </div>
    `;
}

function renderProgressBar(percent) {
    const safe = Math.max(0, Math.min(100, percent || 0));

    return `
        <div class="flex items-center gap-2 min-w-[160px]">
            <div class="w-full h-2 bg-gray-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div class="h-full bg-blue-500 transition-all" style="width: ${safe}%"></div>
            </div>
            <span class="text-xs text-gray-500 dark:text-slate-400">${safe}%</span>
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

window.ui.kpiCard = kpiCard;