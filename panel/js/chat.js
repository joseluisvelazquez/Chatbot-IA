import {
    assignConversationManager,
    getConversations,
    getAvailableManagers,
    getMessages,
    closeTechnicalIncident,
    markConversationRead,
    returnConversation,
    sendFileMessage,
    sendMessage,
    takeConversation,
    transferConversation,
    uploadPanelFile
} from "./api.js"
import { resolveMediaUrl } from "./config.js"
import { EMOJIS } from "./emojis.js"
import {
    canAssignManager,
    canOperateSelected,
    createAssignManagerModal,
    createComposerController,
    createConversationOperationHandlers,
    createPaginationState,
    createSidebarController,
    ensureNewMessagesSeparator,
    getLastRenderedDate,
    insertDateSeparator,
    isUserAtBottom,
    normalizePreviewIndex,
    isValidPreviewIndex,
    removeNewMessagesSeparator,
    renderHeader as renderHeaderView,
} from "./chat/index.js"
import { getWebSocket, subscribe as subscribeWebSocket } from "./websocket.js"
import { dispatch } from "./store.js"
import { subscribeStore, getState } from "./store.js"
import { getSelectedSession, setSelectedSession } from "./app.js"



// =========================
// ESTADO GLOBAL
// =========================
let currentSessionId = null
let lastTyping = 0
let unsubscribeChatStore = null
let unsubscribeChatRealtime = null
let lastLoadTrigger = 0
let lastLoadedSessionId = null
let isLoadingChat = false
let isSendingMessage = false
let firstViewerOpen = true
let isFirstLoad = true
let forceRender = false
let viewerShortcutsBound = false
let chatLoadRequestId = 0
let lastMessagesVersion = -1
let lastMessagesSessionKey = null
let lastPreviewVersion = -1
let lastRealtimeResyncAt = 0
let chatViewController = null
let conversationsListController = null
let realtimeStatus = "unknown"

const renderedMessageIdsBySession = new Map()

// =========================
// CONFIG
// =========================
const LOAD_COOLDOWN = 500
const MAX_RENDERED_MESSAGES = 300
const PAGE_SIZE = 30
const REALTIME_RESYNC_COOLDOWN_MS = 1500
const SKELETON_DELAY_MS = 1000
const SLOW_LOAD_DELAY_MS = 3000

let paginationState = createPaginationState()
let mobileResizeBound = false

function getCurrentUser() {
    return window.currentUser || getState().auth?.user || null
}

function isAdmin() {
    return getCurrentUser()?.role === "admin"
}

const sidebarController = createSidebarController({
    getState,
    loadChat,
    getCurrentSessionId: () => currentSessionId,
    getLastLoadedSessionId: () => lastLoadedSessionId,
    isLoadingChat: () => isLoadingChat,
    showMobileChat,
    isAdmin,
})

const composerController = createComposerController({
    emojis: EMOJIS,
    onSend: () => send(),
    onTyping: () => handleTyping(),
})

const assignManagerModal = createAssignManagerModal({
    getAvailableManagers,
    assignConversationManager,
    canAssignManager,
    getSelectedConversation: getSelectedConversationFromState,
    getCurrentSessionId: () => currentSessionId,
    getState,
    onAssignOptimistic: (username) => {
        const sessionId = Number(currentSessionId || 0)
        const previous = sessionId ? getState().conversations.byId[sessionId] || null : null
        if (!previous) return null

        dispatch({
            type: "conversations/upsert",
            payload: {
                ...previous,
                assigned_user_id: username,
                assigned_role: "gestor",
                status_operativo: "assigned_gestor",
                transfer_pending: false,
                _optimistic: true,
            },
        })

        const optimistic = getState().conversations.byId[sessionId]
        renderSelectedConversation(optimistic)
        renderSidebarFromState(getState())
        return previous
    },
    onAssignRollback: (previous) => {
        if (!previous) return
        dispatch({ type: "conversations/upsert", payload: previous })
        renderSelectedConversation(previous)
        renderSidebarFromState(getState())
    },
    onAssigned: (updated) => {
        dispatch({ type: "conversations/upsert", payload: updated })
        const session = getSelectedConversationFromState() || updated
        renderSelectedConversation(session)
        renderSidebarFromState(getState())
    },
    showToast,
})

const conversationOperations = createConversationOperationHandlers({
    api: {
        closeTechnicalIncident,
        getConversations,
        returnConversation,
        takeConversation,
        transferConversation,
    },
    dispatch,
    getCurrentSessionId: () => currentSessionId,
    getState,
    setSelectedSession,
    setCurrentSessionId: (value) => {
        currentSessionId = value
    },
    setLastLoadedSessionId: (value) => {
        lastLoadedSessionId = value
    },
    showMobileConversationList,
    showToast,
    renderSelectedConversation,
    renderSidebar: (state) => renderSidebarFromState(state),
})

//Para imagenes 
let selectedFiles = []
let selectedPreviewIndex = 0

let imageList = []
let imageSet = new Set()
let currentImageIndex = 0

function trackImageUrl(url) {
    if (!url || imageSet.has(url)) return

    imageSet.add(url)
    imageList.push(url)
}

function hidePreviewContainer() {
    const container = document.getElementById("filePreview")
    if (!container) return

    container.classList.add("hidden")
    container.innerHTML = ""
}

function isMobileChatViewport() {
    return window.matchMedia("(max-width: 767px)").matches
}

function getChatShell() {
    return document.getElementById("chatShell")
}

function showMobileChat() {
    const shell = getChatShell()
    if (shell) shell.classList.add("mobile-chat-open")
}

function showMobileConversationList() {
    const shell = getChatShell()
    if (shell) shell.classList.remove("mobile-chat-open")
}

window.showMobileConversationList = showMobileConversationList

function abortChatViewRequests() {
    if (chatViewController) {
        chatViewController.abort()
    }
    chatViewController = new AbortController()
    return chatViewController
}

function abortConversationListRequest() {
    if (conversationsListController) {
        conversationsListController.abort()
    }
    conversationsListController = new AbortController()
    return conversationsListController
}

function renderChatSkeleton(message = "Consultando datos...") {
    const list = document.getElementById("messages")
    if (!list) return

    list.innerHTML = `
        <div class="mx-auto mt-6 flex w-full max-w-3xl flex-col gap-4 px-2" aria-live="polite">
            <div class="text-xs font-medium text-slate-500 dark:text-slate-400">${message}</div>
            ${Array.from({ length: 5 }).map((_, index) => `
                <div class="h-16 animate-pulse rounded-2xl bg-white dark:bg-slate-800 ${index % 2 ? "ml-auto w-2/3" : "w-3/4"}"></div>
            `).join("")}
        </div>
    `
}

function renderInlineChatStatus(message = "Actualizando datos...") {
    const list = document.getElementById("messages")
    if (!list || document.getElementById("chatInlineStatus")) return

    const status = document.createElement("div")
    status.id = "chatInlineStatus"
    status.className = "mx-auto my-2 inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow dark:bg-slate-100 dark:text-slate-900"
    status.textContent = message
    list.prepend(status)
}

function removeInlineChatStatus() {
    document.getElementById("chatInlineStatus")?.remove()
}

function syncPreviewFromStore() {
    const preview = getState().chat.preview
    selectedFiles = Array.isArray(preview.files) ? preview.files : []
    selectedPreviewIndex = normalizePreviewIndex(preview.selectedIndex, selectedFiles.length)
}

function setPreviewFiles(files, selectedIndex = 0) {
    dispatch({
        type: "chat/preview/set_files",
        payload: {
            files: Array.isArray(files) ? files.filter(Boolean) : [],
            selectedIndex
        }
    })
    syncPreviewFromStore()
}

