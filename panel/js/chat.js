import {
    getConversations,
    getMessages,
    markConversationRead,
    sendFileMessage,
    sendMessage,
    uploadPanelFile,
    apiRequest,
    resumeBotControlApi
} from "./api.js"
import { resolveMediaUrl } from "./config.js"
import { EMOJIS } from "./emojis.js"
import { getWebSocket } from "./websocket.js"
import { dispatch } from "./store.js"
import { subscribeStore, getState } from "./store.js"
import { getSelectedSession, setSelectedSession } from "./app.js"



// =========================
// ESTADO GLOBAL
// =========================
let currentSessionId = null
let lastTyping = 0
let unsubscribeChatStore = null
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
let realtimeRecoveryBound = false
let realtimeRecoveryRunning = false

const renderedMessageIdsBySession = new Map()

// =========================
// CONFIG
// =========================
const sidebarNodes = new Map()
const LOAD_COOLDOWN = 500
const MAX_RENDERED_MESSAGES = 300
const PAGE_SIZE = 30

let paginationState = {
    offset: 0,
    loading: false,
    hasMore: true
}

let searchTerm = ""
let filterMode = "all" // "all" | "unread"
let mobileResizeBound = false

//Para imagenes 
let selectedFiles = []
let selectedPreviewIndex = 0

let imageList = []
let imageSet = new Set()
let currentImageIndex = 0

function extractMessagesList(response) {
    if (Array.isArray(response)) return response
    if (Array.isArray(response?.messages)) return response.messages
    if (Array.isArray(response?.data)) return response.data
    if (Array.isArray(response?.items)) return response.items
    return []
}

function setupRealtimeRecovery() {
    if (realtimeRecoveryBound) return

    window.addEventListener("panel:ws-reconnected", async () => {
        if (!document.getElementById("conversationList")) return
        if (realtimeRecoveryRunning) return

        realtimeRecoveryRunning = true
        try {
            const sessions = await getConversations()
            dispatch({
                type: "conversations/loaded",
                payload: sessions
            })

            if (currentSessionId) {
                const messages = await getMessages(currentSessionId, PAGE_SIZE, 0)
                dispatch({
                    type: "messages/loaded",
                    payload: {
                        sessionId: currentSessionId,
                        items: extractMessagesList(messages)
                    }
                })
            }
        } catch (error) {
            console.warn("No se pudo resincronizar conversaciones:", error)
        } finally {
            realtimeRecoveryRunning = false
        }
    })

    realtimeRecoveryBound = true
}

function trackImageUrl(url) {
    if (!url || imageSet.has(url)) return

    imageSet.add(url)
    imageList.push(url)
}

function normalizePreviewIndex(index, length) {
    if (!length) return 0

    const numericIndex = Number(index)
    if (!Number.isFinite(numericIndex)) return 0

    return Math.max(0, Math.min(length - 1, Math.trunc(numericIndex)))
}

