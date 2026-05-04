import { escapeHtml } from "./utils.js"

export function createAssignManagerModal({
    getAvailableManagers,
    assignConversationManager,
    canAssignManager,
    getSelectedConversation,
    getCurrentSessionId,
    getState,
    onAssignOptimistic,
    onAssignRollback,
    onAssigned,
    showToast,
}) {
    let managersCache = []
    let isManagersLoading = false
    let isAssignManagerSubmitting = false
    let managersController = null
    let searchDebounceTimer = null

    function getNodes() {
        return {
            modal: document.getElementById("assignManagerModal"),
            search: document.getElementById("assignManagerSearch"),
            list: document.getElementById("assignManagerList"),
            title: document.getElementById("assignManagerTitle"),
            loading: document.getElementById("assignManagerLoading"),
            empty: document.getElementById("assignManagerEmpty"),
            close: document.getElementById("assignManagerClose"),
        }
    }

    function setLoadingState(loading) {
        const { loading: loadingNode, list, empty } = getNodes()
        if (loadingNode) loadingNode.classList.toggle("hidden", !loading)
        if (list) list.classList.toggle("hidden", loading)
        if (loading && empty) empty.classList.add("hidden")
    }

    function setButtonsDisabled(disabled) {
        const { list, close, search } = getNodes()
        list?.querySelectorAll("[data-manager-username]").forEach((button) => {
            button.disabled = disabled
            button.classList.toggle("opacity-60", disabled)
            button.classList.toggle("pointer-events-none", disabled)
        })

        if (close) close.disabled = disabled
        if (search) search.disabled = disabled
    }

    function getLiveLoad(username, fallback = 0) {
        if (typeof getState !== "function" || !username) return Number(fallback || 0)

        const state = getState()
        const sessions = state.conversations?.order
            ?.map((id) => state.conversations.byId[id])
            ?.filter(Boolean) || []

        return sessions.filter((session) => (
            String(session.assigned_user_id || "").toLowerCase() === String(username).toLowerCase()
            && !["closed", "completed"].includes(String(session.status_operativo || "").toLowerCase())
        )).length
    }

    function renderList(filterText = "") {
        const { list, empty } = getNodes()
        if (!list || !empty) return

        const needle = String(filterText || "").trim().toLowerCase()
        const items = managersCache.filter((item) => {
            if (!needle) return true

            return [
                item.nombre,
                item.username,
                item.jefe_directo,
                item.puesto,
            ].some((value) => String(value || "").toLowerCase().includes(needle))
        })

        list.innerHTML = items.map((item) => `
            <button
                type="button"
                data-manager-username="${escapeHtml(item.username)}"
                class="w-full rounded-lg border border-gray-200 px-3 py-3 text-left transition hover:border-green-500 hover:bg-green-50 dark:border-slate-700 dark:hover:border-green-500 dark:hover:bg-slate-800"
            >
                <div class="flex items-center justify-between gap-3">
                    <div class="min-w-0">
                        <div class="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                            ${escapeHtml(item.nombre || item.username)}
                        </div>
                        <div class="truncate text-xs text-slate-500 dark:text-slate-400">
                            ${escapeHtml(item.username)}
                        </div>
                    </div>
                    <div class="shrink-0 text-right text-xs text-slate-500 dark:text-slate-400">
                        <div>${getLiveLoad(item.username, item.current_load)} chats</div>
                        <div class="${item.is_online ? "text-emerald-600 dark:text-emerald-400" : ""}">
                            ${item.is_online ? "En linea" : "Sin sesion"}
                        </div>
                    </div>
                </div>
                <div class="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                    ${item.jefe_directo ? `<span>Jefe: ${escapeHtml(item.jefe_directo)}</span>` : ""}
                    ${item.puesto ? `<span>${escapeHtml(item.puesto)}</span>` : ""}
                </div>
            </button>
        `).join("")

        empty.textContent = managersCache.length > 0
            ? "No hay gestores que coincidan con la busqueda."
            : "No hay gestores activos disponibles."
        empty.classList.toggle("hidden", isManagersLoading || items.length > 0)

        list.querySelectorAll("[data-manager-username]").forEach((button) => {
            button.addEventListener("click", () => submit(button.dataset.managerUsername || ""))
        })
    }

    async function loadAvailable(forceRefresh = false) {
        const { list, empty, search } = getNodes()

        if (isManagersLoading) return

        if (!forceRefresh && managersCache.length > 0) {
            renderList(search?.value || "")
            return
        }

        isManagersLoading = true
        if (managersController) managersController.abort()
        managersController = new AbortController()
        setLoadingState(true)

        try {
            const response = await getAvailableManagers({ signal: managersController.signal })
            managersCache = Array.isArray(response) ? response : []
            renderList(search?.value || "")
        } catch (error) {
            if (managersController?.signal?.aborted) return
            managersCache = []

            if (list) {
                list.innerHTML = ""
            }

            if (empty) {
                empty.textContent = error.message || "No se pudo cargar la lista de gestores activos."
                empty.classList.remove("hidden")
            }
        } finally {
            isManagersLoading = false
            managersController = null
            setLoadingState(false)
        }
    }

    function close() {
        const { modal, search } = getNodes()
        if (!modal) return
        modal.classList.add("hidden")
        modal.setAttribute("aria-hidden", "true")
        if (search) search.value = ""
    }

    async function open() {
        const session = getSelectedConversation()
        if (!canAssignManager(session)) return

        const { modal, search, title } = getNodes()
        if (!modal) return

        if (title) {
            title.textContent = session?.display_name || session?.name || session?.phone || "Asignar gestor"
        }

        modal.classList.remove("hidden")
        modal.setAttribute("aria-hidden", "false")

        if (window.lucide) {
            window.lucide.createIcons()
        }

        await loadAvailable()

        if (search) {
            search.value = ""
            search.focus()
        }
    }

    async function submit(username) {
        const sessionId = Number(getCurrentSessionId())
        if (!sessionId || !username || isAssignManagerSubmitting) return

        isAssignManagerSubmitting = true
        setButtonsDisabled(true)
        const rollbackState = typeof onAssignOptimistic === "function"
            ? onAssignOptimistic(username)
            : null

        try {
            const updated = await assignConversationManager(sessionId, username)
            managersCache = []
            if (typeof onAssigned === "function") {
                onAssigned(updated, username)
            }
            close()
            showToast(`Chat asignado a ${username}`, "success")
        } catch (error) {
            if (typeof onAssignRollback === "function") {
                onAssignRollback(rollbackState)
            }
            showToast(error.message || "No se pudo asignar el gestor", "error")
        } finally {
            setButtonsDisabled(false)
            isAssignManagerSubmitting = false
        }
    }

    function setup() {
        const { modal, search, close: closeButton } = getNodes()
        if (!modal || modal.dataset.bound) return

        closeButton?.addEventListener("click", close)
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                close()
            }
        })
        search?.addEventListener("input", (event) => {
            window.clearTimeout(searchDebounceTimer)
            const value = event.target.value
            searchDebounceTimer = window.setTimeout(() => {
                renderList(value)
            }, 180)
        })
        modal.dataset.bound = "true"
    }

    return {
        open,
        close,
        setup,
        clearCache() {
            managersCache = []
        },
    }
}