function setPreviewIndex(index) {
    dispatch({
        type: "chat/preview/select",
        payload: { index }
    })
    syncPreviewFromStore()
}

function removePreviewFile(index) {
    syncPreviewFromStore()

    if (!isValidPreviewIndex(index, selectedFiles.length)) return false

    dispatch({
        type: "chat/preview/remove_at",
        payload: { index: Math.trunc(Number(index)) }
    })
    syncPreviewFromStore()
    return true
}

function clearPreviewFiles() {
    dispatch({ type: "chat/preview/clear" })
    syncPreviewFromStore()
}

function getToastContainer() {
    let container = document.getElementById("chatToastContainer")
    if (container) return container

    container = document.createElement("div")
    container.id = "chatToastContainer"
    container.className = "fixed right-4 top-4 z-[70] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2"
    document.body.appendChild(container)
    return container
}

function showToast(message, tone = "info") {
    const container = getToastContainer()
    const toast = document.createElement("div")
    const tones = {
        success: "bg-emerald-600 text-white",
        error: "bg-red-600 text-white",
        info: "bg-slate-900 text-white",
    }
    toast.className = `rounded-lg px-3 py-2 text-sm shadow-lg ${tones[tone] || tones.info}`
    toast.textContent = message
    container.appendChild(toast)
    window.setTimeout(() => {
        toast.remove()
        if (!container.childElementCount) {
            container.remove()
        }
    }, 3000)
}

function renderConversationPlaceholder(message = "Selecciona una conversacion") {
    const header = document.getElementById("chatHeader")
    const list = document.getElementById("messages")

    if (header) {
        renderHeader(null, "", "")
    }

    if (list) {
        list.innerHTML = `
            <div class="flex min-h-[360px] items-center justify-center p-4">
                <div class="max-w-md rounded-lg border border-dashed border-slate-300 bg-white/70 p-6 text-center shadow-sm dark:border-slate-700 dark:bg-slate-900/40">
                    <div class="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-950/40 dark:text-blue-300">
                        <i data-lucide="message-square" class="h-5 w-5"></i>
                    </div>
                    <div class="text-sm font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(message)}</div>
                    <div class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                        Elige un chat de la lista para cargar mensajes, owner operativo y acciones disponibles.
                    </div>
                </div>
            </div>
        `
        if (window.lucide) window.lucide.createIcons()
    }

    removeTyping()
    removeNewMessagesSeparator()
    updateComposerState(null)
}

function clearActiveConversation(options = {}) {
    const {
        message = "Selecciona una conversacion",
        toastMessage = "",
        toastTone = "info",
        forceList = false,
        removeSessionId = null,
    } = options

    const previousSessionId = currentSessionId
    const sessionIdToRemove = Number(removeSessionId || 0)

    chatLoadRequestId += 1
    abortChatViewRequests()
    currentSessionId = null
    lastLoadedSessionId = null
    isLoadingChat = false
    forceRender = false
    setSelectedSession(null)
    dispatch({
        type: "chat/set_loading",
        payload: { sessionId: null }
    })

    if (sessionIdToRemove) {
        dispatch({
            type: "conversations/remove",
            payload: { session_id: sessionIdToRemove }
        })
    }

    if (previousSessionId != null) {
        clearRenderedSession(previousSessionId)
    }

    if (forceList || isMobileChatViewport()) {
        showMobileConversationList()
    }

    renderConversationPlaceholder(message)

    if (toastMessage) {
        showToast(toastMessage, toastTone)
    }
}

async function syncConversationVisibilityFromBackend(options = {}) {
    const { force = false } = options
    const now = Date.now()
    if (!force && now - lastRealtimeResyncAt < REALTIME_RESYNC_COOLDOWN_MS) return

    lastRealtimeResyncAt = now

    try {
        const sessions = await getConversations()
        dispatch({
            type: "conversations/loaded",
            payload: sessions
        })

        if (!currentSessionId) return

        const refreshedState = getState()
        const session = refreshedState.conversations.byId[Number(currentSessionId)] || null

        if (!session) {
            clearActiveConversation({
                message: "La conversacion ya no esta disponible para tu usuario",
                forceList: true,
            })
            return
        }

        renderSelectedConversation(session)
        renderSidebarFromState(refreshedState)
    } catch (error) {
        console.error("No se pudo resincronizar conversaciones tras reconexion:", error)
    }
}

function handleRealtimeConversationEvent(event) {
    if (!event || typeof event !== "object") return

    if (event.type === "socket_status") {
        realtimeStatus = event.status || "unknown"

        const session = getSelectedConversationFromState()
        if (session) {
            renderSelectedConversation(session)
        } else {
            renderConversationPlaceholder()
        }

        if (event.status === "connected") {
            void syncConversationVisibilityFromBackend({ force: true })
        }
        return
    }

    if (event.type === "conversation_removed") {
        const removedId = Number(event.payload?.session_id || 0)
        if (!removedId || Number(currentSessionId) !== removedId) return

        clearActiveConversation({
            message: "La conversacion ya no esta disponible para tu usuario",
            toastMessage: "La conversacion cambio de owner y ya no esta visible para tu usuario",
            toastTone: "info",
            forceList: true,
        })
        return
    }

    if (event.type !== "conversation_update" && event.type !== "chat_operation") {
        return
    }

    const sessionId = Number(event.payload?.id || event.payload?.session_id || 0)
    if (!sessionId || Number(currentSessionId) !== sessionId) return

    const session = getState().conversations.byId[sessionId] || null
    if (!session) {
        clearActiveConversation({
            message: "La conversacion ya no esta disponible para tu usuario",
            forceList: true,
        })
        return
    }

    renderSelectedConversation(session)
}

function isChatLoadInvalid(requestId, sessionId) {
    if (requestId !== chatLoadRequestId) return true
    if (Number(currentSessionId) !== Number(sessionId)) return true
    return !Boolean(getState().conversations.byId[Number(sessionId)])
}

