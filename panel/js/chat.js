import { getMessages, sendMessage, apiRequest } from "../js/api.js"
import { EMOJIS } from "./emojis.js"
import { getWebSocket } from "./websocket.js"
import { dispatch } from "./store.js"
import { subscribeStore, getState } from "./store.js"
import { getConversations } from "../js/api.js"
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

const renderedMessageIdsBySession = new Map()

// =========================
// CONFIG
// =========================
const sidebarNodes = new Map()
const LOAD_COOLDOWN = 500
const MAX_RENDERED_MESSAGES = 300
const PAGE_SIZE = 30

const API_BASE = window.location.origin.includes("5500")
    ? "http://localhost:8000"
    : ""

let paginationState = {
    offset: 0,
    loading: false,
    hasMore: true
}

let searchTerm = ""
let filterMode = "all" // "all" | "unread"

//Para imagenes 
let selectedFiles = []
let selectedPreviewIndex = 0

// =========================
// INIT
// =========================
export async function initConversationsPage() {
    window.send = send
    window.handleTyping = handleTyping
    window.handleKeyDown = handleKeyDown
    window.autoResize = autoResize
    
    // reset visual de la vista al volver a entrar al módulo
    lastLoadedSessionId = null
    isLoadingChat = false

    if (unsubscribeChatStore) unsubscribeChatStore()

    let lastMessagesRef = null
    let lastConversationSignature = ""

    unsubscribeChatStore = subscribeStore((state) => {
        const currentMessages = state.messages.bySessionId[currentSessionId] || []

        if (currentMessages !== lastMessagesRef) {
            renderMessagesIncremental(state)
            lastMessagesRef = currentMessages
        }

        const signature = state.conversations.order
            .map((id) => {
                const c = state.conversations.byId[id]
                return c
                    ? `${c.id}:${c.last_message_at ?? ""}:${c.unread_count ?? 0}`
                    : id
            })
            .join("|")

        if (signature !== lastConversationSignature) {
            renderSidebarFromState(state)
            lastConversationSignature = signature
        }
    })

    const sessions = await getConversations()

    dispatch({
        type: "conversations/loaded",
        payload: sessions
    })

    renderSidebarFromState(getState())

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

        await loadChat(
            sessionIdNum,
            selected.phone || sessionFromStore?.phone || "",
            selected.name || sessionFromStore?.name || null
        )
    } else {
        const firstId = state.conversations.order[0]
        const session = state.conversations.byId[firstId]

        if (session) {
            await loadChat(session.id, session.phone)
        }
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
                    selectedFiles = [...selectedFiles, ...files]
                    selectedPreviewIndex = 0
                    renderMultiPreview()
                }

                fileInput.value = ""
            })

            fileInput.dataset.bound = "true"
        }
    })
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

    if (normalized.media_url && normalized.media_url.startsWith("/media")) {
        normalized.media_url = `${API_BASE}${normalized.media_url}`
    }

    if (!normalized.created_at) {
        normalized.created_at = new Date().toISOString()
    }

    return normalized
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

    return text
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

    // 🔍 FILTRO POR BÚSQUEDA
    if (searchTerm) {
        sessions = sessions.filter(s => {
            const phone = s.phone?.toLowerCase() || ""
            const name = s.name?.toLowerCase() || ""

            return phone.includes(searchTerm) || name.includes(searchTerm)
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
            return
        }

        await loadChat(s.id, s.phone, s.name)
    }

    return div
}

