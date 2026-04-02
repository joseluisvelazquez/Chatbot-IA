const API_URL = window.location.origin.includes("5500")
    ? "http://localhost:8000"
    : window.location.origin
let currentSessionId = null
let socket = null
let lastTyping = 0
let typingTimeout = null
let selectedSidebarItem = null
let isLoadingChat = false
let lastLoadedSessionId = null
let messageIds = new Set()

import { getConversations } from "../js/api.js"
import { EMOJIS } from "./emojis.js" 
export function initConversationsPage() {
    
    window.send = send
    window.handleTyping = handleTyping
    window.handleKeyDown = handleKeyDown
    window.autoResize = autoResize

    if (!socket || socket.readyState !== WebSocket.OPEN) {
        initWebSocket()
    }

    loadSidebar().then((sessions) => {
        openConversationFromURL(sessions)
    })

    requestAnimationFrame(() => {
        setupInputHandler()
        setupEmojiPicker()

        // 📎 FILE INPUT
        const fileInput = document.getElementById("fileInput")

        if (fileInput) {
            fileInput.addEventListener("change", (e) => {
                const file = e.target.files[0]

                if (file) {
                    sendFile(file)
                }
                fileInput.value = ""
            })
        }
    })
}

// --------------------
// SIDEBAR
// --------------------
export async function loadSidebar() {
    const sessions = await getConversations()
    const list = document.getElementById("conversationList")

    if (!list) return

    const scroll = list.scrollTop
    list.innerHTML = ""

    sessions.forEach(s => {
        const div = document.createElement("div")
        const isActive = s.id === currentSessionId

        div.className = `
            px-4 py-3 cursor-pointer border-b flex justify-between items-center
            border-gray-200 dark:border-slate-700
            hover:bg-gray-100 dark:hover:bg-slate-700
            transition
            ${isActive ? "bg-blue-100 dark:bg-slate-700" : ""}
        `

        div.innerHTML = `
            <div class="min-w-0">
                <div class="font-semibold truncate">${s.phone}</div>
                <div class="text-xs text-gray-500">${s.last_message_at ?? ""}</div>
            </div>
            ${s.unread_count > 0
                ? `<span class="bg-green-500 text-white text-xs px-2 py-1 rounded-full shrink-0">${s.unread_count}</span>`
                : ""
            }
        `

        div.onclick = () => {
            if (currentSessionId === s.id) return
            lastLoadedSessionId = null
            loadChat(s.id, s.phone)
        }

        list.appendChild(div)
    })
    list.scrollTop = scroll

    return sessions
}