// =========================
// INIT
// =========================
export async function initConversationsPage() {
    window.send = send
    window.handleTyping = handleTyping
    window.handleKeyDown = handleKeyDown
    window.autoResize = autoResize
    window.openAssignManagerModal = openAssignManagerModal
    window.closeAssignManagerModal = closeAssignManagerModal
    
    // reset visual de la vista al volver a entrar al módulo
    lastLoadedSessionId = null
    isLoadingChat = false
    lastMessagesVersion = -1
    lastMessagesSessionKey = null
    lastPreviewVersion = -1
    forceRender = true

    if (!mobileResizeBound) {
        window.addEventListener("resize", () => {
            if (!isMobileChatViewport() || currentSessionId) return
            showMobileConversationList()
        })
        mobileResizeBound = true
    }

    if (unsubscribeChatStore) unsubscribeChatStore()
    if (unsubscribeChatRealtime) unsubscribeChatRealtime()

    let lastConversationSignature = ""

    unsubscribeChatStore = subscribeStore((state) => {
        const sessionKey = currentSessionId == null ? null : String(currentSessionId)
        const currentMessagesVersion = sessionKey
            ? Number(state.messages.versionsBySessionId[sessionKey] || 0)
            : -1

        if (
                sessionKey &&
                (
                    forceRender || 
                    sessionKey !== lastMessagesSessionKey ||
                    currentMessagesVersion !== lastMessagesVersion
                )
            ) {
            console.time("renderMessages")
            renderMessagesIncremental(state)
            forceRender = false
            console.timeEnd("renderMessages")
            lastMessagesVersion = currentMessagesVersion
            lastMessagesSessionKey = sessionKey
        }

        if (state.conversations._version !== lastConversationSignature) {
            console.time("renderSidebar")
            renderSidebarFromState(state)
            const selectedConversation = currentSessionId
                ? state.conversations.byId[Number(currentSessionId)]
                : null
            if (selectedConversation) {
                renderHeader(
                    selectedConversation,
                    selectedConversation.display_name || selectedConversation.name || selectedConversation.phone || "Cliente sin nombre",
                    selectedConversation.phone || ""
                )
                updateComposerState(selectedConversation)
            } else if (currentSessionId) {
                clearActiveConversation({
                    message: "La conversacion ya no esta disponible para tu usuario",
                    toastMessage: "La conversacion cambio de owner y ya no esta visible para tu usuario",
                    toastTone: "info",
                    forceList: true,
                })
            }
            console.timeEnd("renderSidebar")
            lastConversationSignature = state.conversations._version
        }

        if (state.chat._previewVersion !== lastPreviewVersion) {
            syncPreviewFromStore()
            lastPreviewVersion = state.chat._previewVersion
        }
    })

    unsubscribeChatRealtime = subscribeWebSocket(handleRealtimeConversationEvent)

    let sessions = []
    const listRequest = abortConversationListRequest()

    try {
        sessions = await getConversations(100, 0, { signal: listRequest.signal })
    } catch (error) {
        if (listRequest.signal.aborted) return
        console.error("No se pudieron cargar las conversaciones:", error)
        showToast(error.message || "No se pudieron cargar las conversaciones", "error")
        sessions = []
    }

    dispatch({
        type: "conversations/loaded",
        payload: sessions
    })
    
    const savedSearch = localStorage.getItem("chatSearch")
    if (savedSearch) {
        sidebarController.hydrateSearch(savedSearch)
    }

    console.time("renderSidebar initial")
    renderSidebarFromState(getState())
    console.timeEnd("renderSidebar initial")

    const state = getState()
    let selected = getSelectedSession()

    if (!selected) {
        const params = new URLSearchParams(window.location.search)
        const sessionIdFromUrl = params.get("session_id")

        if (sessionIdFromUrl) {
            const sessionFromStore = state.conversations.byId[Number(sessionIdFromUrl)]
            selected = {
                sessionId: Number(sessionIdFromUrl),
                phone: sessionFromStore?.phone || null
            }
        }
    }

    if (!selected) {
        const saved = localStorage.getItem("lastSession")
        if (saved) {
            try {
                selected = JSON.parse(saved)
            } catch {}
        }
    }

    if (selected?.sessionId) {
    const sessionIdNum = Number(selected.sessionId)
    const sessionFromStore = state.conversations.byId[sessionIdNum]

    if (!sessionFromStore) {
            console.warn("Sesión inválida desde localStorage, limpiando...")
            setSelectedSession(null)
            localStorage.removeItem("lastSession")
            selected = null
        } else {
            await loadChat(
                sessionIdNum,
                selected.phone || sessionFromStore.phone,
                selected.name || sessionFromStore.name || null
            )
        }
    }

    if (!getSelectedSession()?.sessionId && !isMobileChatViewport()) {
        const firstId = state.conversations.order[0]

        if (!firstId) {
            console.warn("No hay conversaciones disponibles")
        } else {
            const session = state.conversations.byId[firstId]

            if (session) {
                await loadChat(session.id, session.phone, session.name || null)
            }
        }
    }

    if (!getSelectedSession()?.sessionId && isMobileChatViewport()) {
        showMobileConversationList()
    }

    
    requestAnimationFrame(() => {
        setupInputHandler()
        setupEmojiPicker()
        setupVirtualScroll()
        setupBottomSeparatorCleaner()
        setupSearchAndFilters()
        setupDragAndDrop()
        setupAssignManagerModal()

        const fileInput = document.getElementById("fileInput")

        if (fileInput && !fileInput.dataset.bound) {
            fileInput.addEventListener("change", (e) => {
                const files = Array.from(e.target.files || [])
                if (files.length > 0) {
                    setPreviewFiles([...selectedFiles, ...files], 0)
                    renderMultiPreview()
                }

                fileInput.value = ""
                setTimeout(() => {
                    const input = document.getElementById("messageInput")
                    if (input) input.focus()
                }, 0)
            })
            fileInput.dataset.bound = "true"
        }
    })

    if (!viewerShortcutsBound) {
        document.addEventListener("keydown", (e) => {
            const viewer = document.getElementById("imageViewer")
            if (!viewer || viewer.classList.contains("hidden")) return

            if (["ArrowLeft", "ArrowRight", "Escape"].includes(e.key)) {
                e.preventDefault()
            }

            if (e.key === "ArrowLeft") prevImage()
            if (e.key === "ArrowRight") nextImage()
            if (e.key === "Escape") closeImageViewer()
        })

        viewerShortcutsBound = true
    }
}

// =========================
// HELPERS
// =========================
function getRenderedSet(sessionId) {
    if (!renderedMessageIdsBySession.has(sessionId)) {
        renderedMessageIdsBySession.set(sessionId, new Set())
    }
    return renderedMessageIdsBySession.get(sessionId)
}

function clearRenderedSession(sessionId) {
    renderedMessageIdsBySession.set(sessionId, new Set())
}

function normalizeMessage(msg) {
    if (!msg) return {}

    const normalized = { ...msg }

    if (!normalized.type && normalized.media_url) {
        normalized.type = "image"
    }

    if (normalized.media_url) {
        normalized.media_url = resolveMediaUrl(normalized.media_url)
    }

    if (!normalized.created_at) {
        normalized.created_at = new Date().toISOString()
    }

    return normalized
}

function escapeHtml(value) {
    if (value == null) return ""

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
}

function formatTime(dateString) {
    const date = new Date(dateString)
    return date.toLocaleTimeString("es-MX", {
        hour: "2-digit",
        minute: "2-digit"
    })
}

function formatDateSeparator(dateString) {
    const date = new Date(dateString)
    const today = new Date()

    const isToday = date.toDateString() === today.toDateString()

    const yesterday = new Date()
    yesterday.setDate(today.getDate() - 1)

    const isYesterday = date.toDateString() === yesterday.toDateString()

    if (isToday) return "Hoy"
    if (isYesterday) return "Ayer"

    return date.toLocaleDateString("es-MX", {
        weekday: "long",
        day: "numeric",
        month: "long"
    })
}

function formatWhatsAppText(text) {
    if (!text) return ""

    return escapeHtml(text)
        .replace(/\n/g, "<br>")
        .replace(/\*(.*?)\*/g, "<b>$1</b>")
        .replace(/_(.*?)_/g, "<i>$1</i>")
        .replace(/~(.*?)~/g, "<s>$1</s>")
        .replace(/`(.*?)`/g, "<code>$1</code>")
}

const BUTTON_LABELS = {
    MENU_VERIFICACION: "📋 Menú de verificación",
    FOLIO_SI: "✔️ Confirmó folio",
    NOMBRE_SI: "✔️ Confirmó nombre",
    DOM_SI: "🏠 Confirmó domicilio",
    FECHA_SI: "📅 Confirmó fecha",
    PROD_SI: "📦 Confirmó producto",
    PRODESTADOSI: "📦 Producto en buen estado",
    PAGO_SI: "💰 Confirmó pago",
    PAGOS_OK: "💳 Entendió pagos",
    PLAN3_OK: "📆 Aceptó plan 3 meses",
    PLANES_OK: "📊 Revisó planes",
    BEN_OK: "🎉 Confirmó beneficios"
}

