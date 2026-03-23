import { renderHeader, renderSidebar } from "./ui.js";
import { initVerificationsPage } from "./verifications.js";
import { initSidebar } from "./sidebar.js";

export async function loadView(path) {
    const content = document.getElementById("content");

    const res = await fetch(path);
    const html = await res.text();

    content.innerHTML = html;
}

async function loadPage(pageName) {
    const response = await fetch(`/pages/${pageName}.html`);

    if (!response.ok) {
        throw new Error(`No se pudo cargar la página ${pageName}`);
    }

    document.getElementById("content").innerHTML = await response.text();

    bindSidebar(pageName);

    if (pageName === "verificaciones") {
        initVerificationsPage();
    }
}

function bindSidebar(activePage) {
    const navLinks = document.querySelectorAll(".nav-link");

    navLinks.forEach(btn => {
        const page = btn.dataset.page;

        btn.classList.toggle("active", page === activePage);

        btn.onclick = () => loadPage(page);
    });
}



async function initApp() {
    try {

        await loadPage("verificaciones");

    } catch (error) {
        document.getElementById("content").innerHTML = `
            <div class="table-state error">
                Error cargando el panel: ${error.message}
            </div>
        `;
    }
}

export async function navigateTo(page) {

    const content = document.getElementById("content");

    if (page === "verifications") {
        await loadView("/pages/verificaciones.html");
        initVerificationsPage(); // 🔥 ahora sí
    }

    if (page === "dashboard") {
        await loadView("/pages/dashboard.html");
        
    }

    if (page === "conversations") {
        await loadView("/pages/conversaciones.html");
    }

    if (page === "cobranza") {
        await loadView("/pages/cobranza.html");
    }
}
function closeDrawer() {
    const drawer = document.getElementById("drawer");
    const overlay = document.getElementById("drawerOverlay");

    drawer.classList.remove("open");
    overlay.classList.remove("active");
}
document.addEventListener("DOMContentLoaded", initApp);

document.addEventListener("DOMContentLoaded", () => {

    renderHeader();

    renderSidebar();

    initSidebar();
    

    if (window.lucide) {
        lucide.createIcons();
    }

});
// 🔥 COLAPSAR SIDEBAR GLOBAL
window.toggleSidebar = function () {
    document.body.classList.toggle("sidebar-collapsed");
};
document.addEventListener("click", (e) => {
    if (e.target.closest(".btn-primary")) {
        const phone = e.target.closest(".btn-primary").dataset.phone;

        window.selectedPhone = phone;
        navigateTo("conversations");
    }
    // cerrar drawer
    if (e.target.closest("#closeDrawer")) {
        closeDrawer();
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