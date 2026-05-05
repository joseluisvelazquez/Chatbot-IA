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

window.toggleTheme = toggleTheme;
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

function getUserDisplayName() {
    return window.currentUser?.puesto || window.currentUser?.username || "Panel";
}

function renderNavButton(item, activePage = "", extraClass = "") {
    const activeClass = item.page === activePage
        ? "bg-blue-500 text-white"
        : "text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-700";

    return `
        <button
            type="button"
            data-page="${item.page}"
            class="flex h-9 w-9 items-center justify-center rounded-lg ${activeClass}
            active:scale-95 transition-all duration-200 ${extraClass}"
            title="${item.label}"
            aria-label="${item.label}"
        >
            <i data-lucide="${item.icon}" class="w-5 h-5"></i>
        </button>
    `;
}

function renderMobileNav(activePage = "") {
    return `
        <nav class="flex items-center gap-1 md:hidden" aria-label="Navegacion principal">
            ${NAV_ITEMS.map(item => renderNavButton(item, activePage)).join("")}
        </nav>
    `;
}

function renderHeaderNav(activePage = "") {
    return `
        <nav class="flex items-center gap-1 md:gap-3" aria-label="Navegacion principal">
            ${NAV_ITEMS.map(item => renderNavButton(item, activePage)).join("")}
        </nav>
    `;
}

function renderThemeButton() {
    return `
        <button
            type="button"
            onclick="toggleTheme()"
            class="inline-flex h-9 w-9 items-center justify-center rounded-lg
            text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-700
            active:scale-95 transition-all duration-200"
            title="Cambiar tema"
            aria-label="Cambiar tema"
        >
            <i data-lucide="moon" class="w-5 h-5"></i>
        </button>
    `;
}

function renderLogoutButton() {
    return `
        <button
            type="button"
            onclick="logout()"
            class="inline-flex h-9 w-9 items-center justify-center rounded-lg
            text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30
            active:scale-95 transition-all duration-200"
            title="Cerrar sesion"
            aria-label="Cerrar sesion"
        >
            <i data-lucide="log-out" class="w-5 h-5"></i>
        </button>
    `;
}

// =========================
// HEADER
// =========================
export function renderHeader(layout = "default", activePage = "") {
    const header = document.getElementById("header");
    if (!header) return;

    if (layout === "chat") {
        header.className =
            "h-14 flex items-center justify-between gap-2 px-3 md:px-6 bg-white dark:bg-slate-900 border-b border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white transition-colors duration-300";

        header.innerHTML = `
            <div class="flex min-w-0 items-center gap-3 md:gap-6">
                <div class="font-bold text-sky-500 transition-transform duration-200 hover:scale-105">MXCOMP</div>
                ${renderHeaderNav("conversations")}
            </div>

            <div class="flex min-w-0 items-center gap-1 md:gap-3">
                ${renderLogoutButton()}
                ${renderThemeButton()}
                <div class="hidden max-w-[11rem] truncate text-sm text-gray-700 dark:text-slate-300 sm:block">
                    ${escapeHtml(getUserDisplayName())}
                </div>
            </div>
        `;
    } else {
        header.className =
            "h-14 flex items-center justify-between gap-2 px-3 md:px-6 bg-white dark:bg-slate-800 border-b border-gray-200 dark:border-slate-700 transition-colors duration-300";

        header.innerHTML = `
            <div class="flex min-w-0 items-center gap-3 md:gap-4">
                <div class="font-bold text-blue-500 transition-transform duration-200 hover:scale-105">MXCOMP</div>
                <div class="hidden text-sm text-gray-500 dark:text-slate-400 sm:block">Sistema Operativo</div>
                ${renderMobileNav(activePage)}
            </div>

            <div class="flex min-w-0 items-center gap-1 md:gap-3">
                ${renderLogoutButton()}
                ${renderThemeButton()}
                <div class="hidden max-w-[11rem] truncate text-sm text-gray-700 dark:text-slate-200 sm:block">
                    ${escapeHtml(getUserDisplayName())}
                </div>
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
    const sidebar = document.getElementById("sidebar")
    if (!sidebar) return

    sidebar.innerHTML = `
        <div
            data-sidebar-inner
            class="flex h-full flex-col overflow-hidden bg-white dark:bg-slate-800"
        >
            <div
                data-sidebar-header
                class="mb-2 flex min-h-[40px] items-center justify-between px-3 pt-4"
            >
                <span
                    data-sidebar-brand
                    class="truncate font-bold text-sky-500 transition-transform duration-200 hover:scale-105"
                >
                    MXCOMP
                </span>

                <button
                    id="toggleSidebar"
                    type="button"
                    class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg
                    text-gray-700 hover:bg-gray-100 dark:text-slate-200 dark:hover:bg-slate-700
                    active:scale-95 transition-all duration-200"
                    title="Contraer menú"
                    aria-label="Contraer menú"
                >
                    <i data-lucide="panel-left-close" class="h-5 w-5"></i>
                </button>
            </div>

            <nav
                data-sidebar-nav
                class="flex flex-col gap-1 px-2 pb-4"
            >
                ${NAV_ITEMS.map(item => `
                    <button
                        type="button"
                        data-page="${item.page}"
                        title="${item.label}"
                        aria-label="${item.label}"
                        class="nav-item flex min-h-[40px] w-full items-center rounded-xl
                        text-left text-gray-700 dark:text-slate-200
                        hover:bg-gray-100 dark:hover:bg-slate-700
                        active:scale-[0.98] transition-all duration-200"
                    >
                        <i data-lucide="${item.icon}" class="h-5 w-5 shrink-0"></i>
                        <span data-sidebar-label class="truncate">${item.label}</span>
                    </button>
                `).join("")}
            </nav>
        </div>
    `

    if (window.lucide) {
        window.lucide.createIcons()
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
    const raw = String(value);
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
    const date = new Date(hasTimezone ? raw.replace(" ", "T") : raw.replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return "-";
    if (!hasTimezone) return raw.replace("T", " ").slice(0, 16);
    return date.toLocaleString("es-MX", { timeZone: "America/Mexico_City" });
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
        <div class="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg p-4 flex flex-col gap-2">
            <i data-lucide="${icon}" class="w-5 h-5 text-blue-500"></i>
            <h3 id="${id}" class="text-xl font-semibold">0</h3>
            <p class="text-sm text-gray-500 dark:text-slate-400">${label}</p>
        </div>
    `;
}

function renderProgressBar(percent) {
    const safe = Math.max(0, Math.min(100, percent || 0));

    return `
        <div class="flex min-w-[120px] items-center gap-2 md:min-w-[160px]">
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
