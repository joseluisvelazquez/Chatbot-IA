import { renderHeader, renderSidebar } from "./ui.js";
import { initVerificationsPage } from "./verifications.js";
import { initConversationsPage, loadChat } from "./chat.js";
import { initDashboardPage } from "./dashboard.js";
import { initSidebar } from "./sidebar.js";
import { setLayout } from "./layoutmanager.js";


// =========================
// CONFIG
// =========================

const PAGE_CONFIG = {
    dashboard: {
        path: "/pages/dashboard.html",
        layout: "default",
        init: initDashboardPage
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
// STATE
// =========================

const viewCache = {};
let isNavigating = false;
// ====== ESTADO TEMPORAL ======
let selectedSessionId = null

export function setSelectedSession(sessionId) {
    selectedSessionId = sessionId
}

export function consumeSelectedSession() {
    const id = selectedSessionId
    selectedSessionId = null
    return id
}

// =========================
// HELPERS
// =========================

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// =========================
// ANIMACIONES
// =========================

async function animateContentOut(content) {
    content.classList.add(
        "opacity-0",
        "translate-y-1",
        "transition-all",
        "duration-200"
    );
    await sleep(180);
}

async function animateContentIn(content) {
    content.classList.remove("opacity-0", "translate-y-1");
    content.classList.add("opacity-100");
}

// =========================
// LOAD VIEW
// =========================

async function loadView(path) {
    const content = document.getElementById("content");
    if (!content) throw new Error("No se encontró #content");

    if (viewCache[path]) {
        content.innerHTML = "";
        content.appendChild(viewCache[path].cloneNode(true));
        return;
    }

    const res = await fetch(path);

    if (!res.ok) {
        throw new Error(`No se pudo cargar la vista: ${path}`);
    }

    const html = await res.text();

    const wrapper = document.createElement("div");
    wrapper.className = "w-full h-full flex flex-col min-w-0 min-h-0";
    wrapper.innerHTML = html;

    viewCache[path] = wrapper.cloneNode(true);

    content.innerHTML = "";
    content.appendChild(wrapper);
}

// =========================
// NAVEGACIÓN
// =========================

export async function navigateTo(page, push = true) {

    if (isNavigating) return;

    const config = PAGE_CONFIG[page];
    if (!config) {
        console.warn(`Página no registrada: ${page}`);
        return;
    }

    const content = document.getElementById("content");
    if (!content) return;

    try {
        isNavigating = true;

        const url = new URL(window.location);

        // 🔥 SIEMPRE SET VIEW
        url.searchParams.set("view", page);

        // 🔥 LIMPIAR PARAMS SOLO SI NO ES CHAT
        if (page !== "conversations") {
            url.searchParams.delete("session_id");
            url.searchParams.delete("phone");
        }

        if (push) {
            window.history.pushState({}, "", url);
        }

        await animateContentOut(content);

        setLayout(config.layout);
        renderHeader(config.layout);

        if (config.layout === "default") {
            renderSidebar();
            initSidebar(page);
        }

        await loadView(config.path);

        if (typeof config.init === "function") {
            config.init();
        }
        

        if (window.lucide) {
            lucide.createIcons();
        }

        await animateContentIn(content);

    } catch (error) {
        console.error("Error navegando:", error);

        content.innerHTML = `
            <div class="m-4 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-300">
                Error cargando el panel: ${error.message}
            </div>
        `;
    } finally {
        isNavigating = false;
    }
}

// =========================
// EVENTS
// =========================

function bindEvents() {

    document.addEventListener("click", (e) => {

        const btn = e.target.closest(".btn-primary");

        if (btn) {

            const sessionId = btn.dataset.sessionId;

            const url = new URL(window.location);

            url.searchParams.set("view", "conversations");

            if (sessionId) {
                url.searchParams.set("session_id", sessionId);
            }

            window.history.pushState({}, "", url);

            navigateTo("conversations", false);
            return;
        }
    });
}

// =========================
// INIT
// =========================

function initApp() {

    const params = new URLSearchParams(window.location.search);
    const view = params.get("view") || "verifications";

    navigateTo(view, false);
}

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    initApp();
});

window.addEventListener("popstate", () => {
    const params = new URLSearchParams(window.location.search);
    const view = params.get("view") || "verifications";
    navigateTo(view, false);
});