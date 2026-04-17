import { navigateTo } from "./app.js"

const SIDEBAR_STORAGE_KEY = "panel.sidebar.collapsed"
const COLLAPSED_WIDTH_CLASS = "md:w-[72px]"
const EXPANDED_WIDTH_CLASS = "md:w-64"

function readCollapsedState() {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true"
}

function writeCollapsedState(value) {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(Boolean(value)))
}

function getSidebarRoot() {
    return document.getElementById("sidebar")
}

function setToggleIcon(button, collapsed) {
    if (!button) return

    button.innerHTML = collapsed
        ? `<i data-lucide="panel-left-open" class="h-5 w-5"></i>`
        : `<i data-lucide="panel-left-close" class="h-5 w-5"></i>`

    button.title = collapsed ? "Expandir menú" : "Contraer menú"
    button.setAttribute("aria-label", collapsed ? "Expandir menú" : "Contraer menú")

    if (window.lucide) {
        window.lucide.createIcons()
    }
}

function applySidebarState(sidebar, collapsed) {
    if (!sidebar) return

    sidebar.dataset.collapsed = collapsed ? "true" : "false"

    sidebar.classList.remove(COLLAPSED_WIDTH_CLASS, EXPANDED_WIDTH_CLASS)
    sidebar.classList.add(collapsed ? COLLAPSED_WIDTH_CLASS : EXPANDED_WIDTH_CLASS)

    const header = sidebar.querySelector("[data-sidebar-header]")
    const brand = sidebar.querySelector("[data-sidebar-brand]")
    const nav = sidebar.querySelector("[data-sidebar-nav]")
    const toggle = sidebar.querySelector("#toggleSidebar")

    if (header) {
        header.classList.toggle("justify-between", !collapsed)
        header.classList.toggle("justify-center", collapsed)
    }

    if (brand) {
        brand.classList.toggle("hidden", collapsed)
    }

    if (nav) {
        nav.classList.toggle("items-center", collapsed)
    }

    sidebar.querySelectorAll("[data-sidebar-label]").forEach((label) => {
        label.classList.toggle("hidden", collapsed)
    })

    sidebar.querySelectorAll(".nav-item").forEach((item) => {
        item.classList.remove(
            "justify-start",
            "justify-center",
            "px-3",
            "px-2",
            "gap-3",
            "gap-0"
        )

        if (collapsed) {
            item.classList.add("justify-center", "px-2", "gap-0")
        } else {
            item.classList.add("justify-start", "px-3", "gap-3")
        }
    })

    setToggleIcon(toggle, collapsed)
}

function setActiveNavItem(activePage = "") {
    document.querySelectorAll("#sidebar .nav-item").forEach((item) => {
        const page = item.dataset.page || ""
        const isActive = page === activePage

        item.classList.remove(
            "bg-blue-500",
            "text-white",
            "dark:bg-blue-600"
        )

        if (isActive) {
            item.classList.add(
                "bg-blue-500",
                "text-white",
                "dark:bg-blue-600"
            )
        }
    })
}

function bindSidebarNavigation() {
    document.querySelectorAll("#sidebar .nav-item").forEach((item) => {
        item.onclick = () => {
            const page = item.dataset.page
            if (!page) return
            navigateTo(page)
        }
    })
}

function bindToggle(sidebar) {
    const toggle = sidebar.querySelector("#toggleSidebar")
    if (!toggle) return

    toggle.onclick = () => {
        const collapsed = sidebar.dataset.collapsed === "true"
        const next = !collapsed

        writeCollapsedState(next)
        applySidebarState(sidebar, next)
    }
}

export function initSidebar(activePage = "") {
    const sidebar = getSidebarRoot()
    if (!sidebar) return

    applySidebarState(sidebar, readCollapsedState())
    setActiveNavItem(activePage)
    bindSidebarNavigation()
    bindToggle(sidebar)
}