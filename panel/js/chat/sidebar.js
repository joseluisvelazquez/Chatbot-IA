import { shouldShowActionBadge, statusMeta } from "./permissions.js"
import { escapeHtml, formatTime } from "./utils.js"

export function createSidebarController({
    getState,
    loadChat,
    getCurrentSessionId,
    getLastLoadedSessionId,
    isLoadingChat,
    showMobileChat,
    isAdmin,
}) {
    const sidebarNodes = new Map()
    let searchTerm = ""
    let filterMode = "all"
    let searchDebounceTimer = null

    function createSidebarNode(session) {
        const element = document.createElement("div")
        element.className = `
            px-4 py-3 cursor-pointer border-b flex justify-between items-center
            border-gray-200 dark:border-slate-700
            hover:bg-gray-100 dark:hover:bg-slate-700
            transition
        `
        element.dataset.id = session.id
        element.onclick = async () => {
            if (
                getCurrentSessionId() === session.id &&
                getLastLoadedSessionId() === session.id &&
                !isLoadingChat()
            ) {
                showMobileChat()
                return
            }

            await loadChat(session.id, session.phone, session.name)
        }

        return element
    }

    function updateSidebarNode(node, session) {
        const isActive = session.id === getCurrentSessionId()
        const displayName = session.display_name || session.name || session.phone || "Cliente sin nombre"
        const meta = statusMeta(session.status_operativo)
        const showTest = Boolean(session.test_mode && isAdmin())
        const priorityClass = session.priority === "high"
            ? "text-red-500"
            : session.priority === "low"
                ? "text-gray-400"
                : "text-gray-500"

        node.className = `
            px-4 py-3 cursor-pointer border-b flex justify-between items-center
            border-gray-200 dark:border-slate-700
            hover:bg-gray-100 dark:hover:bg-slate-700
            transition
            ${isActive ? "bg-blue-100 dark:bg-slate-700" : ""}
        `

        node.innerHTML = `
            <div class="min-w-0">
                <div class="font-semibold truncate">
                    ${escapeHtml(displayName)}
                </div>

                <div class="mt-1 flex flex-wrap items-center gap-1">
                    <span class="text-[11px] px-2 py-0.5 rounded ${meta.className}">
                        ${escapeHtml(meta.label)}
                    </span>
                    ${
                        shouldShowActionBadge(session)
                            ? `<span class="text-[11px] px-2 py-0.5 rounded bg-red-500 text-white">Accion</span>`
                            : ""
                    }
                    ${
                        showTest
                            ? `<span class="text-[11px] px-2 py-0.5 rounded bg-black text-white">TEST</span>`
                            : ""
                    }
                </div>

                ${
                    session.no_cuenta
                        ? `<div class="text-xs text-gray-400">Cuenta: ${escapeHtml(session.no_cuenta)}</div>`
                        : ""
                }

                <div class="text-xs ${priorityClass}">
                    ${session.last_message_at ? formatTime(session.last_message_at) : ""}
                </div>
            </div>

            ${session.unread_count > 0
                ? `<span class="bg-green-500 text-white text-xs px-2 py-1 rounded-full shrink-0">${session.unread_count}</span>`
                : ""
            }
        `
    }

    function render(state) {
        const list = document.getElementById("conversationList")
        if (!list) return

        let sessions = state.conversations.order
            .map(id => state.conversations.byId[id])
            .filter(Boolean)
            .sort((a, b) => {
                const dateA = new Date(a.last_message_at || 0).getTime()
                const dateB = new Date(b.last_message_at || 0).getTime()
                return dateB - dateA
            })

        if (searchTerm) {
            sessions = sessions.filter(session => {
                const phone = session.phone?.toLowerCase() || ""
                const name = session.name?.toLowerCase() || ""
                const cuenta = String(session.no_cuenta || "").toLowerCase()
                const folio = String(session.folio || "").toLowerCase()

                return (
                    phone.includes(searchTerm) ||
                    name.includes(searchTerm) ||
                    cuenta.includes(searchTerm) ||
                    folio.includes(searchTerm)
                )
            })
        }

        if (filterMode === "unread") {
            sessions = sessions.filter(session => (session.unread_count || 0) > 0)
        }

        const fragment = document.createDocumentFragment()
        const seen = new Set()

        sessions.forEach((session) => {
            seen.add(session.id)

            let node = sidebarNodes.get(session.id)
            if (!node) {
                node = createSidebarNode(session)
                sidebarNodes.set(session.id, node)
            }

            updateSidebarNode(node, session)
            fragment.appendChild(node)
        })

        sidebarNodes.forEach((_, id) => {
            if (!seen.has(id)) {
                sidebarNodes.delete(id)
            }
        })

        list.replaceChildren(fragment)
    }

    function setActiveFilter(activeButton, inactiveButton) {
        activeButton.classList.remove(
            "bg-gray-200", "text-gray-700",
            "dark:bg-slate-700", "dark:text-gray-300"
        )
        activeButton.classList.add(
            "bg-green-600", "text-white",
            "dark:bg-green-500"
        )

        inactiveButton.classList.remove(
            "bg-green-600", "text-white",
            "dark:bg-green-500"
        )
        inactiveButton.classList.add(
            "bg-gray-200", "text-gray-700",
            "dark:bg-slate-700", "dark:text-gray-300"
        )
    }

    function setupFilters() {
        const input = document.getElementById("searchInput")
        const allButton = document.getElementById("filterAll")
        const unreadButton = document.getElementById("filterUnread")

        if (input) {
            input.addEventListener("input", (event) => {
                const value = event.target.value
                window.clearTimeout(searchDebounceTimer)
                searchDebounceTimer = window.setTimeout(() => {
                    searchTerm = value.toLowerCase().trim()
                    localStorage.setItem("chatSearch", searchTerm)
                    render(getState())
                }, 180)
            })
        }

        if (allButton) {
            allButton.onclick = () => {
                filterMode = "all"
                setActiveFilter(allButton, unreadButton)
                render(getState())
            }
        }

        if (unreadButton) {
            unreadButton.onclick = () => {
                filterMode = "unread"
                setActiveFilter(unreadButton, allButton)
                render(getState())
            }
        }
    }

    function hydrateSearch(value) {
        searchTerm = String(value || "").toLowerCase().trim()
        const input = document.getElementById("searchInput")
        if (input) input.value = value || ""
    }

    return {
        render,
        setupFilters,
        hydrateSearch,
    }
}
