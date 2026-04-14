import { fetchVerifications } from "./api.js";
import { navigateTo, setSelectedSession } from "./app.js"
import {loadChat} from "./chat.js"
import { dispatch, subscribeStore, getState } from "./store.js"

let currentVerificationStatus = ""
function getDrawerElements() {
    return {
        drawer: document.getElementById("drawer"),
        body: document.getElementById("drawerBody"),
        overlay: document.getElementById("drawerOverlay")
    };
}

function closeVerificationDrawer() {
    const { drawer, overlay } = getDrawerElements();
    if (!drawer || !overlay) return;

    drawer.classList.remove("translate-x-0");
    drawer.classList.add("translate-x-full");

    overlay.classList.remove("opacity-100");
    overlay.classList.add("opacity-0", "pointer-events-none");
}

window.closeVerificationDrawer = closeVerificationDrawer;

function setVerificationState(state) {
    const loadingEl = document.getElementById("verificationLoading");
    const errorEl = document.getElementById("verificationError");
    const emptyEl = document.getElementById("verificationEmpty");
    const tableWrapper = document.getElementById("verificationTableWrapper");

    if (!loadingEl || !errorEl || !emptyEl || !tableWrapper) return;

    loadingEl.classList.add("hidden");
    errorEl.classList.add("hidden");
    emptyEl.classList.add("hidden");
    tableWrapper.classList.add("hidden");

    switch (state.type) {
        case "loading":
            loadingEl.classList.remove("hidden");
            break;
        case "error":
            errorEl.textContent = state.message || "Error";
            errorEl.classList.remove("hidden");
            break;
        case "empty":
            emptyEl.classList.remove("hidden");
            break;
        case "success":
            tableWrapper.classList.remove("hidden");
            break;
    }
}

function updateVerificationKpis(items) {
    const total = document.getElementById("kpiTotal")
    if (!total) return

    document.getElementById("kpiTotal").textContent = items.length
    document.getElementById("kpiInProgress").textContent =
        items.filter(i => i.status === "in_progress").length
    document.getElementById("kpiInconsistent").textContent =
        items.filter(i => i.status === "inconsistent").length
    document.getElementById("kpiCompleted").textContent =
        items.filter(i => i.status === "completed").length
}