function formatButtonMessage(text) {
    if (!text) return text

    const match = text.match(/\[BOTON\]\s*(.+)/)
    if (!match) return text

    const key = match[1].trim()

    if (BUTTON_LABELS[key]) {
        return `
            <span class="
                inline-flex items-center gap-1
                bg-gray-100 dark:bg-slate-500
                text-gray-800 dark:text-white
                border border-gray-200 dark:border-slate-400
                px-3 py-1 rounded-md text-xs font-medium
                shadow-none dark:shadow-sm
            ">
                🔘 ${BUTTON_LABELS[key]}
            </span>
        `
    }

    let label = key

    if (key.endsWith("_SI")) {
        label = "✔️ Confirmó " + key.replace("_SI", "").toLowerCase()
    } else if (key.endsWith("_NO")) {
        label = "❌ Rechazó " + key.replace("_NO", "").toLowerCase()
    } else if (key.endsWith("_DUDA")) {
        label = "❓ Tiene dudas"
    } else if (key.endsWith("_OK")) {
        label = "✅ Confirmó"
    } else {
        label = key.replaceAll("_", " ").toLowerCase()
    }

    return `
        <span class="
            inline-flex items-center gap-1
            bg-gray-100 dark:bg-slate-500
            text-gray-800 dark:text-white
            border border-gray-200 dark:border-slate-400
            px-3 py-1 rounded-md text-xs font-medium
            shadow-none dark:shadow-sm
        ">
            🔘 ${label}
        </span>
    `
}

// =========================
// SIDEBAR
// =========================
function renderSidebarFromState(state) {
    sidebarController.render(state)
}

// =========================
// MENSAJES
// =========================
function createMessageNode(rawMsg, timeOverride = "") {

    const msg = normalizeMessage(rawMsg)

    const cleanContent =
        msg.content && msg.content.trim() !== "" && msg.content !== "[MEDIA]"
            ? msg.content
            : null

    const wrapper = document.createElement("div")
    wrapper.className = "w-full flex opacity-0 translate-y-2 transition-all duration-300"

    requestAnimationFrame(() => {
        wrapper.classList.remove("opacity-0", "translate-y-2")
    })

    const bubble = document.createElement("div")
    let bubbleClass = "inline-block max-w-[88%] sm:max-w-[78%] md:max-w-[70%] min-w-[80px] px-3 py-2 rounded-lg text-sm shadow-sm break-words"

    if (msg.direction === "in") {
        wrapper.classList.add("justify-start")
        bubbleClass += " bg-gray-200 text-black dark:bg-slate-700 dark:text-white"
    } else if (msg.direction === "out") {
        wrapper.classList.add("justify-end")
        bubbleClass += " bg-blue-100 text-black"
    } else if (msg.direction === "agent") {
        wrapper.classList.add("justify-end")
        bubbleClass += " bg-green-200 text-black"
    } else {
        wrapper.classList.add("justify-start")
        bubbleClass += " bg-white text-black"
    }

    bubble.className = bubbleClass

    const time = timeOverride || (msg.created_at ? formatTime(msg.created_at) : "")
    const label =
        msg.direction === "out" ? "Assistant" :
        msg.direction === "agent" ? "Tú 🧑‍💻" :
        msg.direction === "in" ? "Cliente 👤" :
        ""

    let bodyContent = ""
    const mediaUrl = msg.media_url

    if (mediaUrl) {
        if (msg.type === "image") {
            trackImageUrl(mediaUrl)
            bodyContent = `
                <div class="flex flex-col gap-1">
                    <img
                        src="${mediaUrl}"
                        data-open-viewer
                        class="max-w-full sm:max-w-[380px] max-h-[420px] object-contain rounded-lg cursor-pointer hover:opacity-90"
                        onclick="openImageViewer('${mediaUrl}')"
                        loading="lazy"
                    />
                    ${
                        cleanContent
                            ? `<span class="text-sm">${formatWhatsAppText(cleanContent)}</span>`
                            : ""
                    }
                </div>
            `
        } else {
            bodyContent = `
                <a href="${mediaUrl}" target="_blank" rel="noopener noreferrer"
                    class="flex items-center gap-3 p-2 rounded-lg bg-gray-100 dark:bg-slate-600
                        hover:bg-gray-200 dark:hover:bg-slate-500 transition cursor-pointer">

                    <div class="w-10 h-10 flex items-center justify-center bg-red-500 text-white rounded-md text-xs font-bold">
                        PDF
                    </div>

                    <div class="flex flex-col min-w-0">
                        <span class="text-sm font-medium truncate">
                            ${msg.file_name || "Archivo"}
                        </span>
                        <span class="text-xs text-gray-500 dark:text-gray-300">
                            Abrir documento
                        </span>
                    </div>

                </a>

                ${
                    cleanContent
                        ? `<span class="text-sm mt-1 block">${formatWhatsAppText(cleanContent)}</span>`
                        : ""
                }
            `
        }
    } else if (typeof msg.content === "string" && msg.content.trim().startsWith("[BOTON]")) {
        bodyContent = `<div>${formatButtonMessage(msg.content)}</div>`
    } else {
        bodyContent = `<div>${formatWhatsAppText(msg.content)}</div>`
    }

    const metaClass =
        msg.direction === "in"
            ? "text-gray-900 dark:text-gray-300"
            : "text-gray-800 dark:!text-black"

    const messageFailed = ["failed", "error"].includes(String(msg.status || msg.delivery_status || "").toLowerCase())
        || Boolean(msg.failed || msg.error)
    const retryAction = messageFailed
        ? `
            <div class="mt-2 flex items-center justify-end gap-2 text-[11px]">
                <span class="rounded-full bg-red-100 px-2 py-1 font-medium text-red-700 dark:bg-red-950/40 dark:text-red-300">
                    No enviado
                </span>
                ${typeof window.retryFailedMessage === "function"
                    ? `<button
                        type="button"
                        data-retry-message-id="${escapeHtml(msg.id || "")}"
                        class="rounded-md border border-red-200 bg-white px-2 py-1 font-medium text-red-700 transition hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 dark:border-red-900 dark:bg-slate-900 dark:text-red-300 dark:hover:bg-red-950/30"
                        title="Reintentar envio"
                    >
                        Reintentar
                    </button>`
                    : ""
                }
            </div>
        `
        : ""

    bubble.innerHTML = `
        ${bodyContent}
        <div class="text-[10px] ${metaClass} mt-1 text-right">
            ${label ? `${label} · ${time}` : time}
        </div>
        ${retryAction}
    `

    const retryButton = bubble.querySelector("[data-retry-message-id]")
    if (retryButton && typeof window.retryFailedMessage === "function") {
        retryButton.onclick = () => window.retryFailedMessage(msg.id)
    }

    wrapper.appendChild(bubble)
    return wrapper
}

function appendMessageWithSeparators(list, msg, options = {}) {
    const { showNewIncomingSeparator = false } = options
    const normalized = normalizeMessage(msg)

    const currentDate = new Date(normalized.created_at).toDateString()
    const lastDate = getLastRenderedDate(list)

    if (lastDate !== currentDate) {
        insertDateSeparator(list, normalized.created_at)
    }

    if (showNewIncomingSeparator && normalized.direction === "in") {
        ensureNewMessagesSeparator(list)
    }

    const node = createMessageNode(normalized)
    node.dataset.messageId = normalized.id ?? `${normalized.content ?? "media"}-${normalized.created_at}`
    node.dataset.messageDate = currentDate

    list.appendChild(node)
}

