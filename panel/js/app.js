import { renderHeader, renderSidebar } from "./ui.js";
import { initVerificationsPage } from "./verifications.js";
import { initConversationsPage } from "./chat.js";
import { initDashboardPage } from "./dashboard.js";
import { initSidebar } from "./sidebar.js";
import { setLayout } from "./layoutmanager.js";
import { getAuthUrl, getPanelHomeUrl, getPanelPageUrl, isLocalPanelEnvironment } from "./config.js";
import { initWebSocket } from "./websocket.js"
import { dispatch, getState } from "./store.js"


// =========================
// CONFIG
// =========================
const PAGE_CONFIG = {
    dashboard: {
        path: getPanelPageUrl("pages/dashboard.html"),
        layout: "default",
        init: initDashboardPage
    },
    conversations: {
        path: getPanelPageUrl("pages/conversaciones.html"),
        layout: "chat",
        init: initConversationsPage
    },
    verifications: {
        path: getPanelPageUrl("pages/verificaciones.html"),
        layout: "default",
        init: initVerificationsPage
    },
    cobranza: {
        path: getPanelPageUrl("pages/cobranza.html"),
        layout: "default",
        init: null
    }
};
export function startSessionHeartbeat() {
    setInterval(async () => {
        try {
            const res = await fetch(getAuthUrl("me"), {
                credentials: "include"
            })

            if (!res.ok) {
                renderSessionExpired()
            }

        } catch (error) {
            console.warn("Heartbeat error:", error)
            renderNetworkError()
        }
    }, 120000) // 2 minutos
}
export function startSessionTimeout() {
    if (!window.currentUser?.exp) return

    const now = Date.now()
    const exp = window.currentUser.exp * 1000

    const timeout = exp - now

    if (timeout <= 0) {
        renderSessionExpired()
        return
    }

    setTimeout(() => {
        renderSessionExpired()
    }, timeout)
}
// =========================
// STATE
// =========================

const viewCache = {};
let isNavigating = false;
// ====== ESTADO TEMPORAL ======
let selectedSession = null

export function setSelectedSession(session) {
    if (session == null) {
        selectedSession = null
        localStorage.removeItem("lastSession")
        dispatch({
            type: "chat/select_session",
            payload: null
        })
        return
    }

    const normalized =
        typeof session === "object"
            ? {
                sessionId: Number(session.sessionId ?? session.id ?? session.session_id),
                phone: session.phone ?? null,
                name: session.name ?? null
            }
            : {
                sessionId: Number(session),
                phone: null,
                name: null
            }

    if (!normalized.sessionId || Number.isNaN(normalized.sessionId)) {
        return
    }

    selectedSession = normalized
    localStorage.setItem("lastSession", JSON.stringify(normalized))
    dispatch({
        type: "chat/select_session",
        payload: normalized
    })
}

export function getSelectedSession() {
    const stateSelected = getState().chat.selectedSession
    return stateSelected || selectedSession
}