// --------------------
// HELPERS
// --------------------
const BUTTON_LABELS = {
    "MENU_VERIFICACION": "📋 Menú de verificación",
    "FOLIO_SI": "✔️ Confirmó folio",
    "NOMBRE_SI": "✔️ Confirmó nombre",
    "DOM_SI": "🏠 Confirmó domicilio",
    "FECHA_SI": "📅 Confirmó fecha",
    "PROD_SI": "📦 Confirmó producto",
    "PRODESTADOSI": "📦 Producto en buen estado",
    "PAGO_SI": "💰 Confirmó pago",
    "PAGOS_OK": "💳 Entendió pagos",
    "PLAN3_OK": "📆 Aceptó plan 3 meses",
    "PLANES_OK": "📊 Revisó planes",
    "BEN_OK": "🎉 Confirmó beneficios"
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

function formatTime(dateString) {
    const date = new Date(dateString)
    return date.toLocaleTimeString("es-MX", {
        hour: "2-digit",
        minute: "2-digit"
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

// --------------------
// BURBUJA
// --------------------
function createMessageNode(msg, timeOverride = "") {
    const wrapper = document.createElement("div");
    wrapper.className = "w-full flex opacity-0 translate-y-2 transition-all duration-300";
    requestAnimationFrame(() => {
        wrapper.classList.remove("opacity-0", "translate-y-2");
    });

    const bubble = document.createElement("div")

    // ancho estable entre conversaciones
    let bubbleClass = "inline-block max-w-[70%] min-w-[80px] px-3 py-2 rounded-lg text-sm shadow-sm break-words"
    

    if (msg.direction === "in") {
    wrapper.classList.add("justify-start")
    bubbleClass += `
        bg-gray-200 text-black
        dark:bg-slate-700 dark:text-white`
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
    // --------------------
    // 📸 IMAGENES
    // --------------------
    if (msg.media_url) {
        if (msg.type === "image") {
            bodyContent = `
                <img 
                    src="${msg.media_url}" 
                    class="max-w-[220px] rounded-lg cursor-pointer hover:opacity-90"
                    onclick="window.open('${msg.media_url}', '_blank')"
                />
            `
        } else {
            bodyContent = `
                <a 
                    href="${msg.media_url}" 
                    target="_blank"
                    class="flex items-center gap-2 text-blue-600 underline"
                >
                    📄 ${msg.file_name || "Archivo"}
                </a>
            `
        }
    }

    // --------------------
    // 📄 DOCUMENTOS
    // --------------------
    else if (msg.type === "document" && msg.media_url) {
        bodyContent = `
            <a 
                href="${msg.media_url}" 
                target="_blank"
                class="flex items-center gap-2 text-blue-600 underline"
            >
                📄 ${msg.file_name || "Documento"}
            </a>
        `
    }

    // --------------------
    // 💬 TEXTO
    // --------------------
    else {
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

// --------------------
// LOAD CHAT
// --------------------
export async function loadChat(sessionId, phone) {
    if (isLoadingChat) return

    let lastDate = null
    let firstUnreadInserted = false
    currentSessionId = sessionId
    isLoadingChat = true
    lastLoadedSessionId = sessionId

    try {
        const header = document.getElementById("chatHeader")
        if (header) {
            header.innerHTML = `
                <div class="flex flex-col">
                    <span class="font-semibold">+${phone}</span>
                    <span class="text-xs text-gray-500">En conversación</span>
                </div>
            `
        }

        const container = document.getElementById("messages")
        if (!container) return

        container.innerHTML = ""
        messageIds.clear()

        await fetch(`http://localhost:8000/api/panel/conversations/${sessionId}/read`, {
            method: "POST"
        })

        const res = await fetch(`http://localhost:8000/api/panel/messages/${sessionId}?limit=300`)
        const messages = await res.json()

        let list = Array.isArray(messages) ? messages :
            messages.messages || messages.data || messages.items || []
        
        let lastDate = null

        list.forEach(msg => {
            
            if (!msg.type && msg.media_url) {
                msg.type = "image"
            }
            
            if (msg.media_url && msg.media_url.startsWith("/media")) {
                msg.media_url = API_URL + msg.media_url
            }
            const safeDate = msg.created_at ? new Date(msg.created_at) : new Date()
            const currentDate = safeDate.toDateString()

            // --------------------
            // 📅 SEPARADOR DE FECHA
            // --------------------
            if (lastDate !== currentDate) {
                const separator = document.createElement("div")
                separator.className = "flex justify-center my-2"

                separator.innerHTML = `
                    <div class="text-xs px-3 py-1 rounded-full bg-gray-300 dark:bg-slate-700 text-gray-700 dark:text-gray-200">
                        ${msg.created_at ? formatDateSeparator(msg.created_at) : ""}
                    </div>
                `

                container.appendChild(separator)
                lastDate = currentDate
            }

            // --------------------
            // 🆕 NUEVOS MENSAJES (AL ENTRAR AL CHAT)
            // --------------------
            if (!firstUnreadInserted && msg.unread) {
                firstUnreadInserted = true

                const separator = document.createElement("div")
                separator.className = "flex justify-center my-2"

                separator.innerHTML = `
                    <div class="
                        text-xs px-3 py-1 rounded-full 
                        bg-blue-500 text-white
                    ">
                        Nuevos mensajes
                    </div>
                `

                container.appendChild(separator)
            }

            const id = msg.id ? String(msg.id) : `temp-${Math.random()}`

            if (messageIds.has(id)) return
            messageIds.add(id)

            const node = createMessageNode(msg)
            node.dataset.id = id
            node.dataset.date = currentDate

            container.appendChild(node)
        })
        lastLoadedSessionId = sessionId

        container.scrollTop = container.scrollHeight

    } finally {
        isLoadingChat = false
    }
}

// --------------------
// INPUT
// --------------------
function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault()
        send()
    }
}

// --------------------
// SEND
// --------------------
export async function send() {
    const input = document.getElementById("messageInput")
    const content = input.value.trim()

    if (!content || !currentSessionId) return

    const container = document.getElementById("messages")
    if (!container) return

    const now = formatTime(new Date())

    const node = createMessageNode(
        {
            direction: "agent",
            content
        },
        now
    )

    container.appendChild(node)

    container.scrollTo({
        top: container.scrollHeight,
        behavior: "smooth"
    })

    input.value = ""
    input.focus()
    removeTyping()

    await fetch("http://localhost:8000/api/panel/messages", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            session_id: currentSessionId,
            content: content
        })
    })
}

// --------------------
// TYPING
// --------------------
function showTyping(text = "✍️ escribiendo...") {
    removeTyping()

    const container = document.getElementById("messages")
    if (!container) return

    const div = document.createElement("div")
    div.id = "typing"
    div.className = "w-fit max-w-[42rem] text-xs text-gray-500 italic self-start bg-white px-3 py-2 rounded-lg shadow-sm"
    div.innerText = text

    container.appendChild(div)
    container.scrollTop = container.scrollHeight
}

function removeTyping() {
    const typing = document.getElementById("typing")
    if (typing) typing.remove()
}

// --------------------
// WEBSOCKET
// --------------------
export function initWebSocket() {
    socket = new WebSocket("ws://localhost:8000/api/panel/ws")

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data)

        if (data.type === "new_message" || data.type === "update_unread") {
            const prev = currentSessionId
            loadSidebar().then(() => {
                currentSessionId = prev
            })
        }

        if (data.type === "typing") {
            if (data.session_id === currentSessionId) {
                showTyping()
                clearTimeout(typingTimeout)
                typingTimeout = setTimeout(removeTyping, 2000)
            }
            return
        }

        if (data.type === "new_message") {
            const msg = data.message

            if (msg.media_url && msg.media_url.startsWith("/media")) {
                msg.media_url = API_URL + msg.media_url
            }

            console.log("📡 WS:", {
                id: msg.id,
                content: msg.content,
                session: data.session_id
            })

            if (isLoadingChat) return

            if (msg.direction === "agent") return

            if (data.session_id !== currentSessionId) {
                if (msg.direction === "in") {
                    const audio = document.getElementById("notificationSound")
                    if (audio) audio.play().catch(() => {})
                }
                return
            }

            const container = document.getElementById("messages")
            if (!container) return

            const id = msg.id ? String(msg.id) : `temp-${Math.random()}`

            if (messageIds.has(id)) return
            messageIds.add(id)

            removeTyping()

            const currentDate = new Date(msg.created_at).toDateString()
            let lastDate = null

            for (let i = container.children.length - 1; i >= 0; i--) {
                const el = container.children[i]
                if (el.dataset?.date) {
                    lastDate = el.dataset.date
                    break
                }
            }

            // separador si cambia el día
            if (lastDate !== currentDate) {

                const isNearBottom =
                    container.scrollHeight - container.scrollTop - container.clientHeight < 100

                const separator = document.createElement("div")
                    separator.id = "newMessagesSeparator"
                    separator.className = "flex justify-center my-2"

                // SI NO ESTÁ ABAJO → mostrar "Nuevos mensajes"
                const isDifferentDay = lastDate !== currentDate
                if (!isNearBottom && isDifferentDay) {
                    separator.innerHTML = `
                        <div class="
                            text-xs px-3 py-1 rounded-full 
                            bg-blue-500 text-white
                        ">
                            Nuevos mensajes
                        </div>
                    `
                } else {
                    // comportamiento normal
                    separator.innerHTML = `
                        <div class="text-xs px-3 py-1 rounded-full bg-gray-300 dark:bg-slate-700 text-gray-700 dark:text-gray-200">
                            ${msg.created_at ? formatDateSeparator(msg.created_at) : "Mensajes nuevos"}
                        </div>
                    `
                }

                container.appendChild(separator)
            }

            const node = createMessageNode(msg)
            node.dataset.id = id
            node.dataset.date = currentDate

            container.appendChild(node)

            const isNearBottom =
                container.scrollHeight - container.scrollTop - container.clientHeight < 100

            if (isNearBottom) {
                container.scrollTo({
                    top: container.scrollHeight,
                    behavior: "smooth"
                })
            }
        }
    }
    socket.onclose = () => setTimeout(initWebSocket, 2000)
}

