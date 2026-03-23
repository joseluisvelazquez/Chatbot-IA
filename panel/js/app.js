import { renderHeader, renderSidebar } from "./ui.js";
import { initVerificationsPage } from "./verifications.js";
import { initConversationsPage } from "./chat.js";
import { initSidebar } from "./sidebar.js";
import { setLayout } from "./layoutmanager.js";

// =========================
// CONFIG DE VISTAS
// =========================
const PAGE_CONFIG = {
    dashboard: {
        path: "/pages/dashboard.html",
        layout: "default",
        init: null
    },
    conversations: {
        path: "/pages/conversaciones.html",
        layout: "chat",
        init: initConversationsPage
    },
    verifications: {
        path: "/pages/verificaciones.html",
        layout: "default",
        init: initVerificationsPage
    },
    cobranza: {
        path: "/pages/cobranza.html",
        layout: "default",
        init: null
    }
};

// =========================
// LOAD VIEW
// =========================
async function loadView(path) {
    const content = document.getElementById("content");
    if (!content) {
        throw new Error("No se encontró el contenedor #content");
    }

    const res = await fetch(path);

    if (!res.ok) {
        throw new Error(`No se pudo cargar la vista: ${path}`);
    }

    const html = await res.text();
    content.innerHTML = html;
}

// =========================
// NAVEGACIÓN CENTRAL
// =========================
export async function navigateTo(page) {
    const config = PAGE_CONFIG[page];

    if (!config) {
        console.warn(`Página no registrada: ${page}`);
        return;
    }

    try {
        // 1) aplicar layout
        setLayout(config.layout);

        // 2) renderizar header según layout
        renderHeader(config.layout);

        // 3) sidebar global solo se mantiene en layout default
        if (config.layout === "default") {
            renderSidebar();
            initSidebar(page);
        }

        // 4) cargar vista
        await loadView(config.path);

        // 5) inicializar vista si aplica
        if (typeof config.init === "function") {
            config.init();
        }

        // 6) re-render iconos
        if (window.lucide) {
            lucide.createIcons();
        }

    } catch (error) {
        console.error("Error navegando:", error);

        const content = document.getElementById("content");
        if (content) {
            content.innerHTML = `
                <div class="table-state error">
                    Error cargando el panel: ${error.message}
                </div>
            `;
        }
    }
}

// =========================
// DRAWER
// =========================
function closeDrawer() {
    const drawer = document.getElementById("drawer");
    const overlay = document.getElementById("drawerOverlay");

    if (drawer) drawer.classList.remove("open");
    if (overlay) overlay.classList.remove("active");
}

// =========================
// EVENTOS GLOBALES
// =========================
function bindGlobalEvents() {
    document.addEventListener("click", (e) => {
        const conversationBtn = e.target.closest(".btn-primary");
        if (conversationBtn) {
            const phone = conversationBtn.dataset.phone || null;
            window.selectedPhone = phone;
            navigateTo("conversations");
            return;
        }

        if (e.target.closest("#closeDrawer")) {
            closeDrawer();
            return;
        }

        if (e.target.id === "drawerOverlay") {
            closeDrawer();
        }
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeDrawer();
        }
    });

    window.toggleSidebar = function () {
        const sidebar = document.getElementById("sidebar");
        if (!sidebar) return;
        sidebar.classList.toggle("collapsed");
    };
}

// =========================
// APP INIT
// =========================
async function initApp() {
    try {
        // layout inicial
        setLayout("default");

        // render base
        renderHeader("default");
        renderSidebar();
        initSidebar("verifications");

        // vista inicial
        await navigateTo("verifications");

    } catch (error) {
        console.error("Error inicializando app:", error);

        const content = document.getElementById("content");
        if (content) {
            content.innerHTML = `
                <div class="table-state error">
                    Error cargando el panel: ${error.message}
                </div>
            `;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    bindGlobalEvents();
    initApp();
});