// =========================
// RENDER INCREMENTAL
// =========================
function renderMessagesIncremental(state) {
    const container = document.getElementById("messagesContainer")
    const list = document.getElementById("messages")

    if (!container || !list || !currentSessionId) return

    const messages = state.messages.bySessionId[currentSessionId] || []
    const renderedSet = getRenderedSet(currentSessionId)
    const wasAtBottom = isUserAtBottom(container)
    const fragment = document.createDocumentFragment()
    let lastDate = getLastRenderedDate(list)

    for (let i = 0; i < messages.length; i++) {
        const msg = normalizeMessage(messages[i])
        if (msg.type === "image" && msg.media_url) {
            trackImageUrl(msg.media_url)
        }
        if (!msg.id) continue
        const id = `msg-${msg.id}`

        if (renderedSet.has(id)) continue

        const shouldShowNewSeparator =
            !wasAtBottom &&
            msg.direction === "in" &&
            lastLoadedSessionId === currentSessionId &&
            renderedSet.size > 0

        const currentDate = new Date(msg.created_at).toDateString()

        if (lastDate !== currentDate) {
            const sep = document.createElement("div")
            sep.className = "flex justify-center my-2"
            sep.dataset.separatorType = "date"
            sep.innerHTML = `
                <div class="text-xs px-3 py-1 rounded-full bg-gray-300 dark:bg-slate-700 text-gray-700 dark:text-gray-200">
                    ${formatDateSeparator(msg.created_at)}
                </div>
            `
            fragment.appendChild(sep)
            lastDate = currentDate
        }

        if (shouldShowNewSeparator && !document.getElementById("newMessagesSeparator")) {
            const newSep = document.createElement("div")
            newSep.id = "newMessagesSeparator"
            newSep.className = "flex justify-center my-2"
            newSep.dataset.separatorType = "new"
            newSep.innerHTML = `
                <div class="text-xs px-3 py-1 rounded-full bg-blue-500 text-white">
                    Nuevos mensajes
                </div>
            `
            fragment.appendChild(newSep)
        }

        const node = createMessageNode(msg)
        node.dataset.messageId = id
        node.dataset.messageDate = currentDate

        fragment.appendChild(node)
        renderedSet.add(id)

        if (renderedSet.size > MAX_RENDERED_MESSAGES) {
            const firstKey = renderedSet.values().next().value
            renderedSet.delete(firstKey)
        }
    }

    if (fragment.childNodes.length > 0) {
        list.appendChild(fragment)

        if (isFirstLoad) {
            // SOLO UNA VEZ al abrir chat
            requestAnimationFrame(() => {
                container.scrollTop = container.scrollHeight
            })
            isFirstLoad = false
        } else if (wasAtBottom) {
            // solo si ya estabas abajo
            requestAnimationFrame(() => {
                container.scrollTop = container.scrollHeight
                removeNewMessagesSeparator()
            })
        }
    }
}

// =========================
// PAGINACIÓN
// =========================
async function loadMoreMessages() {
    if (!currentSessionId) return
    if (paginationState.loading) return
    if (!paginationState.hasMore) return

    const container = document.getElementById("messagesContainer")
    const list = document.getElementById("messages")
    if (!container || !list) return

    paginationState.loading = true

    const prevScrollTop = container.scrollTop
    const prevHeight = container.scrollHeight

    showTopLoader()

    try {
        const res = await getMessages(currentSessionId, PAGE_SIZE, paginationState.offset)

        let newMessages = []

        if (Array.isArray(res)) newMessages = res
        else if (Array.isArray(res.messages)) newMessages = res.messages
        else if (Array.isArray(res.data)) newMessages = res.data
        else if (Array.isArray(res.items)) newMessages = res.items

        if (newMessages.length === 0) {
            paginationState.hasMore = false
            return
        }

        paginationState.offset += newMessages.length
        paginationState.hasMore = Boolean(res?.has_more) || newMessages.length === PAGE_SIZE

        const renderedSet = getRenderedSet(currentSessionId)
        const fragment = document.createDocumentFragment()
        let tempDate = null

        for (let i = 0; i < newMessages.length; i++) {
            const msg = normalizeMessage(newMessages[i])
            const id = msg.id ? `msg-${msg.id}` : null
            if (!id) continue

            if (renderedSet.has(id)) continue

            const currentDate = new Date(msg.created_at).toDateString()

            if (tempDate !== currentDate) {
                const separator = document.createElement("div")
                separator.className = "flex justify-center my-2"
                separator.dataset.separatorType = "date"
                separator.innerHTML = `
                    <div class="text-xs px-3 py-1 rounded-full bg-gray-300 dark:bg-slate-700 text-gray-700 dark:text-gray-200">
                        ${formatDateSeparator(msg.created_at)}
                    </div>
                `
                fragment.appendChild(separator)
                tempDate = currentDate
            }

            const node = createMessageNode(msg)
            node.dataset.messageId = id
            node.dataset.messageDate = currentDate

            fragment.appendChild(node)
            renderedSet.add(id)
        }

        list.prepend(fragment)

        requestAnimationFrame(() => {
            const newHeight = container.scrollHeight
            const delta = newHeight - prevHeight
            container.scrollTop = prevScrollTop + delta
        })
    } catch (err) {
        console.error("Error lazy load:", err)
    } finally {
        paginationState.loading = false
        hideTopLoader()
    }
}

// =========================
// LOAD CHAT
// =========================
export async function loadChat(sessionId, phone, name = null) {
    const header = document.getElementById("chatHeader")
    const list = document.getElementById("messages")
    const numericSessionId = Number(sessionId)

    if (!Number.isFinite(numericSessionId) || numericSessionId <= 0) return

    const alreadyRendered =
        currentSessionId === numericSessionId &&
        lastLoadedSessionId === numericSessionId &&
        header &&
        header.textContent?.trim() &&
        list &&
        list.childElementCount > 0

    if (alreadyRendered) {
        showMobileChat()
        return
    }

    if (isLoadingChat && currentSessionId === numericSessionId) {
        showMobileChat()
        return
    }

    const state = getState()
    const sessionInfo = state.conversations.byId[numericSessionId]

    if (!sessionInfo) {
        console.warn("Intentando cargar sesion inexistente:", sessionId)
        return
    }

    const requestId = ++chatLoadRequestId
    const requestController = abortChatViewRequests()
    const requestSignal = requestController.signal
    imageList = []
    currentImageIndex = 0
    thumbsRendered = false
    imageSet = new Set()
    closeImageViewer()
    isFirstLoad = true

    const previousSessionId = currentSessionId
    const isSameChat = previousSessionId === numericSessionId

    currentSessionId = numericSessionId
    setSelectedSession({
        sessionId: numericSessionId,
        phone,
        name
    })
    showMobileChat()

    renderSidebarFromState(getState())
    isLoadingChat = true
    dispatch({
        type: "chat/set_loading",
        payload: { sessionId: numericSessionId }
    })

    const safePhone = phone || sessionInfo?.phone || ""
    const displayName = sessionInfo?.display_name || sessionInfo?.name || name || safePhone || "Cliente sin nombre"
    const skeletonTimer = window.setTimeout(() => {
        if (!isChatLoadInvalid(requestId, numericSessionId)) {
            renderChatSkeleton("Consultando mensajes...")
        }
    }, SKELETON_DELAY_MS)
    const slowTimer = window.setTimeout(() => {
        if (!isChatLoadInvalid(requestId, numericSessionId)) {
            renderInlineChatStatus("Sincronizando...")
        }
    }, SLOW_LOAD_DELAY_MS)


    try {
        if (isChatLoadInvalid(requestId, numericSessionId)) return

        renderHeader(sessionInfo, displayName, safePhone)
        updateComposerState(sessionInfo)

        try {
            await markConversationRead(numericSessionId, { signal: requestSignal })
        } catch (err) {
            if (requestSignal.aborted) return
            const status = Number(err?.status || 0)

            if (status === 403 || status === 404) {
                clearActiveConversation({
                    message: "La conversacion ya no esta disponible para tu usuario",
                    toastMessage: err.message || "Ya no tienes acceso a esta conversacion",
                    toastTone: "error",
                    forceList: true,
                    removeSessionId: numericSessionId,
                })
                return
            }

            console.error("No se pudo marcar la conversacion como leida:", err)
            showToast(err.message || "No se pudo actualizar la lectura de la conversacion", "error")
        }
        if (isChatLoadInvalid(requestId, numericSessionId)) return

        paginationState = {
            offset: 0,
            loading: false,
            hasMore: true
        }

        if (list) {
            list.innerHTML = ""
            clearRenderedSession(numericSessionId)
            removeNewMessagesSeparator()
        }

        const cachedMessages = state.messages.bySessionId[String(numericSessionId)] || []
        if (cachedMessages.length > 0 && list && list.childElementCount === 0) {
            renderMessagesIncremental(state)
        }

        let messages = null
        try {
            messages = await getMessages(numericSessionId, PAGE_SIZE, 0, { signal: requestSignal })
        } catch (error) {
            if (requestSignal.aborted) return
            const status = Number(error?.status || 0)

            if (status === 403 || status === 404) {
                clearActiveConversation({
                    message: "La conversacion ya no esta disponible para tu usuario",
                    toastMessage: error.message || "La conversacion ya no esta disponible para tu usuario",
                    toastTone: "error",
                    forceList: true,
                    removeSessionId: numericSessionId,
                })
                return
            }

            console.error("No se pudieron cargar los mensajes del chat:", error)
            showToast(error.message || "No se pudieron cargar los mensajes del chat", "error")
            return
        }
        if (isChatLoadInvalid(requestId, numericSessionId)) return

        let messagesList = []

        if (Array.isArray(messages)) messagesList = messages
        else if (Array.isArray(messages.messages)) messagesList = messages.messages
        else if (Array.isArray(messages.data)) messagesList = messages.data
        else if (Array.isArray(messages.items)) messagesList = messages.items

        if (!isSameChat) {
            dispatch({
                type: "messages/loaded",
                payload: {
                    sessionId: numericSessionId,
                    items: messagesList
                }
            })
        }

        paginationState.offset = messagesList.length
        paginationState.hasMore = Boolean(messages?.has_more) || messagesList.length === PAGE_SIZE
        lastLoadedSessionId = numericSessionId

    } finally {
        window.clearTimeout(skeletonTimer)
        window.clearTimeout(slowTimer)
        removeInlineChatStatus()
        if (requestId === chatLoadRequestId) {
            isLoadingChat = false
            dispatch({
                type: "chat/set_loading",
                payload: { sessionId: null }
            })
        }
    }
}