// --------------------
// TYPING EVENT
// --------------------
function sendTypingEvent() {
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
// --------------------
// GETPHONE EVENT
// --------------------
function getSessionIdFromURL() {
    const params = new URLSearchParams(window.location.search);
    return params.get("session_id");
}
let hasOpenedFromURL = false;

function openConversationFromURL(conversations) {
    if (hasOpenedFromURL) return;

    const sessionId = getSessionIdFromURL();
    if (!sessionId) return;

    const match = conversations.find(
        c => String(c.id) === String(sessionId)
    );

    if (!match) {
        console.warn("No se encontró sesión:", sessionId);
        return;
    }

    hasOpenedFromURL = true;

    loadChat(match.id, match.phone);

    // 🔥 limpiar URL (IMPORTANTE)
    const url = new URL(window.location);
    url.searchParams.delete("session_id");
    window.history.replaceState({}, "", url);
}

// --------------------
// EMOJIS
// --------------------
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

        // Shift + Enter = salto de línea
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

    // reset
    el.style.height = "auto"

    // limitar a 120px (como tu diseño)
    const newHeight = Math.min(el.scrollHeight, 120)

    el.style.height = newHeight + "px"
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

async function sendFile(file) {
    if (!file || !currentSessionId) return

    const formData = new FormData()
    formData.append("file", file)

    const res = await fetch(`${API_URL}/api/panel/upload`, {
        method: "POST",
        body: formData
    })

    const data = await res.json()

    const container = document.getElementById("messages")

    const node = createMessageNode({
        direction: "agent",
        type: file.type.startsWith("image") ? "image" : "document",
        media_url: API_URL + data.url,
        file_name: data.filename
    })

    container.appendChild(node)
    container.scrollTop = container.scrollHeight

    await fetch(`${API_URL}/api/panel/messages/file`, {
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
}