function renderInconsistencias(item) {
    const inconsistencias = item.inconsistencias || [];

    if (!inconsistencias.length) {
        return `<p class="text-green-500 dark:text-green-400">Sin inconsistencias</p>`;
    }
    
    return `
        <ul class="flex flex-col gap-2">
            ${inconsistencias.map(i => `
                <li class="flex items-start gap-2 text-sm text-gray-700 dark:text-slate-200">
                    <span class="mt-1 w-2 h-2 rounded-full ${i.estado === "ABIERTA" ? "bg-red-500" : "bg-green-500"}"></span>
                    <div>
                        <strong>${ui.escapeHtml(i.campo)}:</strong>
                        <span>${ui.escapeHtml(i.mensaje)}</span>
                    </div>
                </li>
            `).join("")}
        </ul>
    `;
}
function renderDrawerBase(item) {
    const { body } = getDrawerElements()
    if (!body) return

    body.innerHTML = `
    <div class="flex flex-col h-full text-gray-900 dark:text-white">

        <div id="drawerHeader"></div>

        <div class="mt-4 bg-white dark:bg-slate-800 p-4 rounded-xl border dark:border-slate-700">
            <h4 class="text-xs text-gray-500 mb-2">CLIENTE</h4>
            <div id="drawerCliente" class="grid grid-cols-3 gap-3 text-sm"></div>
        </div>

        <div class="mt-4 bg-white dark:bg-slate-800 p-4 rounded-xl border dark:border-slate-700">
            <h4 class="text-xs text-gray-500 mb-2">PROGRESO</h4>
            <div id="drawerProgressBar"></div>
            <div id="drawerProgressMeta" class="mt-3 flex justify-between text-xs text-gray-500"></div>
        </div>

        <div class="mt-4 bg-white dark:bg-slate-800 p-4 rounded-xl border dark:border-slate-700 flex-1 overflow-y-auto">
            <h4 class="text-xs text-gray-500 mb-2">INCONSISTENCIAS</h4>
            <div id="drawerInconsistencias"></div>
        </div>

        <div id="drawerFooter" class="mt-4"></div>
    </div>
    `

    updateDrawer(item)
}
function updateDrawer(item) {
    // HEADER
    const header = document.getElementById("drawerHeader")
    if (header) {
        header.innerHTML = `
            <div class="flex justify-between items-start border-b border-gray-200 dark:border-slate-700 pb-4">
                <div>
                    <h2 class="text-2xl font-semibold">
                        Folio ${ui.escapeHtml(item.folio || "-")}
                    </h2>
                    <span class="${ui.statusClass(item.status)} mt-2 inline-block">
                        ${ui.statusLabel(item.status)}
                    </span>
                    <span class="text-xs text-gray-500">
                        Última actividad: ${ui.formatDateTime(item.last_activity)}
                    </span>
                </div>
                <button onclick="closeVerificationDrawer()"
                    class="h-10 w-10 rounded-lg bg-gray-100 dark:bg-slate-700">
                    ✕
                </button>
            </div>
        `
    }

    // CLIENTE
    const cliente = document.getElementById("drawerCliente")
    if (cliente) {
        cliente.innerHTML = `
            <div>
                <p class="text-gray-500">Nombre</p>
                <p>${ui.escapeHtml(item.name || "-")}</p>
            </div>
            <div>
                <p class="text-gray-500">Teléfono</p>
                <p>${ui.escapeHtml(item.phone || "-")}</p>
            </div>
            <div>
                <p class="text-gray-500">Cuenta</p>
                <p>${ui.escapeHtml(item.no_cuenta || "-")}</p>
            </div>
        `
    }

    // PROGRESO
    const progressBar = document.getElementById("drawerProgressBar")
    if (progressBar) {
        progressBar.innerHTML = ui.renderProgressBar(item.progress_pct)
    }

    const progressMeta = document.getElementById("drawerProgressMeta")
    if (progressMeta) {
        progressMeta.innerHTML = `
            <span>${item.progress_pct}%</span>
            <span>${ui.escapeHtml(item.current_step || "-")}</span>
        `
    }

    // INCONSISTENCIAS
    const inconsistenciasEl = document.getElementById("drawerInconsistencias")
    if (inconsistenciasEl) {
        inconsistenciasEl.innerHTML = item.inconsistencias?.length
            ? item.inconsistencias.map(i => `
                <div class="mb-3 p-3 rounded-lg border 
                    ${i.estado === "ABIERTA"
                        ? "border-red-300 bg-red-50 dark:bg-red-900/20"
                        : "border-green-300 bg-green-50 dark:bg-green-900/20"}">
                    <div class="flex justify-between">
                        <div>
                            <div class="text-sm font-semibold">
                                ${ui.escapeHtml(i.campo)}
                            </div>
                            <div class="text-xs text-gray-600">
                                ${ui.escapeHtml(i.mensaje)}
                            </div>
                        </div>
                        ${
                            i.estado === "ABIERTA"
                            ? `<a 
                                href="#"
                                onclick="goToSiga('${item.no_cuenta}')"
                                class="text-xs bg-blue-500 text-white px-2 py-1 rounded"
                                >
                                Resolver
                                </a>`
                            : `<span class="text-green-500 text-xs">✔</span>`
                        }
                    </div>
                </div>
            `).join("")
            : `<p class="text-green-500 text-sm">Sin inconsistencias</p>`
    }
        const footer = document.getElementById("drawerFooter")
    if (footer) {
        footer.innerHTML = `
            <button
                id="goToChat"
                type="button"
                class="w-full bg-blue-500 hover:bg-blue-600 text-white py-3 rounded-lg transition"
            >
                💬 Abrir conversación
            </button>
        `

        const goToChatBtn = document.getElementById("goToChat")
        if (goToChatBtn) {
            goToChatBtn.onclick = async () => {
                if (window.closeVerificationDrawer) {
                    window.closeVerificationDrawer()
                }

                setSelectedSession(item.session_id)

                await navigateTo("conversations")
                await loadChat(item.session_id, item.phone)
            }
        }
    }
}

function openVerificationDetail(item) {
    const { drawer, overlay } = getDrawerElements()
    if (!drawer || !overlay) return

    dispatch({
        type: "verifications/select",
        payload: item.session_id
    })

    renderDrawerBase(item)

    drawer.classList.remove("translate-x-full")
    drawer.classList.add("translate-x-0")

    overlay.classList.remove("opacity-0", "pointer-events-none")
    overlay.classList.add("opacity-100")
}