// =========================
// SEND
// =========================
function handleKeyDown(event) {
    composerController.handleKeyDown(event)
}
export async function send() {
    if (isSendingMessage) return

    syncPreviewFromStore()

    const input = document.getElementById("messageInput")
    if (!input) return

    const content = input.value.trim()

    if (!content && selectedFiles.length === 0) return
    if (!currentSessionId) return

    const session = getSelectedConversationFromState()

    if (!session) {
        showToast("Conversación inválida", "error")
        return
    }

    if (!canOperateSelected(session)) {
        showToast("No puedes responder este chat con el owner actual", "error")
        return
    }

    const textToSend = content

    isSendingMessage = true
    input.value = ""
    input.focus()
    removeTyping()

    try {
        if (selectedFiles.length > 0) {
            for (let i = 0; i < selectedFiles.length; i++) {
                const file = selectedFiles[i]
                const data = await uploadPanelFile(file)

                await sendFileMessage({
                    session_id: currentSessionId,
                    media_url: data.url,
                    file_name: data.filename,
                    type: file.type.startsWith("image") ? "image" : "document",
                    content: i === 0 ? (textToSend || null) : null
                })
            }

            removeAllFiles()
        } else {
            await sendMessage({
                session_id: currentSessionId,
                content: textToSend
            })
        }
    } catch (error) {
        console.error("Error enviando mensaje:", error)
        showToast(error.message || "No se pudo enviar el mensaje", "error")
    } finally {
        isSendingMessage = false
    }
}

async function sendFile(file) {
    if (!file || !currentSessionId) return

    if (file.size > 10 * 1024 * 1024) {
        alert("Archivo demasiado grande")
        return
    }

    try {
        const data = await uploadPanelFile(file)

        //  NO render optimista para evitar duplicados con WS
        await sendFileMessage({
            session_id: currentSessionId,
            media_url: data.url,
            file_name: data.filename,
            type: file.type.startsWith("image") ? "image" : "document"
        })
    } catch (err) {
        console.error("Error subiendo archivo:", err)
    }
}

// =========================
// TYPING
// =========================
function showTyping(text = "✍️ escribiendo...") {
    removeTyping()

    const container = document.getElementById("messages")
    if (!container) return

    const div = document.createElement("div")
    div.id = "typing"
    div.className = "w-fit max-w-[88%] md:max-w-[42rem] text-xs text-gray-500 italic self-start bg-white px-3 py-2 rounded-lg shadow-sm"
    div.innerText = text

    container.appendChild(div)
}

function removeTyping() {
    const typing = document.getElementById("typing")
    if (typing) typing.remove()
}

function sendTypingEvent() {
    const socket = getWebSocket()

    if (!socket || socket.readyState !== WebSocket.OPEN) return
    if (!currentSessionId) return

    socket.send(JSON.stringify({
        type: "typing",
        session_id: currentSessionId
    }))
}

function handleTyping() {
    const now = Date.now()

    if (now - lastTyping < 1000) return

    lastTyping = now
    sendTypingEvent()
}

// =========================
// SCROLL HELPERS
// =========================
function setupVirtualScroll() {
    const container = document.getElementById("messagesContainer")
    if (!container) return
    if (container.dataset.virtualBound === "true") return

    let ticking = false

    container.addEventListener("scroll", () => {
        if (ticking) return
        ticking = true

        requestAnimationFrame(() => {
            const now = Date.now()

            if (isUserAtBottom(container)) {
                removeNewMessagesSeparator()
            }

            const nearTop = container.scrollTop < 80
            const canTrigger = (now - lastLoadTrigger) > LOAD_COOLDOWN

            if (nearTop && canTrigger && !paginationState.loading) {
                lastLoadTrigger = now
                loadMoreMessages()
            }

            ticking = false
        })
    })

    container.dataset.virtualBound = "true"
}

function setupBottomSeparatorCleaner() {
    const container = document.getElementById("messagesContainer")
    if (!container || container.dataset.separatorCleanerBound === "true") return

    container.addEventListener("scroll", () => {
        if (isUserAtBottom(container)) {
            removeNewMessagesSeparator()
        }
    })

    container.dataset.separatorCleanerBound = "true"
}

function showTopLoader() {
    if (document.getElementById("topLoader")) return

    const container = document.getElementById("messages")
    if (!container) return

    const div = document.createElement("div")
    div.id = "topLoader"
    div.className = "text-center text-xs text-gray-400 py-2"
    div.innerText = "Cargando mensajes..."

    container.prepend(div)
}

function hideTopLoader() {
    const el = document.getElementById("topLoader")
    if (el) el.remove()
}

// =========================
// EMOJIS
// =========================
function setupInputHandler() {
    composerController.setupInputHandler()
}

function setupEmojiPicker() {
    composerController.setupEmojiPicker()
}

function autoResize(el) {
    composerController.autoResize(el)
}

function setupSearchAndFilters() {
    sidebarController.setupFilters()
}

