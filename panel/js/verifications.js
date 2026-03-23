import { fetchVerifications } from "./api.js";

let currentVerificationStatus = "";

// -------------------------------------
// STATE (único, sin flags sueltos)
// -------------------------------------
function setVerificationState(state) {
    const loadingEl = document.getElementById("verificationLoading");
    const errorEl = document.getElementById("verificationError");
    const emptyEl = document.getElementById("verificationEmpty");
    const tableWrapper = document.querySelector(".table-wrapper");

    if (!loadingEl || !errorEl || !emptyEl || !tableWrapper) return;

    // 🔥 RESET TOTAL (FORZADO)
    loadingEl.style.display = "none";
    errorEl.style.display = "none";
    emptyEl.style.display = "none";
    tableWrapper.style.display = "none";

    switch (state.type) {
        case "loading":
            loadingEl.style.display = "block";
            break;

        case "error":
            errorEl.textContent = state.message || "Error";
            errorEl.style.display = "block";
            break;

        case "empty":
            emptyEl.style.display = "block";
            break;

        case "success":
            tableWrapper.style.display = "block";
            break;
    }
}

// -------------------------------------
// KPIs
// -------------------------------------
function updateVerificationKpis(items) {
    document.getElementById("kpiTotal").textContent = items.length;
    document.getElementById("kpiInProgress").textContent =
        items.filter(i => i.status === "in_progress").length;
    document.getElementById("kpiInconsistent").textContent =
        items.filter(i => i.status === "inconsistent").length;
    document.getElementById("kpiCompleted").textContent =
        items.filter(i => i.status === "completed").length;
}

// -------------------------------------
// Inconsistencias badge
// -------------------------------------
function renderInconsistenciasBadge(inconsistencias = []) {
    if (!inconsistencias.length) {
        return `<span class="ok">0</span>`;
    }

    const abiertas = inconsistencias.filter(i => i.estado === "open").length;

    return `
        <span class="badge inconsistent">
            ${abiertas} ⚠️
        </span>
    `;
}

// -------------------------------------
// Inconsistencias detalle
// -------------------------------------
function renderInconsistencias(item) {
    const inconsistencias = item.inconsistencias || [];

    if (!inconsistencias.length) {
        return `<p class="ok">Sin inconsistencias</p>`;
    }

    return `
        <ul class="inconsistencias-list">
            ${inconsistencias.map(i => `
                <li>
                    <span class="error-dot ${String(i.estado || "").toLowerCase()}"></span>
                    <strong>${i.campo}:</strong> ${i.mensaje}
                </li>
            `).join("")}
        </ul>
    `;
}

// -------------------------------------
// Drawer detalle
// -------------------------------------
function openVerificationDetail(item) {
    const drawer = document.getElementById("drawer");
    const body = document.getElementById("drawerBody");

    body.innerHTML = `
        <div class="detail">

            <div class="drawer-header">
                <div class="drawer-title">
                    <h2>Folio ${item.folio}</h2>
                    <span class="badge ${item.status}">
                        ${ui.statusLabel(item.status)}
                    </span>
                </div>

                <button class="drawer-close" id="closeDrawer">✕</button>
            </div>

            <div class="detail-section">
                <h4>Cliente</h4>
                <p><strong>Teléfono:</strong> ${item.phone}</p>
                <p><strong>No. cuenta:</strong> ${item.no_cuenta || "Sin cuenta"}</p>
            </div>

            <div class="detail-section">
                <h4>Progreso</h4>
                ${ui.renderProgressBar(item.progress_pct)}
                <p><strong>Paso actual:</strong> ${item.current_step}</p>
            </div>

            <div class="detail-section">
                <h4>⚠️ Inconsistencias</h4>
                ${renderInconsistencias(item)}
            </div>

            <div class="detail-actions">
                <button class="btn-primary" data-phone="${item.phone}">
                    💬 Ver conversación
                </button>
            </div>

        </div>
    `;

    drawer.classList.add("open");
    document.getElementById("drawerOverlay").classList.add("active");
}

// -------------------------------------
// Render tabla
// -------------------------------------
function renderVerificationRows(items) {
    const tbody = document.getElementById("verificationTableBody");
    tbody.innerHTML = "";

    if (!items.length) return;

    items.forEach(item => {
        const tr = document.createElement("tr");

        tr.innerHTML = `
            <td>${ui.escapeHtml(item.no_cuenta || "-")}</td>
            <td>${ui.escapeHtml(item.folio || "-")}</td>
            <td>${ui.escapeHtml(item.phone || "-")}</td>
            <td><span class="${ui.statusClass(item.status)}">${ui.statusLabel(item.status)}</span></td>
            <td>${ui.renderProgressBar(item.progress_pct)}</td>
            <td>${ui.escapeHtml(item.current_step)}</td>
            <td>${item.inconsistencias_count}</td>
            <td>${ui.formatDateTime(item.last_activity)}</td>
        `;

        tr.onclick = () => openVerificationDetail(item);
        tr.classList.add("clickable");

        tbody.appendChild(tr);
    });
}

// -------------------------------------
// LOAD (controlado)
// -------------------------------------
async function loadVerifications(status = "") {
    console.log("LOAD VERIFICATIONS:", status);

    currentVerificationStatus = status;

    setVerificationState({ type: "loading" });

    try {
        const response = await fetchVerifications(status);
        const items = response?.data ?? [];

        console.log("DATA:", items);

        updateVerificationKpis(items);

        if (!items.length) {
            renderVerificationRows([]);
            setVerificationState({ type: "empty" });
            return;
        }

        renderVerificationRows(items);
        setVerificationState({ type: "success" });

    } catch (error) {
        console.error("ERROR:", error);

        setVerificationState({
            type: "error",
            message: error?.message
        });
    }
}

// -------------------------------------
// Filtros
// -------------------------------------
function bindVerificationFilters() {
    document.querySelectorAll(".filter-btn").forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll(".filter-btn")
                .forEach(b => b.classList.remove("active"));

            btn.classList.add("active");

            loadVerifications(btn.dataset.status || "");
        };
    });
}

// -------------------------------------
// INIT
// -------------------------------------
export function initVerificationsPage() {
    console.log("INIT VERIFICATIONS PAGE");

    bindVerificationFilters();
    loadVerifications();
}