function renderVerificationRows(items) {
    const tbody = document.getElementById("verificationTableBody");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!items.length) return;

    items.forEach(item => {
        const tr = document.createElement("tr");
        tr.className = "cursor-pointer border-b border-gray-100 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-700/40 transition";

        tr.innerHTML = `
            <td class="px-4 py-4">${ui.escapeHtml(item.no_cuenta || "-")}</td>
            <td class="px-4 py-4">${ui.escapeHtml(item.folio || "-")}</td>
            <td class="px-4 py-4">${ui.escapeHtml(item.phone || "-")}</td>
            <td class="px-4 py-4"><span class="${ui.statusClass(item.status)}">${ui.statusLabel(item.status)}</span></td>
            <td class="px-4 py-4">${ui.renderProgressBar(item.progress_pct)}</td>
            <td class="px-4 py-4">${ui.escapeHtml(item.current_step || "-")}</td>
            <td class="px-4 py-4">${item.inconsistencias_count ?? 0}</td>
            <td class="px-4 py-4 whitespace-nowrap">${ui.formatDateTime(item.last_activity)}</td>
        `;

        tr.onclick = () => openVerificationDetail(item);
        tbody.appendChild(tr);
        
    });
}

function renderVerificationsFromState(state) {
    const items = state.verifications.order
        .map(id => state.verifications.bySessionId[id])
        .filter(Boolean)

    
    

    if (!items.length) {
        setVerificationState({ type: "empty" })
    }
    else {
        updateVerificationKpis(items)
        renderVerificationRows(items)

        
        setVerificationState({ type: "success" })
    } 
}
async function loadVerifications(status = "") {
    currentVerificationStatus = status;
    setVerificationState({ type: "loading" });

    try {
        const response = await fetchVerifications(status);
        const items = response?.data ?? [];


        dispatch({
            type: "verifications/loaded",
            payload: items
        })
    } catch (error) {
        setVerificationState({
            type: "error",
            message: error?.message || "Error cargando verificaciones"
        });
    }
}

function bindVerificationFilters() {
    document.querySelectorAll(".filter-btn").forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll(".filter-btn").forEach(b => {
                b.classList.remove("bg-blue-500", "text-white");
                b.classList.add(
                    "bg-gray-100",
                    "text-gray-700",
                    "dark:bg-slate-700",
                    "dark:text-slate-200"
                );
            });

            btn.classList.remove(
                "bg-gray-100",
                "text-gray-700",
                "dark:bg-slate-700",
                "dark:text-slate-200"
            );
            btn.classList.add("bg-blue-500", "text-white");

            loadVerifications(btn.dataset.status || "");
        };
    });
}

function bindDrawerCloseEvents() {
    const overlay = document.getElementById("drawerOverlay");
    if (overlay) {
        overlay.onclick = closeVerificationDrawer;
    }

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeVerificationDrawer();
        }
    });
}

let unsubscribeVerificationStore = null

export function initVerificationsPage() {
    bindVerificationFilters()
    bindDrawerCloseEvents()

    loadVerifications()

    if (unsubscribeVerificationStore) {
        unsubscribeVerificationStore()
    }

    unsubscribeVerificationStore = subscribeStore((state) => {

        
        renderVerificationsFromState(state)

        const selected = state.verifications.selected
        console.log("SELECTED:", state.verifications.selected)
        if (!selected) return
        const updated = state.verifications.bySessionId[String(selected)]
        console.log("UPDATED:", updated)
        if (!updated) return
        

        updateDrawer(updated)

    })

}

document.addEventListener("click", (e) => {

    const btn = e.target.closest("[data-session-id]")
    if (!btn) return

    const sessionId = Number(btn.dataset.sessionId)
    if (!sessionId) return
    
    // IMPORTANTE: cerrar drawer antes de navegar
    if (window.closeVerificationDrawer) {
        window.closeVerificationDrawer()
    }

    setSelectedSession(sessionId)
    
    // IMPORTANTE: delay mínimo para evitar conflicto DOM
    requestAnimationFrame(() => {
        navigateTo("conversations")
    })
})




window.goToSiga = function(noCuenta) {
    const form = document.createElement("form")
    form.method = "POST"
    form.action = "http://localhost/siga/app/cuentas/datos_cuenta.php"
    form.target = "_blank" // opcional

    const input = document.createElement("input")
    input.type = "hidden"
    input.name = "no_cuenta"
    input.value = noCuenta

    form.appendChild(input)
    document.body.appendChild(form)
    form.submit()
}