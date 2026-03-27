import { fetchVerifications } from "./api.js";
import { navigateTo, setSelectedSession } from "./app.js"
import {loadChat} from "./chat.js"

let currentVerificationStatus = "";

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
    document.getElementById("kpiTotal").textContent = items.length;
    document.getElementById("kpiInProgress").textContent =
        items.filter(i => i.status === "in_progress").length;
    document.getElementById("kpiInconsistent").textContent =
        items.filter(i => i.status === "inconsistent").length;
    document.getElementById("kpiCompleted").textContent =
        items.filter(i => i.status === "completed").length;
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
                    <span class="mt-1 w-2 h-2 rounded-full ${i.estado === "open" ? "bg-red-500" : "bg-green-500"}"></span>
                    <div>
                        <strong>${ui.escapeHtml(i.campo)}:</strong>
                        <span>${ui.escapeHtml(i.mensaje)}</span>
                    </div>
                </li>
            `).join("")}
        </ul>
    `;
}

function openVerificationDetail(item) {
    const { drawer, body, overlay } = getDrawerElements();
    if (!drawer || !body || !overlay) return;

    body.innerHTML = `
        <div class="flex flex-col gap-5 h-full text-gray-900 dark:text-white">
            <div class="flex justify-between items-start gap-4 border-b border-gray-200 dark:border-slate-700 pb-4">
                <div class="flex flex-col gap-2">
                    <h2 class="text-2xl font-semibold">Folio ${ui.escapeHtml(item.folio || "-")}</h2>
                    <span class="${ui.statusClass(item.status)} w-fit">
                        ${ui.statusLabel(item.status)}
                    </span>
                </div>

                <button
                    type="button"
                    onclick="closeVerificationDrawer()"
                    class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-slate-700 dark:text-white dark:hover:bg-slate-600 transition"
                    aria-label="Cerrar"
                >
                    ✕
                </button>
            </div>

            <div class="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-xl p-4">
                <h4 class="text-sm text-gray-500 dark:text-slate-400 mb-3">Cliente</h4>
                <div class="space-y-2 text-sm md:text-base">
                    <p><strong>Teléfono:</strong> ${ui.escapeHtml(item.phone || "-")}</p>
                    <p><strong>No. cuenta:</strong> ${ui.escapeHtml(item.no_cuenta || "Sin cuenta")}</p>
                </div>
            </div>

            <div class="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-xl p-4">
                <h4 class="text-sm text-gray-500 dark:text-slate-400 mb-3">Progreso</h4>
                ${ui.renderProgressBar(item.progress_pct)}
                <p class="mt-3 text-sm text-gray-700 dark:text-slate-200">
                    <strong>Paso actual:</strong> ${ui.escapeHtml(item.current_step || "-")}
                </p>
            </div>

            <div class="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-xl p-4">
                <h4 class="text-sm text-gray-500 dark:text-slate-400 mb-3">⚠️ Inconsistencias</h4>
                ${renderInconsistencias(item)}
            </div>

            <div class="mt-auto pt-2">
                <button id="goToChat"
                    class="btn-primary w-full bg-blue-500 hover:bg-blue-600 text-white py-3 rounded-lg transition"
                    data-session-id="${item.session_id}"
                >
                    💬 Ver conversación
                </button>
            </div>
        </div>
    `;
    const btn = document.getElementById("goToChat");

    if (btn) {
        btn.onclick = async () => {
            await navigateTo("conversations");

            loadChat(item.session_id, item.phone); // 🔥 FIX
        };
    }

    drawer.classList.remove("translate-x-full");
    drawer.classList.add("translate-x-0");

    overlay.classList.remove("opacity-0", "pointer-events-none");
    overlay.classList.add("opacity-100");
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

async function loadVerifications(status = "") {
    currentVerificationStatus = status;
    setVerificationState({ type: "loading" });

    try {
        const response = await fetchVerifications(status);
        const items = response?.data ?? [];

        updateVerificationKpis(items);

        if (!items.length) {
            renderVerificationRows([]);
            setVerificationState({ type: "empty" });
            return;
        }

        renderVerificationRows(items);
        setVerificationState({ type: "success" });
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

export function initVerificationsPage() {
    bindVerificationFilters();
    bindDrawerCloseEvents();
    loadVerifications();
}

document.addEventListener("click", (e) => {

    const btn = e.target.closest("[data-session-id]")
    if (!btn) return

    const sessionId = Number(btn.dataset.sessionId)
    if (!sessionId) return
    
    // 🔥 IMPORTANTE: cerrar drawer antes de navegar
    if (window.closeVerificationDrawer) {
        window.closeVerificationDrawer()
    }

    setSelectedSession(sessionId)
    
    // 🔥 IMPORTANTE: delay mínimo para evitar conflicto DOM
    requestAnimationFrame(() => {
        navigateTo("conversations")
    })
})