// =========================
// HELPERS
// =========================

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
// =========================
// RENDERIZADOS GENERALES
// =========================
function renderLoading() {
    let loader = document.getElementById("globalLoader")

    if (loader) return

    loader = document.createElement("div")
    loader.id = "globalLoader"

    loader.className = `
        fixed inset-0 z-[9999]
        flex items-center justify-center
        bg-slate-900
    `

    loader.innerHTML = `
        <div class="text-center text-white">
            <div class="animate-spin rounded-full h-10 w-10 border-2 border-green-400 border-t-transparent mx-auto mb-4"></div>
            <p class="text-sm text-slate-400">
                Verificando sesión...
            </p>
        </div>
    `

    document.body.appendChild(loader)
}
function removeLoading() {
    const loader = document.getElementById("globalLoader")
    if (loader) loader.remove()
}
// =========================
// AUTH
// =========================
export function renderSessionExpired() {
    // limpiar estado
    window.currentUser = null
    localStorage.removeItem("lastSession")

    const root = document.getElementById("app")

    root.innerHTML = `
        <div class="h-screen flex items-center justify-center bg-slate-900">
            <div class="bg-slate-800 p-8 rounded-xl text-center max-w-md w-full border border-slate-700">

                <div class="text-4xl mb-4">⏳</div>

                <h1 class="text-xl font-semibold mb-2 text-white">
                    Sesión expirada
                </h1>

                <p class="text-sm text-slate-400 mb-4">
                    Tu sesión ha expirado por seguridad.
                </p>

                <button onclick="location.reload()"
                    class="mt-4 px-4 py-2 bg-green-500 text-black rounded-lg">
                    Reingresar
                </button>

            </div>
        </div>
    `
}
export function renderNetworkError() {
    const root = document.getElementById("app")

    root.innerHTML = `
        <div class="h-screen flex items-center justify-center bg-slate-900">
            <div class="bg-slate-800 p-8 rounded-xl text-center max-w-md w-full border border-red-500">

                <div class="text-4xl mb-4">⚠️</div>

                <h1 class="text-xl font-semibold mb-2 text-white">
                    Error de conexión
                </h1>

                <p class="text-sm text-slate-400 mb-4">
                    No se pudo conectar con el servidor.
                </p>

                <p class="text-xs text-red-400">
                    Verifica la conexión con el servidor del panel e inténtalo de nuevo.
                </p>

            </div>
        </div>
    `
}
function renderUnauthorized(message = "Debes acceder desde SIGA para continuar.") {
    const root = document.getElementById("app")

    if (!root) return

    root.innerHTML = `
        <div class="h-screen w-full flex items-center justify-center bg-slate-900">
            
            <div class="bg-slate-800 text-white rounded-xl shadow-xl p-8 max-w-md w-full text-center border border-slate-700">

                <div class="text-4xl mb-4">🔒</div>

                <h1 class="text-xl font-semibold mb-2">
                    Acceso no autorizado
                </h1>

                <p class="text-sm text-slate-400 mb-4">
                    ${message}
                </p>

                <div class="text-xs text-slate-500">
                    Si el problema persiste, contacta a sistemas.
                </div>

            </div>

        </div>
    `
}
export async function logout() {
    try {
        await fetch(getAuthUrl("logout"), {
            method: "POST",
            credentials: "include"
        })
    } catch (e) {
        console.warn("Logout error:", e)
    }

    // limpiar estado
    window.currentUser = null
    localStorage.removeItem("lastSession")

    // reload limpio
    window.location.href = getPanelHomeUrl()
}
async function initAuth() {
    const params = new URLSearchParams(window.location.search)
    const token = params.get("token")

    try {

        // 🔐 1. SI VIENE TOKEN → hacer exchange
        if (token) {
            const res = await fetch(getAuthUrl("exchange"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ token })
            })

            if (!res.ok) {
                renderUnauthorized("Token inválido o expirado")
                return false
            }

            // limpiar URL
            window.history.replaceState({}, document.title, window.location.pathname)
        }

        // 🔐 2. SIEMPRE intentar validar sesión (cookie)
        const me = await fetch(getAuthUrl("me"), {
            credentials: "include"
        })

        if (me.ok) {
            const user = await me.json()
            window.currentUser = user

            startSessionHeartbeat()
            startSessionTimeout()

            return true
        }

        // 🔐 3. SI NO hay sesión → fallback

        if (isLocalPanelEnvironment()) {
            const res = await fetch(getAuthUrl("dev-login"), {
                method: "POST",
                credentials: "include"
            })

            if (!res.ok) {
                renderUnauthorized("Modo desarrollo no disponible")
                return false
            }

            const me2 = await fetch(getAuthUrl("me"), {
                credentials: "include"
            })

            if (!me2.ok) {
                renderUnauthorized("Error validando sesión")
                return false
            }

            const user = await me2.json()
            window.currentUser = user

            startSessionHeartbeat()
            startSessionTimeout()

            return true
        }

        // ❌ SI no hay token ni sesión → bloquear
        renderUnauthorized("Debes acceder desde SIGA")
        return false

    } catch (error) {
        console.error("Auth error:", error)
        renderNetworkError()
        return false
    }
}
// =========================
// ANIMACIONES
// =========================


function animateSidebarToNavbar() {
    const sidebar = document.getElementById("sidebar")

    if (!sidebar) return

    sidebar.classList.add("transition-all", "duration-300")

    if (window.innerWidth < 768) {
        sidebar.classList.add("opacity-0", "-translate-x-4")
    } else {
        sidebar.classList.remove("opacity-0", "-translate-x-4")
    }
}

window.addEventListener("resize", animateSidebarToNavbar)
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
function runInitialAnimations() {
    const header = document.getElementById("header")
    const content = document.getElementById("content")

    if (!header || !content) return

    header.classList.add("-translate-y-full", "opacity-0")
    content.classList.add("opacity-0", "translate-y-4")

    requestAnimationFrame(() => {
        header.classList.add("transition-all", "duration-500", "ease-out")
        content.classList.add("transition-all", "duration-500", "ease-out")

        header.classList.remove("-translate-y-full", "opacity-0")
        content.classList.remove("opacity-0", "translate-y-4")
    })
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
        if (page !== "conversations") {
            const last = localStorage.getItem("lastSession")

            if (last) {
                try {
                    setSelectedSession(JSON.parse(last))
                } catch {}
            }
        }
        isNavigating = true;

        const url = new URL(window.location);

        // SIEMPRE SET VIEW
        url.searchParams.set("view", page);

        // LIMPIAR PARAMS SOLO SI NO ES CHAT
        if (page !== "conversations") {
            url.searchParams.delete("session_id");
            url.searchParams.delete("phone");
        }

        if (push) {
            window.history.pushState({}, "", url);
        }

        await animateContentOut(content);

        setLayout(config.layout);
        renderHeader(config.layout, page);

        if (config.layout === "default") {
            renderSidebar();
            initSidebar(page);
        }

        await loadView(config.path);

        if (typeof config.init === "function") {
            await config.init();
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
            const sessionId = btn.dataset.sessionId
            const phone = btn.dataset.phone || null

            const url = new URL(window.location)
            url.searchParams.set("view", "conversations")

            if (sessionId) {
                url.searchParams.set("session_id", sessionId)
            }

            setSelectedSession({
                sessionId: Number(sessionId),
                phone
            })

            window.history.pushState({}, "", url)
            navigateTo("conversations", false)
            return
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

document.addEventListener("DOMContentLoaded", async () => {
    renderLoading();

    bindEvents();

    const ok = await initAuth(); // AUTH PRIMERO
    removeLoading();

    if (!ok) return
    

    initApp(); // SOLO SI AUTH OK
    await initWebSocket();
    
    if (!window.__appAnimated) {
        runInitialAnimations();
        window.__appAnimated = true
}
});

window.addEventListener("popstate", () => {
    const params = new URLSearchParams(window.location.search);
    const view = params.get("view") || "verifications";
    navigateTo(view, false);
});
window.logout = logout; // para poder llamar desde HTML