function renderMultiPreview() {
    syncPreviewFromStore()
    const container = document.getElementById("filePreview")
    if (!container) return
    if (selectedFiles.length === 0) {
        hidePreviewContainer()
        return
    }

    const mainFile = selectedFiles[selectedPreviewIndex]
    if (!mainFile) {
        setPreviewIndex(0)
        return
    }

    const mainUrl = URL.createObjectURL(mainFile)

    const isImage = mainFile.type.startsWith("image")
    const isPDF = mainFile.type === "application/pdf"

    container.classList.remove("hidden")

    container.innerHTML = `
        <div class="flex flex-col items-center w-full gap-2">

            <div class="relative w-full max-w-[520px]">
                ${
                    isImage
                    ? `
                        <img 
                            id="mainPreviewImage"
                            src="${mainUrl}" 
                            class="w-full max-h-[420px] object-contain rounded-xl"
                        />
                    `
                    : isPDF
                    ? `
                        <embed
                            id="mainPreviewImage"
                            src="${mainUrl}"
                            type="application/pdf"
                            class="w-full h-[420px] rounded-xl bg-white"
                        />
                    `
                    : `
                        <div 
                            id="mainPreviewImage"
                            class="w-full max-w-[520px] h-[200px] flex flex-col items-center justify-center bg-gray-300 dark:bg-slate-700 rounded-xl text-sm"
                        >
                            📄 ${escapeHtml(mainFile.name)}
                        </div>
                    `
                }

                <button
                    type="button"
                    onclick="removeCurrentFile(event)"
                    class="absolute top-2 right-2 bg-black/70 text-white rounded-full w-7 h-7 flex items-center justify-center hover:bg-red-600"
                >
                    ✕
                </button>
            </div>

            <div id="thumbContainer"
                class="flex gap-2 overflow-x-auto max-w-[600px] px-2 pb-1 pt-1 items-center">
            </div>
        </div>
    `
    
    const thumbContainer = document.getElementById("thumbContainer")

    thumbContainer.innerHTML = selectedFiles.map((file, i) => {
        const url = URL.createObjectURL(file)
        return `
            <div class="relative shrink-0 group">
                ${file.type.startsWith("image") 
                    ? `
                        <img
                            src="${url}"
                            data-thumb
                            onclick="selectPreview(${i})"
                            class="
                                w-16 h-16 object-cover rounded-md cursor-pointer
                                ${i === selectedPreviewIndex 
                                    ? "ring-2 ring-green-500" 
                                    : "opacity-70 hover:opacity-100"}
                            "
                        />
                    `
                    : `
                        <div
                            data-thumb
                            onclick="selectPreview(${i})"
                            class="
                                w-16 h-16 flex items-center justify-center
                                bg-red-500 text-white text-xs font-bold
                                rounded-md cursor-pointer
                                ${i === selectedPreviewIndex 
                                    ? "ring-2 ring-green-500" 
                                    : "opacity-70 hover:opacity-100"}
                            "
                        >
                            PDF
                        </div>
                    `
                }

                <button
                    type="button"
                    onclick="removeFileAtIndex(${i}, event)"
                    class="absolute top-1 right-1 bg-black/70 text-white text-xs w-5 h-5 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition"
                >
                    ✕
                </button>
            </div>
        `
    }).join("")

    const input = document.getElementById("messageInput")
    if (input) input.focus()
}


function updatePreviewUI() {
    syncPreviewFromStore()
    const container = document.getElementById("mainPreviewImage")
    if (!container) return

    const file = selectedFiles[selectedPreviewIndex]
    if (!file) {
        renderMultiPreview()
        return
    }

    const isImage = file.type.startsWith("image")
    const isPDF = file.type === "application/pdf"

    const newUrl = URL.createObjectURL(file)

    if (isImage) {
        if (container.tagName === "IMG") {
            container.src = newUrl
        } else {
            container.outerHTML = `
                <img
                    id="mainPreviewImage"
                    src="${newUrl}"
                    class="w-full max-h-[420px] object-contain rounded-xl"
                />
            `
        }
    } 
    else if (isPDF) {
        container.outerHTML = `
            <embed
                id="mainPreviewImage"
                src="${newUrl}"
                type="application/pdf"
                class="w-full h-[420px] rounded-xl bg-white"
            />
        `
    } 
    else {
        container.outerHTML = `
            <div 
                id="mainPreviewImage"
                class="w-full max-w-[520px] h-[200px] flex items-center justify-center bg-gray-300 dark:bg-slate-700 rounded-xl text-sm"
            >
                📄 ${escapeHtml(file.name)}
            </div>
        `
    }

    document.querySelectorAll("[data-thumb]").forEach((el, i) => {
        if (i === selectedPreviewIndex) {
            el.classList.add("ring-2", "ring-green-500")
            el.classList.remove("opacity-70")
        } else {
            el.classList.remove("ring-2", "ring-green-500")
            el.classList.add("opacity-70")
        }
    })
}


window.selectPreview = function (index) {
    syncPreviewFromStore()

    if (!isValidPreviewIndex(index, selectedFiles.length)) return

    const nextIndex = Math.trunc(Number(index))
    if (nextIndex === selectedPreviewIndex) return

    setPreviewIndex(nextIndex)
    updatePreviewUI()
}

window.removeAllFiles = function () {
    clearPreviewFiles()
    hidePreviewContainer()
}

function getSelectedConversationFromState() {
    if (!currentSessionId) return null
    return getState().conversations.byId[Number(currentSessionId)] || null
}

function closeAssignManagerModal() {
    assignManagerModal.close()
}

async function openAssignManagerModal() {
    await assignManagerModal.open()
}

function setupAssignManagerModal() {
    assignManagerModal.setup()
}

function renderSelectedConversation(session) {
    if (!session) {
        renderHeader(null, '', '')
        updateComposerState(null)
        return
    }

    renderHeader(
        session,
        session.display_name || session.name || session.phone || 'Cliente sin nombre',
        session.phone || ''
    )
    updateComposerState(session)
}

function renderHeader(session, displayName, phone) {
    renderHeaderView({
        session,
        displayName,
        phone,
        onBack: showMobileConversationList,
        onTakeChat: takeCurrentChat,
        onTransferToSupport: () => transferCurrentChat('soporte_tecnico'),
        onReturnToAssistant: () => returnCurrentChat('assistant'),
        onReturnToGestor: () => returnCurrentChat('gestor'),
        onAssignManager: openAssignManagerModal,
        onCloseSupport: closeSupportToOriginalGestor,
        realtimeStatus,
    })
}

function updateComposerState(session) {
    composerController.updateComposerState(session)
}

async function applyConversationOperation(operation) {
    const sessionId = Number(currentSessionId || 0)
    const previousStatus = sessionId
        ? getState().conversations.byId[sessionId]?.status_operativo ?? null
        : null

    const result = await conversationOperations.applyConversationOperation(operation)
    if (!sessionId) return result

    const nextSession = getState().conversations.byId[sessionId] || null
    const nextStatus = nextSession?.status_operativo ?? null

    if (!nextSession || previousStatus !== nextStatus) {
        forceRender = true
    }

    return result
}

function takeCurrentChat() {
    return conversationOperations.applyConversationOperation(
        (sessionId) => takeConversation(sessionId),
        {
            optimisticPatch: () => ({
                status_operativo: "assigned_gestor",
                assigned_user_id: getCurrentUser()?.username || null,
                assigned_role: "gestor",
            }),
        }
    )
}

function transferCurrentChat(destination) {
    return conversationOperations.applyConversationOperation(
        (sessionId) => transferConversation(sessionId, destination),
        {
            optimisticPatch: () => ({
                status_operativo: destination === "soporte_tecnico" ? "assigned_soporte" : destination,
                assigned_role: destination === "soporte_tecnico" ? "soporte" : destination,
                transfer_pending: false,
            }),
        }
    )
}

