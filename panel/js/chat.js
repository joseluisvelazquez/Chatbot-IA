let currentSessionId = null
let socket = null
let lastTyping = 0
let typingTimeout = null

import { getConversations } from "../js/api.js"

export function initConversationsPage() {
    window.send = send;
    window.handleTyping = handleTyping;
    window.handleKeyDown = handleKeyDown;

    initWebSocket();

    loadSidebar().then((sessions) => {
        openConversationFromURL(sessions);
    });
    if (window.selectedSession) {
        const { sessionId, phone } = window.selectedSession;

        loadChat(sessionId, phone);

        window.selectedSession = null;
    }
}
// --------------------
// SIDEBAR
// --------------------
export async function loadSidebar() {
    const sessions = await getConversations()
    const list = document.getElementById("conversationList")

    if (!list) return

    list.innerHTML = ""

    sessions.forEach(s => {
        const div = document.createElement("div")

        div.className = `
            px-4 py-3 cursor-pointer border-b
            border-gray-200 dark:border-slate-700
            hover:bg-gray-100 dark:hover:bg-slate-700
            transition
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

        div.onclick = () => loadChat(s.id, s.phone)

        list.appendChild(div)
    })
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
    const label = BUTTON_LABELS[key] || key

    return `
        <span class="inline-block bg-gray-200 px-2 py-1 rounded text-xs">
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
        bubbleClass += " bg-white text-black"
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

    const content = formatButtonMessage(msg.content)
    const finalText = formatWhatsAppText(content)

    bubble.innerHTML = `
        <div>${finalText}</div>
        <div class="text-[10px] text-gray-500 mt-1 text-right">
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
    const isSameChat = currentSessionId === sessionId
    currentSessionId = sessionId

    const header = document.getElementById("chatHeader")

    if (header) {
        header.innerHTML = `
            <div class="flex flex-col">
                <span class="font-semibold">+${phone}</span>
                <span class="text-xs text-gray-500">En conversación</span>
            </div>
        `
    }

    await fetch(`http://localhost:8000/api/panel/conversations/${sessionId}/read`, {
        method: "POST"
    })

    const res = await fetch(`http://localhost:8000/api/panel/messages/${sessionId}`)
    const messages = await res.json()

    const container = document.getElementById("messages")
    if (!container) return

    if (!isSameChat) {
        container.innerHTML = ""
    }

    let list = []

    if (Array.isArray(messages)) list = messages
    else if (Array.isArray(messages.messages)) list = messages.messages
    else if (Array.isArray(messages.data)) list = messages.data
    else if (Array.isArray(messages.items)) list = messages.items

    const existing = new Set([...container.children].map(el => el.dataset.id))

    list.forEach(msg => {
        const id = msg.id || msg.content + msg.created_at
        if (existing.has(id)) return

        const node = createMessageNode(msg)
        node.dataset.id = id
        container.appendChild(node)
    })

    container.scrollTo({
        top: container.scrollHeight,
        behavior: "smooth"
    })
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
            loadSidebar()
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

            if (msg.direction === "agent") return
            if (data.session_id !== currentSessionId) return

            removeTyping()

            const container = document.getElementById("messages")
            if (!container) return

            const id = msg.id || msg.content + msg.created_at

            if ([...container.children].some(el => el.dataset.id === id)) return

            if (msg.direction === "in") {
                const audio = document.getElementById("notificationSound")
                if (audio) audio.play().catch(() => {})
            }

            const node = createMessageNode(msg)
            node.dataset.id = id
            container.appendChild(node)

            container.scrollTo({
                top: container.scrollHeight,
                behavior: "smooth"
            })
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