function isValidPreviewIndex(index, length = selectedFiles.length) {
    const numericIndex = Number(index)
    return Number.isFinite(numericIndex) && numericIndex >= 0 && Math.trunc(numericIndex) < length
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

    if (!isValidPreviewIndex(index)) return false

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

// =========================
// INIT
// =========================
export async function initConversationsPage() {
    window.send = send
    window.resumeBotControl = async function (sessionId) {
        const confirmed = await new Promise((resolve) => {
            const overlay = document.createElement("div")
            overlay.className = "fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm transition-opacity"

            const modal = document.createElement("div")
            modal.className = "bg-white dark:bg-slate-800 rounded-xl shadow-2xl p-6 w-full max-w-sm mx-4 transform scale-95 transition-transform"

            modal.innerHTML = `
                <div class="flex items-center gap-3 mb-4 text-blue-600 dark:text-blue-500">
                    <i data-lucide="bot" class="w-6 h-6"></i>
                    <h3 class="text-lg font-bold text-slate-900 dark:text-white">Panel Mexicomp</h3>
                </div>
                <p class="text-sm text-slate-600 dark:text-slate-300 mb-6">
                    ¿Deseas terminar la atencion manual y devolver el control automatico al Chatbot?
                </p>
                <div class="flex justify-end gap-3">
                    <button id="cancelConfirmBtn" class="px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg transition-colors">
                        Cancelar
                    </button>
                    <button id="okConfirmBtn" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors flex items-center gap-2 shadow-sm">
                        <span>Aceptar</span>
                    </button>
                </div>
            `

            overlay.appendChild(modal)
            document.body.appendChild(overlay)

            if (window.lucide) lucide.createIcons({ root: modal })

            // Animation
            requestAnimationFrame(() => {
                modal.classList.remove("scale-95")
                modal.classList.add("scale-100")
            })

            const cleanup = (result) => {
                overlay.classList.add("opacity-0")
                setTimeout(() => {
                    if (document.body.contains(overlay)) document.body.removeChild(overlay)
                    resolve(result)
                }, 200)
            }

            modal.querySelector("#cancelConfirmBtn").addEventListener("click", () => cleanup(false))
            modal.querySelector("#okConfirmBtn").addEventListener("click", () => cleanup(true))
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) cleanup(false)
            })
        })

        if (!confirmed) return;

        try {
            await resumeBotControlApi(sessionId)
        } catch (err) {
            const errorMessage = err.message || "Error al devolver el control al bot"
            const alertOverlay = document.createElement("div")
            alertOverlay.className = "fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm transition-opacity"

            const alertModal = document.createElement("div")
            alertModal.className = "bg-white dark:bg-slate-800 rounded-xl shadow-2xl p-6 w-full max-w-sm mx-4 transform scale-95 transition-transform"

            alertModal.innerHTML = `
                <div class="flex items-center gap-3 mb-4 text-blue-600 dark:text-blue-500">
                    <i data-lucide="info" class="w-6 h-6"></i>
                    <h3 class="text-lg font-bold text-slate-900 dark:text-white">Aviso</h3>
                </div>
                <p class="text-sm text-slate-600 dark:text-slate-300 mb-6">
                    ${errorMessage}
                </p>
                <div class="flex justify-end">
                    <button id="okAlertBtn" class="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors flex items-center shadow-sm">
                        <span>Aceptar</span>
                    </button>
                </div>
            `

            alertOverlay.appendChild(alertModal)
            document.body.appendChild(alertOverlay)

            if (window.lucide) lucide.createIcons({ root: alertModal })

            requestAnimationFrame(() => {
                alertModal.classList.remove("scale-95")
                alertModal.classList.add("scale-100")
            })

            const cleanupAlert = () => {
                alertOverlay.classList.add("opacity-0")
                setTimeout(() => {
                    if (document.body.contains(alertOverlay)) document.body.removeChild(alertOverlay)
                }, 200)
            }

            alertModal.querySelector("#okAlertBtn").addEventListener("click", cleanupAlert)
            alertOverlay.addEventListener("click", (e) => {
                if (e.target === alertOverlay) cleanupAlert()
            })
        }
    }
    window.handleTyping = handleTyping
    window.handleKeyDown = handleKeyDown
    window.autoResize = autoResize
    
    startWindowValidationTimer()
    setupRealtimeRecovery()

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
            console.timeEnd("renderSidebar")
            lastConversationSignature = state.conversations._version

            // 🛡️ ACTUALIZAR ESTADO DE INPUT SI LA SESION ACTUAL CAMBIA
            if (currentSessionId) {
                const currentSession = state.conversations.byId[currentSessionId]
                if (currentSession) {
                    updateChatInputState(currentSession)
                    updateChatHeaderControlState(currentSession)
                }
            }
        }

        if (state.chat._previewVersion !== lastPreviewVersion) {
            syncPreviewFromStore()
            lastPreviewVersion = state.chat._previewVersion
        }
    })

    const sessions = await getConversations()

    dispatch({
        type: "conversations/loaded",
        payload: sessions
    })

    const savedSearch = localStorage.getItem("chatSearch")
    if (savedSearch) {
        searchTerm = savedSearch

        const input = document.getElementById("searchInput")
        if (input) input.value = savedSearch
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
            } catch { }
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

    if (normalized.extra_json && typeof normalized.extra_json === "string") {
        try {
            normalized.extra_json = JSON.parse(normalized.extra_json)
        } catch {
            normalized.extra_json = null
        }
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
    if (!dateString) return ""

    const raw = String(dateString)
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)

    if (!hasTimezone) {
        const match = raw.match(/(?:T|\s)(\d{2}):(\d{2})/)
        return match ? `${match[1]}:${match[2]}` : ""
    }

    const date = new Date(raw.replace(" ", "T"))

    return date.toLocaleTimeString("es-MX", {
        timeZone: "America/Mexico_City",
        hour: "2-digit",
        minute: "2-digit"
    })
}

function parsePanelDate(dateString) {
    if (!dateString) return null

    const raw = String(dateString)
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)

    if (hasTimezone) {
        const date = new Date(raw.replace(" ", "T"))
        if (Number.isNaN(date.getTime())) return null

        return new Date(date.toLocaleString("en-US", {
            timeZone: "America/Mexico_City"
        }))
    }

    const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2})(?::(\d{2}))?)?/)
    if (!match) return null

    return new Date(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]),
        Number(match[4] || 0),
        Number(match[5] || 0),
        Number(match[6] || 0),
    )
}