function returnCurrentChat(destination) {
    return conversationOperations.applyConversationOperation(
        (sessionId) => returnConversation(sessionId, destination),
        {
            optimisticPatch: () => ({
                status_operativo: destination === "gestor" ? "assigned_gestor" : "assistant_active",
                assigned_role: destination,
                transfer_pending: false,
            }),
        }
    )
}

function closeSupportToOriginalGestor() {
    return conversationOperations.applyConversationOperation(
        (sessionId) => closeTechnicalIncident(sessionId, {
            return_action: 'return_to_original_gestor',
            fallback_destination: 'jefe_operativo',
        }),
        {
            optimisticPatch: () => ({
                status_operativo: "assigned_gestor",
                assigned_role: "gestor",
                transfer_pending: false,
            }),
        }
    )
}

function closeSupportToAssistant() {
    return conversationOperations.applyConversationOperation(
        (sessionId) => closeTechnicalIncident(sessionId, {
            return_action: 'assistant_active',
            fallback_destination: 'jefe_operativo',
        }),
        {
            optimisticPatch: () => ({
                status_operativo: "assistant_active",
                assigned_role: "assistant",
                transfer_pending: false,
            }),
        }
    )
}

function closeSupportToQueue() {
    return conversationOperations.applyConversationOperation(
        (sessionId) => closeTechnicalIncident(sessionId, {
            return_action: 'cola_general',
            fallback_destination: 'jefe_operativo',
        }),
        {
            optimisticPatch: () => ({
                status_operativo: "unassigned",
                assigned_user_id: null,
                assigned_role: null,
                transfer_pending: false,
            }),
        }
    )
}

window.takeCurrentChat = takeCurrentChat
window.transferCurrentChat = transferCurrentChat
window.returnCurrentChat = returnCurrentChat
window.closeSupportToOriginalGestor = closeSupportToOriginalGestor
window.closeSupportToAssistant = closeSupportToAssistant
window.closeSupportToQueue = closeSupportToQueue

function setupDragAndDrop() {
    const container = document.getElementById("messagesContainer")

    if (!container) return

    // 🔵 CUANDO ARRASTRAS ENCIMA
    container.addEventListener("dragover", (e) => {
        e.preventDefault()
        container.classList.add("bg-green-100/30", "dark:bg-green-900/20")
    })

    // 🔴 CUANDO SALES
    container.addEventListener("dragleave", () => {
        container.classList.remove("bg-green-100/30", "dark:bg-green-900/20")
    })

    // 📥 CUANDO SUELTAS
    container.addEventListener("drop", (e) => {
        e.preventDefault()

        container.classList.remove("bg-green-100/30", "dark:bg-green-900/20")

        const files = e.dataTransfer.files
        if (!files || files.length === 0) return

        const droppedFiles = Array.from(files)

        // Solo imágenes y docs básicos
        const validFiles = droppedFiles.filter(file =>
            file.type.startsWith("image") || file.type.includes("pdf")
        )

        if (validFiles.length === 0) {
            alert("Tipo de archivo no soportado")
            return
        }

        setPreviewFiles([...selectedFiles, ...validFiles], 0)
        renderMultiPreview()
    })
}

window.removeFileAtIndex = function (index, event) {
    event?.preventDefault()
    event?.stopPropagation()

    if (!removePreviewFile(index)) return

    if (selectedFiles.length === 0) {
        hidePreviewContainer()
        return
    }

    renderMultiPreview()
}

// =========================
// IMAGE VIEWER (WhatsApp-style)
// =========================
window.openImageViewer = function (src) {
    firstViewerOpen = true

    const viewer = document.getElementById("imageViewer")
    const img = document.getElementById("imageViewerImg")

    if (!viewer || !img) return

    currentImageIndex = imageList.indexOf(src)
    if (currentImageIndex === -1) currentImageIndex = 0
    dispatch({
        type: "chat/viewer/open",
        payload: {
            images: imageList,
            selectedIndex: currentImageIndex
        }
    })

    showImage(currentImageIndex)

    viewer.classList.remove("hidden")
}

window.closeImageViewer = function () {
    const viewer = document.getElementById("imageViewer")
    const img = document.getElementById("imageViewerImg")

    if (!viewer || !img) return

    img.src = ""
    viewer.classList.add("hidden")
    dispatch({ type: "chat/viewer/close" })
}

// cerrar al hacer click fuera de la imagen
document.addEventListener("click", (e) => {
    const viewer = document.getElementById("imageViewer")

    if (!viewer || viewer.classList.contains("hidden")) return

    // SOLO cerrar si das click directamente en el fondo
    if (e.target === viewer) {
        closeImageViewer()
    }
})

// renderiza las miniaturas en el visor
window.showImage = function (index) {
    if (index < 0 || index >= imageList.length) return
    dispatch({
        type: "chat/viewer/show",
        payload: { index }
    })

    const img = document.getElementById("imageViewerImg")
    const newSrc = imageList[index]

    const temp = new Image()
    temp.src = newSrc

    temp.onload = () => {
        img.style.opacity = "0"

        requestAnimationFrame(() => {
            currentImageIndex = index
            img.src = newSrc

            renderThumbs()

            requestAnimationFrame(() => {
                img.style.opacity = "1"
            })
        })
    }
}

window.prevImage = () => {
    if (currentImageIndex > 0) {
        showImage(currentImageIndex - 1)
    }
}

window.nextImage = () => {
    if (currentImageIndex < imageList.length - 1) {
        showImage(currentImageIndex + 1)
    }
}

// renderiza las miniaturas en el visor y resalta la actual
let thumbsRendered = false

window.renderThumbs = function () {
    const box = document.getElementById("imageThumbs")
    if (!box) return

    if (!thumbsRendered || box.children.length !== imageList.length) {
        box.innerHTML = imageList.map((url, i) => `
            <img 
                src="${url}"
                data-index="${i}"
                class="w-14 h-14 object-cover rounded cursor-pointer shrink-0"
            />
        `).join("")

        // eventos
        box.querySelectorAll("img").forEach(img => {
            img.onclick = () => {
                const index = Number(img.dataset.index)
                showImage(index)
            }
        })

        thumbsRendered = true
    }

    box.querySelectorAll("img").forEach((img, i) => {
        if (i === currentImageIndex) {
            img.classList.add("ring-2", "ring-green-500")
            img.classList.remove("opacity-60")
        } else {
            img.classList.remove("ring-2", "ring-green-500")
            img.classList.add("opacity-60")
        }
    })

    // SCROLL
    requestAnimationFrame(() => {
        const activeThumb = box.children[currentImageIndex]
        if (!activeThumb) return

        const boxWidth = box.clientWidth
        const thumbLeft = activeThumb.offsetLeft
        const thumbWidth = activeThumb.clientWidth

        const targetScroll =
            thumbLeft - (boxWidth / 2) + (thumbWidth / 2)

        const behavior = firstViewerOpen ? "auto" : "smooth"

        box.scrollTo({
            left: targetScroll,
            behavior
        })

        firstViewerOpen = false
    })
}

const style = document.createElement("style")
style.innerHTML = `
    #imageThumbs::-webkit-scrollbar {
        display: none;
    }
`
document.head.appendChild(style)

window.removeCurrentFile = function (event) {
    event?.preventDefault()
    event?.stopPropagation()

    syncPreviewFromStore()

    if (selectedFiles.length === 0) return

    if (!removePreviewFile(selectedPreviewIndex)) return

    if (selectedFiles.length === 0) {
        hidePreviewContainer()
        return
    }

    renderMultiPreview()
}