function updateSidebarNode(node, s) {
    const isActive = s.id === currentSessionId

    node.className = `
        px-4 py-3 cursor-pointer border-b flex justify-between items-center
        border-gray-200 dark:border-slate-700
        hover:bg-gray-100 dark:hover:bg-slate-700
        transition
        ${isActive ? "bg-blue-100 dark:bg-slate-700" : ""}
    `

    node.innerHTML = `
        <div class="min-w-0">
            <div class="font-semibold truncate">${s.name || s.phone}</div>
            <div class="text-xs text-gray-500">${s.last_message_at ?? ""}</div>
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
    let bubbleClass = "inline-block max-w-[70%] min-w-[80px] px-3 py-2 rounded-lg text-sm shadow-sm break-words"

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
    const mediaUrl = msg.media_url

    if (mediaUrl) {
        if (msg.type === "image") {
            bodyContent = `
                <div class="flex flex-col gap-1">
                    <img
                        src="${mediaUrl}"
                        class="max-w-[380px] max-h-[420px] object-contain rounded-lg cursor-pointer hover:opacity-90"
                        onclick="window.open('${mediaUrl}', '_blank')"
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
                <div class="flex items-center gap-3 p-2 rounded-lg bg-gray-100 dark:bg-slate-600">

                    <div class="w-10 h-10 flex items-center justify-center bg-red-500 text-white rounded-md text-xs font-bold">
                        PDF
                    </div>

                    <div class="flex flex-col min-w-0">
                        <span class="text-sm font-medium truncate">
                            ${msg.file_name || "Archivo"}
                        </span>
                        <span class="text-xs text-gray-500 dark:text-gray-300">
                            Documento
                        </span>
                    </div>

                </div>

                ${
                    cleanContent
                        ? `<span class="text-sm mt-1 block">${formatWhatsAppText(cleanContent)}</span>`
                        : ""
                }
            `
        }
    } else {
        const content = formatButtonMessage(msg.content)
        const finalText = formatWhatsAppText(content)
        bodyContent = `<div>${finalText}</div>`
    }

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

    for (let i = 0; i < messages.length; i++) {
        const msg = normalizeMessage(messages[i])
        if (!msg.id) continue
        const id = `msg-${msg.id}`

        if (renderedSet.has(id)) continue

        if (document.querySelector(`[data-message-id="${id}"]`)) {
            renderedSet.add(id)
            continue
        }

        const shouldShowNewSeparator =
            !wasAtBottom &&
            msg.direction === "in" &&
            lastLoadedSessionId === currentSessionId &&
            renderedSet.size > 0

        const currentDate = new Date(msg.created_at).toDateString()
        const lastDate = fragment.querySelectorAll("[data-message-date]").length
            ? fragment.querySelectorAll("[data-message-date]")[fragment.querySelectorAll("[data-message-date]").length - 1].dataset.messageDate
            : getLastRenderedDate(list)

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

        if (wasAtBottom) {
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

    if (isLoadingChat) return

    // solo evita recargar si la vista actual YA tiene renderizado ese chat
    const alreadyRendered =
        currentSessionId === Number(sessionId) &&
        lastLoadedSessionId === Number(sessionId) &&
        header &&
        header.textContent?.trim() &&
        list &&
        list.childElementCount > 0

    if (alreadyRendered) return
    const previousSessionId = currentSessionId
    const isSameChat = previousSessionId === sessionId

    currentSessionId = Number(sessionId)
    setSelectedSession({
        sessionId: Number(sessionId),
        phone,
        name
    })
    
    renderSidebarFromState(getState())
    isLoadingChat = true
    const state = getState()
    const sessionInfo = state.conversations.byId[Number(sessionId)]
    const displayName = sessionInfo?.name || `+${phone}`


    try {
        if (header) {
            header.innerHTML = `
                <div class="flex items-center justify-between w-full">
                    
                    <div class="flex flex-col">
                        <span class="font-semibold text-sm">
                            ${name || "+" + phone}
                        </span>
                        <span class="text-xs text-gray-400">
                            ${name ? "+" + phone : "En conversación"}
                        </span>
                    </div>

                </div>
            `
        }

        await apiRequest(`/panel/conversations/${sessionId}/read`, {
            method: "POST"
        })

        paginationState = {
            offset: 0,
            loading: false,
            hasMore: true
        }

        if (!isSameChat && list) {
            list.innerHTML = ""
            clearRenderedSession(sessionId)
            removeNewMessagesSeparator()
        }

        const messages = await getMessages(sessionId, PAGE_SIZE, 0)

        let messagesList = []

        if (Array.isArray(messages)) messagesList = messages
        else if (Array.isArray(messages.messages)) messagesList = messages.messages
        else if (Array.isArray(messages.data)) messagesList = messages.data
        else if (Array.isArray(messages.items)) messagesList = messages.items

        if (!isSameChat) {
            dispatch({
                type: "messages/loaded",
                payload: {
                    sessionId,
                    items: messagesList
                }
            })
        }
        paginationState.offset = messagesList.length
        lastLoadedSessionId = sessionId

    } finally {
        isLoadingChat = false
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
    const input = document.getElementById("messageInput")
    if (!input) return

    const content = input.value.trim()

    if (!content && selectedFiles.length === 0) return
    if (!currentSessionId) return

    const textToSend = content

    input.value = ""
    input.focus()
    removeTyping()

    try {
        // 📦 SI HAY ARCHIVOS
        if (selectedFiles.length > 0) {

            for (let i = 0; i < selectedFiles.length; i++) {
                const file = selectedFiles[i]

                const formData = new FormData()
                formData.append("file", file)

                const res = await fetch(`${API_BASE}/api/panel/upload`, {
                    method: "POST",
                    body: formData
                })

                if (!res.ok) {
                    throw new Error("Error subiendo archivo")
                }

                const data = await res.json()

                await apiRequest(`/panel/messages/file`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        session_id: currentSessionId,
                        media_url: data.url,
                        file_name: data.filename,
                        type: file.type.startsWith("image") ? "image" : "document",
                        content: i === 0 ? (textToSend || null) : null
                    })
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
    }
}

async function sendFile(file) {
    if (!file || !currentSessionId) return

    if (file.size > 10 * 1024 * 1024) {
        alert("Archivo demasiado grande")
        return
    }

    const formData = new FormData()
    formData.append("file", file)

    try {
        const res = await fetch(`${API_BASE}/api/panel/upload`, {
            method: "POST",
            body: formData
        })

        if (!res.ok) {
            throw new Error(`Upload error: ${res.status}`)
        }

        const data = await res.json()

        //  NO render optimista para evitar duplicados con WS
        await apiRequest(`/panel/messages/file`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                session_id: currentSessionId,
                media_url: data.url,
                file_name: data.filename,
                type: file.type.startsWith("image") ? "image" : "document"
            })
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
    div.className = "w-fit max-w-[42rem] text-xs text-gray-500 italic self-start bg-white px-3 py-2 rounded-lg shadow-sm"
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

selectedFiles = selectedFiles.filter(Boolean)

function renderMultiPreview() {
    const container = document.getElementById("filePreview")
    if (!container || selectedFiles.length === 0) return

    const mainFile = selectedFiles[selectedPreviewIndex]
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
                            📄 ${mainFile.name}
                        </div>
                    `
                }

                <button
                    onclick="removeAllFiles()"
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
                    onclick="removeFileAtIndex(${i})"
                    class="absolute top-1 right-1 bg-black/70 text-white text-xs w-5 h-5 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition"
                >
                    ✕
                </button>
            </div>
        `
    }).join("")
}


function updatePreviewUI() {
    const container = document.getElementById("mainPreviewImage")
    if (!container) return

    const file = selectedFiles[selectedPreviewIndex]
    if (!file) return

    const isImage = file.type.startsWith("image")
    const isPDF = file.type === "application/pdf"

    const newUrl = URL.createObjectURL(file)

    if (isImage) {
        container.outerHTML = `
            <img 
                id="mainPreviewImage"
                src="${newUrl}" 
                class="w-full max-h-[420px] object-contain rounded-xl"
            />
        `
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
    selectedPreviewIndex = index
    updatePreviewUI()
}

window.removeAllFiles = function () {
    selectedFiles = []
    selectedPreviewIndex = 0

    const container = document.getElementById("filePreview")
    if (container) {
        container.classList.add("hidden")
        container.innerHTML = ""
    }
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

        selectedFiles = [...selectedFiles, ...validFiles]
        selectedPreviewIndex = 0
        renderMultiPreview()
    })
}

window.removeFileAtIndex = function (index) {
    selectedFiles.splice(index, 1)

    if (selectedPreviewIndex >= selectedFiles.length) {
        selectedPreviewIndex = selectedFiles.length - 1
    }

    if (selectedFiles.length === 0) {
        removeAllFiles()
        return
    }

    renderMultiPreview()
}