function startOfDay(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function formatSidebarTimestamp(dateString) {
    const date = parsePanelDate(dateString)
    if (!date) return formatTime(dateString)

    const mexicoNow = new Date(new Date().toLocaleString("en-US", {
        timeZone: "America/Mexico_City"
    }))
    const diffDays = Math.floor((startOfDay(mexicoNow) - startOfDay(date)) / 86400000)
    const time = date.toLocaleTimeString("es-MX", {
        hour: "2-digit",
        minute: "2-digit"
    })

    if (diffDays === 0) return `Hoy ${time}`
    if (diffDays === 1) return `Ayer ${time}`
    if (diffDays > 1 && diffDays < 7) {
        const weekday = date.toLocaleDateString("es-MX", { weekday: "long" })
        return `${weekday.charAt(0).toUpperCase()}${weekday.slice(1)} ${time}`
    }

    const dateText = date.toLocaleDateString("es-MX", {
        day: "2-digit",
        month: "short",
        year: date.getFullYear() === mexicoNow.getFullYear() ? undefined : "numeric"
    }).replace(".", "")

    return `${dateText} ${time}`
}

function formatDateSeparator(dateString) {
    if (!dateString) return ""

    const today = new Date()
    const mexicoNow = new Date(today.toLocaleString("en-US", {
        timeZone: "America/Mexico_City"
    }))

    const raw = String(dateString)
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
    let mexicoDate

    if (hasTimezone) {
        const date = new Date(raw.replace(" ", "T"))
        mexicoDate = new Date(date.toLocaleString("en-US", {
            timeZone: "America/Mexico_City"
        }))
    } else {
        const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
        if (!match) return ""
        mexicoDate = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    }

    const isToday = mexicoDate.toDateString() === mexicoNow.toDateString()

    const yesterday = new Date(mexicoNow)
    yesterday.setDate(mexicoNow.getDate() - 1)

    const isYesterday = mexicoDate.toDateString() === yesterday.toDateString()

    if (isToday) return "Hoy"
    if (isYesterday) return "Ayer"

    return mexicoDate.toLocaleDateString("es-MX", {
        weekday: "long",
        day: "numeric",
        month: "long"
    })
}

function accountList(value) {
    if (!value) return []
    if (Array.isArray(value)) return value.flatMap(accountList)

    return String(value)
        .split(",")
        .map(item => item.trim())
        .filter(Boolean)
        .filter((item, index, items) => items.indexOf(item) === index)
}

function renderSidebarAccounts(value) {
    const accounts = accountList(value)
    if (!accounts.length) return ""

    const label = accounts.length === 1 ? "Cuenta" : "Cuentas"
    const chips = accounts
        .map(account => `
            <span class="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-600 dark:bg-slate-700 dark:text-slate-200">
                ${escapeHtml(account)}
            </span>
        `)
        .join("")

    return `
        <div class="mt-1 flex min-w-0 flex-wrap items-center gap-1 text-xs text-gray-400">
            <span class="shrink-0">${label}:</span>
            ${chips}
        </div>
    `
}

function formatWhatsAppText(text) {
    if (!text) return ""

    let formatted = escapeHtml(text)
        .replace(/\n/g, "<br>")
        .replace(/\*(.*?)\*/g, "<b>$1</b>")
        .replace(/_(.*?)_/g, "<i>$1</i>")
        .replace(/~(.*?)~/g, "<s>$1</s>")
        .replace(/`(.*?)`/g, "<code>$1</code>")

    // Fix visual para web del mensaje de desglose de cuenta con espaciadores \u2007
    if (formatted.includes('\u2007')) {
        formatted = formatted.split('<br>').map(line => {
            if (line.includes('te comparto el desglose de tu cuenta')) {
                return `<div class="mb-2">${line}</div>`;
            }
            if (line.includes('\u2007') && line.includes('</b>')) {
                let cleanLine = line.replace(/\u2007/g, '').trim();
                let parts = cleanLine.split('</b>');
                if (parts.length >= 2) {
                    let label = parts[0].replace('<b>', '').trim();
                    let amount = parts[1].trim();
                    return `<div class="flex justify-between gap-4 py-[2px]"><b>${label}</b><span>${amount}</span></div>`;
                }
            }
            if (line.includes('----')) {
                return `<div class="border-t border-dashed border-gray-400 dark:border-slate-500 my-2 opacity-60"></div>`;
            }
            return line;
        }).join('<br>');

        // Remove empty brs around our generated divs to keep spacing tight
        formatted = formatted.replace(/<br><div/g, '<div');
        formatted = formatted.replace(/<\/div><br>/g, '</div>');
    }

    return formatted
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
    COMPROBANTE_ACCESO_OK: "Entendió datos de comprobante",
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

function formatButtonMessageSafe(text) {
    if (!text) return text
    const match = text.match(/\[BOTON\]\s*(.+)/)
    if (!match) return escapeHtml(text)

    const key = match[1].trim()
    let label = BUTTON_LABELS[key] || key

    if (!BUTTON_LABELS[key]) {
        if (key.endsWith("_SI")) label = "Confirmo " + key.replace("_SI", "").toLowerCase()
        else if (key.endsWith("_NO")) label = "Rechazo " + key.replace("_NO", "").toLowerCase()
        else if (key.endsWith("_DUDA")) label = "Tiene dudas"
        else if (key.endsWith("_OK")) label = "Confirmo"
        else label = key.replaceAll("_", " ").toLowerCase()
    }

    return `
        <span class="inline-flex items-center gap-1 bg-gray-100 dark:bg-slate-500 text-gray-800 dark:text-white border border-gray-200 dark:border-slate-400 px-3 py-1 rounded-md text-xs font-medium shadow-none dark:shadow-sm">
            ${escapeHtml(label)}
        </span>
    `
}

function getMessageMetadata(msg) {
    return msg?.extra_json && typeof msg.extra_json === "object" ? msg.extra_json : {}
}

function renderHistoricalButtons(msg) {
    const metadata = getMessageMetadata(msg)
    const interactive = metadata.interactive && typeof metadata.interactive === "object"
        ? metadata.interactive
        : null
    const buttons = Array.isArray(interactive?.buttons) ? interactive.buttons : []
    if (!buttons.length) return ""

    const chips = buttons.map((button) => {
        const title = button?.title || button?.label || button?.text || "Opcion"
        return `
            <span class="inline-flex items-center rounded-md border border-blue-200 bg-white/80 px-2.5 py-1 text-xs font-medium text-blue-800 shadow-sm dark:border-slate-500 dark:bg-slate-700 dark:text-slate-100">
                ${escapeHtml(title)}
            </span>
        `
    }).join("")

    return `
        <div class="mt-2 flex flex-col gap-1">
            <span class="text-[11px] font-semibold uppercase text-gray-500 dark:text-gray-600">Opciones</span>
            <div class="flex flex-wrap gap-1.5">${chips}</div>
        </div>
    `
}

function renderCustomerSelection(text) {
    const match = String(text || "").match(/^Cliente seleccion[oó]:\s*(.+)$/i)
    if (!match) return null

    const selected = match[1].trim()
    if (!selected) return null

    return `
        <div class="flex flex-wrap items-center gap-2">
            <span>${escapeHtml("Cliente selecciono:")}</span>
            <span class="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-gray-100 px-3 py-1 text-xs font-medium text-gray-800 shadow-none dark:border-slate-400 dark:bg-slate-500 dark:text-white dark:shadow-sm">
                ${escapeHtml(selected)}
            </span>
        </div>
    `
}

function mediaLabel(type) {
    if (type === "image") return "Imagen enviada"
    if (type === "video") return "Video enviado"
    if (type === "document") return "Documento enviado"
    return "Media enviada"
}

function renderMediaFallbackCard(media) {
    if (!media || typeof media !== "object") return ""
    const type = String(media.type || "media").toLowerCase()
    const caption = media.caption || ""
    return `
        <div class="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 dark:border-slate-500 dark:bg-slate-700 dark:text-slate-100">
            <div class="font-medium">${escapeHtml(mediaLabel(type))}</div>
            ${caption ? `<div class="mt-1 text-xs text-gray-500 dark:text-gray-300">${formatWhatsAppText(caption)}</div>` : ""}
            <div class="mt-1 text-[11px] text-gray-400 dark:text-gray-300">Enviado sin preview local</div>
        </div>
    `
}

function renderMessageReactions(msg) {
    const reactions = Array.isArray(msg?.reactions) ? msg.reactions : []
    if (!reactions.length) return ""

    const content = reactions
        .map((reaction) => reaction?.reaction_emoji)
        .filter(Boolean)
        .map((emoji) => `<span>${escapeHtml(emoji)}</span>`)
        .join("")

    if (!content) return ""

    return `
        <div class="mt-1 flex ${msg.direction === "in" ? "justify-start" : "justify-end"}">
            <span class="inline-flex min-h-6 items-center gap-1 rounded-full border border-gray-200 bg-white px-2 py-0.5 text-sm shadow-sm dark:border-slate-500 dark:bg-slate-700">
                ${content}
            </span>
        </div>
    `
}

function renderStickerBubble(msg, mediaUrl) {
    const safeMediaUrl = mediaUrl ? escapeHtml(mediaUrl) : null
    if (safeMediaUrl) {
        return `
            <div class="flex flex-col gap-1">
                <img
                    src="${safeMediaUrl}"
                    class="max-w-[160px] max-h-[160px] object-contain rounded-lg"
                    loading="lazy"
                    alt="Sticker recibido"
                />
                <span class="text-sm">El cliente envio un sticker</span>
            </div>
        `
    }
    return `
        <div class="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 dark:border-slate-500 dark:bg-slate-700 dark:text-slate-100">
            <div class="font-medium">El cliente envio un sticker</div>
            <div class="mt-1 text-[11px] text-gray-400 dark:text-gray-300">Preview no disponible</div>
        </div>
    `
}

function isUserAtBottom(container) {
    const threshold = 60
    return container.scrollHeight - container.scrollTop - container.clientHeight < threshold
}

function getLastRenderedDate(list) {
    const nodes = list.querySelectorAll("[data-message-date]")
    if (!nodes.length) return null
    return nodes[nodes.length - 1].dataset.messageDate
}

function insertDateSeparator(list, dateString) {
    const separator = document.createElement("div")
    separator.className = "flex justify-center my-2"
    separator.dataset.separatorType = "date"

    separator.innerHTML = `
        <div class="text-xs px-3 py-1 rounded-full bg-gray-300 dark:bg-slate-700 text-gray-700 dark:text-gray-200">
            ${formatDateSeparator(dateString)}
        </div>
    `

    list.appendChild(separator)
}

function ensureNewMessagesSeparator(list) {
    if (document.getElementById("newMessagesSeparator")) return

    const separator = document.createElement("div")
    separator.id = "newMessagesSeparator"
    separator.className = "flex justify-center my-2"
    separator.dataset.separatorType = "new"

    separator.innerHTML = `
        <div class="text-xs px-3 py-1 rounded-full bg-blue-500 text-white">
            Nuevos mensajes
        </div>
    `

    list.appendChild(separator)
}

function removeNewMessagesSeparator() {
    const separator = document.getElementById("newMessagesSeparator")
    if (separator) separator.remove()
}

// =========================
// SIDEBAR
// =========================
function renderSidebarFromState(state) {
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

    // 🔍 FILTRO POR BÚSQUEDA
    if (searchTerm) {
        sessions = sessions.filter(s => {
            const phone = s.phone?.toLowerCase() || ""
            const name = s.name?.toLowerCase() || ""
            const cuenta = String(s.no_cuenta || "").toLowerCase()
            const folio = String(s.folio || "").toLowerCase()
            const folios = Array.isArray(s.folios)
                ? s.folios.join(" ").toLowerCase()
                : String(s.folios || "").toLowerCase()

            return (
                phone.includes(searchTerm) ||
                name.includes(searchTerm) ||
                cuenta.includes(searchTerm) ||
                folio.includes(searchTerm) ||
                folios.includes(searchTerm)
            )
        })
    }

    // 🟢 FILTRO NO LEÍDOS
    if (filterMode === "unread") {
        sessions = sessions.filter(s => (s.unread_count || 0) > 0)
    }

    const fragment = document.createDocumentFragment()
    const seen = new Set()

    sessions.forEach((s) => {
        seen.add(s.id)

        let node = sidebarNodes.get(s.id)

        if (!node) {
            node = createSidebarNode(s)
            sidebarNodes.set(s.id, node)
        }

        updateSidebarNode(node, s)
        fragment.appendChild(node)
    })

    sidebarNodes.forEach((node, id) => {
        if (!seen.has(id)) {
            sidebarNodes.delete(id)
        }
    })

    list.replaceChildren(fragment)
}

function createSidebarNode(s) {
    const div = document.createElement("div")

    div.className = `
        px-4 py-3 cursor-pointer border-b flex justify-between items-center
        border-gray-200 dark:border-slate-700
        hover:bg-gray-100 dark:hover:bg-slate-700
        transition
    `

    div.dataset.id = s.id

    div.onclick = async () => {
        if (currentSessionId === s.id && lastLoadedSessionId === s.id && !isLoadingChat) {
            showMobileChat()
            return
        }

        await loadChat(s.id, s.phone, s.name)
    }

    return div
}

function updateSidebarNode(node, s) {
    const isActive = s.id === currentSessionId
    const displayName = s.display_name || s.name || s.phone || "Cliente sin nombre"

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

            ${renderSidebarAccounts(s.no_cuenta)}

            <div class="text-xs text-gray-500">
                ${formatSidebarTimestamp(s.last_message_at)}
            </div>
        </div>

        ${s.unread_count > 0
            ? `<span class="bg-green-500 text-white text-xs px-2 py-1 rounded-full shrink-0">${s.unread_count}</span>`
            : ""
        }
    `
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
        msg.direction === "out" ? "Bot 🤖" :
            msg.direction === "agent" ? "Tú 🧑‍💻" :
                msg.direction === "in" ? "Cliente 👤" :
                    ""

    let bodyContent = ""
    const metadata = getMessageMetadata(msg)
    const mediaMeta = metadata.media && typeof metadata.media === "object" ? metadata.media : null
    const mediaUrl = msg.media_url || (mediaMeta?.url ? resolveMediaUrl(mediaMeta.url) : null)
    const messageType = msg.type || mediaMeta?.type

    if (messageType === "sticker") {
        bodyContent = renderStickerBubble(msg, mediaUrl)
    } else if (mediaUrl) {
        const safeMediaUrl = escapeHtml(mediaUrl)
        if (messageType === "image") {
            trackImageUrl(mediaUrl)
            bodyContent = `
                <div class="flex flex-col gap-1">
                    <img
                        src="${safeMediaUrl}"
                        data-open-viewer
                        data-media-url="${safeMediaUrl}"
                        class="max-w-full sm:max-w-[380px] max-h-[420px] object-contain rounded-lg cursor-pointer hover:opacity-90"
                        loading="lazy"
                    />
                    ${cleanContent
                    ? `<span class="text-sm">${formatWhatsAppText(cleanContent)}</span>`
                    : ""
                }
                </div>
            `
        } else if (messageType === "video") {
            bodyContent = `
                <div class="flex flex-col gap-1">
                    <video
                        src="${safeMediaUrl}"
                        controls
                        preload="metadata"
                        class="max-w-full sm:max-w-[420px] max-h-[420px] rounded-lg bg-black"
                    ></video>
                    ${cleanContent
                    ? `<span class="text-sm">${formatWhatsAppText(cleanContent)}</span>`
                    : `<span class="text-sm font-medium">${escapeHtml(mediaLabel("video"))}</span>`
                }
                </div>
            `
        } else {
            bodyContent = `
                <a href="${safeMediaUrl}" target="_blank" rel="noopener noreferrer"
                    class="flex items-center gap-3 p-2 rounded-lg bg-gray-100 dark:bg-slate-600
                        hover:bg-gray-200 dark:hover:bg-slate-500 transition cursor-pointer">

                    <div class="w-10 h-10 flex items-center justify-center bg-red-500 text-white rounded-md text-xs font-bold">
                        PDF
                    </div>

                    <div class="flex flex-col min-w-0">
                        <span class="text-sm font-medium truncate">
                            ${escapeHtml(msg.file_name || mediaLabel(messageType) || "Archivo")}
                        </span>
                        <span class="text-xs text-gray-500 dark:text-gray-300">
                            Abrir documento
                        </span>
                    </div>

                </a>

                ${cleanContent
                    ? `<span class="text-sm mt-1 block">${formatWhatsAppText(cleanContent)}</span>`
                    : ""
                }
            `
        }
    } else if (mediaMeta) {
        bodyContent = renderMediaFallbackCard(mediaMeta)
    } else if (typeof msg.content === "string" && msg.content.trim().startsWith("[BOTON]")) {
        bodyContent = `<div>${formatButtonMessageSafe(msg.content)}</div>`
    } else if (typeof msg.content === "string" && renderCustomerSelection(msg.content)) {
        bodyContent = renderCustomerSelection(msg.content)
    } else {
        bodyContent = `<div>${formatWhatsAppText(msg.content)}</div>`
    }

    bodyContent += renderHistoricalButtons(msg)
    bodyContent += renderMessageReactions(msg)

    const metaClass =
        msg.direction === "in"
            ? "text-gray-900 dark:text-gray-300"
            : "text-gray-800 dark:!text-black"

    bubble.innerHTML = `
        ${bodyContent}
        <div class="text-[10px] ${metaClass} mt-1 text-right">
            ${label ? `${label} · ${time}` : time}
        </div>
    `

    bubble.querySelectorAll("[data-open-viewer]").forEach((item) => {
        item.addEventListener("click", () => {
            const url = item.getAttribute("data-media-url")
            if (url) openImageViewer(url)
        })
    })

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
// VALIDACION VENTANA 24H
// =========================
function updateChatInputState(session) {
    const input = document.getElementById("messageInput")
    const warning = document.getElementById("expiredWindowWarning")
    const inputControls = document.getElementById("inputControls")

    if (!input || !warning || !inputControls) return

    if (!session || !session.last_customer_message_at) {
        warning.classList.add("hidden")
        inputControls.classList.remove("hidden")
        input.disabled = false
        return
    }

    const lastMsgDate = new Date(session.last_customer_message_at)
    const now = new Date()
    const diffMs = now - lastMsgDate
    const diffHours = diffMs / (1000 * 60 * 60)

    const isExpired = diffHours >= 24

    if (isExpired) {
        warning.classList.remove("hidden")
        inputControls.classList.add("hidden")
        input.disabled = true
        if (window.lucide) lucide.createIcons()
    } else {
        warning.classList.add("hidden")
        inputControls.classList.remove("hidden")
        input.disabled = false
    }
}

// =========================
// ACTUALIZAR ESTADO DE BOTON DE TRANSFERENCIA
// =========================
function updateChatHeaderControlState(session) {
    const container = document.getElementById("transferControlContainer")
    if (!container) return
    
    const isBotStopped = session?.status === "calls" || session?.status === "doubts" || session?.status === "inconsistent" || session?.status === "LLAMADA" || session?.status === "ACLARACION"
    
    if (isBotStopped) {
        container.classList.remove("hidden")
    } else {
        container.classList.add("hidden")
    }
}

// Monitoreo automático de la ventana cada 10 segundos
let windowValidationTimer = null
function startWindowValidationTimer() {
    if (windowValidationTimer) return
    windowValidationTimer = setInterval(() => {
        if (currentSessionId) {
            const state = getState()
            const session = state.conversations.byId[currentSessionId]
            if (session) {
                updateChatInputState(session)
                updateChatHeaderControlState(session)
            }
        }
    }, 30000) // Revisar cada 30 segundos
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

    updateChatInputState(sessionInfo)

    const requestId = ++chatLoadRequestId
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


    try {
        if (requestId !== chatLoadRequestId) return

        if (header) {
            header.innerHTML = `
                <div class="flex items-center justify-between w-full min-w-0">
                    <div class="flex items-center gap-3 min-w-0">
                        <button
                            type="button"
                            onclick="showMobileConversationList()"
                            class="md:hidden h-9 w-9 shrink-0 inline-flex items-center justify-center rounded-lg
                            hover:bg-gray-100 dark:hover:bg-slate-700 active:scale-95 transition"
                            title="Volver a conversaciones"
                            aria-label="Volver a conversaciones"
                        >
                            <i data-lucide="arrow-left" class="w-5 h-5"></i>
                        </button>
                        <div class="flex min-w-0 flex-col">
                            <span class="truncate font-semibold text-sm">
                                ${escapeHtml(displayName)}
                            </span>
                            <span class="truncate text-xs text-gray-400">
                                ${escapeHtml(safePhone ? `+${safePhone}` : "En conversacion")}
                            </span>
                        </div>
                    </div>
                    
                    <div id="transferControlContainer" class="${(sessionInfo?.status === 'calls' || sessionInfo?.status === 'doubts' || sessionInfo?.status === 'inconsistent' || sessionInfo?.status === 'LLAMADA' || sessionInfo?.status === 'ACLARACION') ? '' : 'hidden'} shrink-0 ml-2">
                        <button onclick="resumeBotControl(${numericSessionId})" class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition-colors flex items-center gap-1 shadow-sm" title="Devolver control al chatbot">
                            <span class="inline">🔄</span> <span class="hidden sm:inline">Transferir Control</span>
                        </button>
                    </div>
                </div>
            `
            if (window.lucide) lucide.createIcons()
        }

        try {
            await apiRequest(`/panel/conversations/${numericSessionId}/read`, {
                method: "POST"
            })
        } catch (err) {
            console.error("Sesión no existe, reseteando...", err)

            setSelectedSession(null)
            localStorage.removeItem("lastSession")

            const fallbackState = getState()
            const firstId = fallbackState.conversations.order[0]
            const firstSession = fallbackState.conversations.byId[firstId]

            if (firstSession && Number(firstSession.id) !== numericSessionId) {
                isLoadingChat = false
                return loadChat(
                    firstSession.id,
                    firstSession.phone,
                    firstSession.name || null
                )
            }

            currentSessionId = null
            lastLoadedSessionId = null

            if (list) list.innerHTML = ""
            if (header) {
                header.innerHTML = `
                    <div class="text-sm text-gray-400">Sin conversación seleccionada</div>
                `
            }

            return
        }
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

        const messages = await getMessages(numericSessionId, PAGE_SIZE, 0)
        if (requestId !== chatLoadRequestId) return

        const messagesList = extractMessagesList(messages)

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
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault()
        send()
    }
}

export async function send() {
    if (isSendingMessage) return

    syncPreviewFromStore()
    const input = document.getElementById("messageInput")
    if (!input) return

    const content = input.value.trim()

    if (!content && selectedFiles.length === 0) return
    if (!currentSessionId) return

    const textToSend = content

    isSendingMessage = true
    input.value = ""
    input.focus()
    removeTyping()

    try {
        // 📦 SI HAY ARCHIVOS
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
        }
        // 💬 SOLO TEXTO
        else {
            await sendMessage({
                session_id: currentSessionId,
                content: textToSend
            })
        }

    } catch (error) {
        console.error("Error enviando mensaje:", error)
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
    const input = document.getElementById("messageInput")

    if (!input) {
        console.warn("No existe #messageInput")
        return
    }

    if (input._handleKeyDownRef) {
        input.removeEventListener("keydown", input._handleKeyDownRef)
    }

    const handler = function (event) {
        if (event.key !== "Enter") return
        if (event.shiftKey) return

        event.preventDefault()
        send()
    }

    input._handleKeyDownRef = handler
    input.addEventListener("keydown", handler)
}

function setupEmojiPicker() {
    const btn = document.getElementById("emojiBtn")
    const container = document.getElementById("emojiPickerContainer")
    const input = document.getElementById("messageInput")

    if (!btn || !container || !input) return

    if (!container.dataset.init) {
        container.innerHTML = `
            <input
                id="emojiSearch"
                placeholder="Buscar emoji..."
                class="h-8 mb-3 px-2 rounded border border-gray-600 bg-white dark:bg-slate-800 border-gray-300 dark:border-slate-600 text-black dark:text-white text-sm outline-none focus:border-green-500"
            />
            <div
                id="emojiGrid"
                class="flex-1 grid grid-cols-8 gap-1 overflow-y-auto"
            ></div>
        `
        container.dataset.init = "true"
    }

    const grid = container.querySelector("#emojiGrid")
    const search = container.querySelector("#emojiSearch")

    if (!grid || !search) return

    container.classList.add("hidden")

    function render(list) {
        grid.innerHTML = ""

        list.forEach((e) => {
            const btnEmoji = document.createElement("button")
            btnEmoji.type = "button"
            btnEmoji.className = `
                flex items-center justify-center text-xl cursor-pointer
                rounded-lg
                hover:bg-gray-200 dark:hover:bg-slate-700
                transition
            `
            btnEmoji.textContent = e.emoji

            btnEmoji.onclick = () => {
                const start = input.selectionStart ?? input.value.length
                const end = input.selectionEnd ?? input.value.length

                input.value =
                    input.value.slice(0, start) +
                    e.emoji +
                    input.value.slice(end)

                const pos = start + e.emoji.length
                input.focus()
                input.selectionStart = input.selectionEnd = pos

                autoResize(input)
                container.classList.add("hidden")
            }

            grid.appendChild(btnEmoji)
        })
    }

    render(EMOJIS.slice(0, 200))

    search.oninput = () => {
        const term = search.value.toLowerCase().trim()

        const filtered = EMOJIS.filter((e) =>
            e.annotation?.toLowerCase().includes(term) ||
            e.tags?.some((t) => t.toLowerCase().includes(term))
        ).slice(0, 200)

        render(filtered)
    }

    btn.onclick = (e) => {
        e.stopPropagation()
        container.classList.toggle("hidden")

        if (!container.classList.contains("hidden")) {
            search.focus()
        }
    }

    container.onclick = (e) => {
        e.stopPropagation()
    }

    input.addEventListener("focus", () => {
        container.classList.add("hidden")
    })

    if (!container.dataset.outsideCloseBound) {
        document.addEventListener("click", () => {
            container.classList.add("hidden")
        })
        container.dataset.outsideCloseBound = "true"
    }
}

function autoResize(el) {
    if (!el) return

    el.style.height = "auto"
    const newHeight = Math.min(el.scrollHeight, 120)
    el.style.height = `${newHeight}px`
}
function setActiveFilter(activeBtn, inactiveBtn) {
    // ACTIVO
    activeBtn.classList.remove(
        "bg-gray-200", "text-gray-700",
        "dark:bg-slate-700", "dark:text-gray-300"
    )
    activeBtn.classList.add(
        "bg-green-600", "text-white",
        "dark:bg-green-500"
    )

    // INACTIVO
    inactiveBtn.classList.remove(
        "bg-green-600", "text-white",
        "dark:bg-green-500"
    )
    inactiveBtn.classList.add(
        "bg-gray-200", "text-gray-700",
        "dark:bg-slate-700", "dark:text-gray-300"
    )
}

function setupSearchAndFilters() {
    const input = document.getElementById("searchInput")
    const btnAll = document.getElementById("filterAll")
    const btnUnread = document.getElementById("filterUnread")

    if (input) {
        input.addEventListener("input", (e) => {
            searchTerm = e.target.value.toLowerCase().trim()
            localStorage.setItem("chatSearch", searchTerm)
            renderSidebarFromState(getState())
        })
    }

    if (btnAll) {
        btnAll.onclick = () => {
            filterMode = "all"
            setActiveFilter(btnAll, btnUnread)
            renderSidebarFromState(getState())
        }
    }

    if (btnUnread) {


        btnUnread.onclick = () => {
            filterMode = "unread"
            setActiveFilter(btnUnread, btnAll)
            renderSidebarFromState(getState())
        }
    }
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
                ${isImage
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
                            📄 ${mainFile.name}
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
                📄 ${file.name}
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

    if (!isValidPreviewIndex(index)) return

    const nextIndex = Math.trunc(Number(index))
    if (nextIndex === selectedPreviewIndex) return

    setPreviewIndex(nextIndex)
    updatePreviewUI()
}

window.removeAllFiles = function () {
    clearPreviewFiles()
    hidePreviewContainer()
}

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
