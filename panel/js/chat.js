let currentSessionId = null
let socket = null
let lastTyping = 0
let typingTimeout = null
import { getConversations } from "../js/api.js"
export function initConversationsPage() {
    
    window.send = send

    //función para formatear el número de teléfono en formato internacional
    function formatPhone(phone) {
        return "+" + phone.replace(/(\d{2})(\d{3})(\d{3})(\d{4})/, "$1 $2 $3 $4")
    }

    //INICIAS EL WS
    initWebSocket()

    // Función para formatear la hora de la última conversación
    function formatTime(dateString) {
        if (!dateString) return ""

        const date = new Date(dateString)
        return date.toLocaleTimeString("es-MX", {
            hour: "2-digit",
            minute: "2-digit"
        })
    }

    async function loadSidebar(){
        const sessions = await getConversations()
        const container = document.getElementById("conversationList")
        container.innerHTML = ""

        sessions.forEach(s => {
            const div = document.createElement("div")

            div.className = "conversation-item"

            div.innerHTML = `
                <div class="chat-row">
                    <div class="chat-info">
                        <b>${formatPhone(s.phone)}</b><br>
                        <small>${formatTime(s.last_message_at)}</small>
                    </div>

                    ${
                        s.unread_count > 0
                        ? `<span class="badge">${s.unread_count}</span>`
                        : ""
                    }
                </div>
            `

            div.onclick = () => loadChat(s.id, s.phone)

            container.appendChild(div)
        })
    }

    loadSidebar()}
    
// Mapeo de claves a etiquetas y emojis para mensajes de botón
const BUTTON_LABELS = {
    // verificación
    "MENU_VERIFICACION": "📋 Menú de verificación",
    "FOLIO_SI": "✔️ Confirmó folio",
    "NOMBRE_SI": "✔️ Confirmó nombre",
    "DOM_SI": "🏠 Confirmó domicilio",
    "FECHA_SI": "📅 Confirmó fecha",
    "PROD_SI": "📦 Confirmó producto",
    "PRODESTADOSI": "📦 Producto en buen estado",

    // pagos
    "PAGO_SI": "💰 Confirmó pago",
    "PAGOS_OK": "💳 Entendió pagos",

    // planes
    "PLAN3_OK": "📆 Aceptó plan 3 meses",
    "PLANES_OK": "📊 Revisó planes",

    // beneficios
    "BEN_OK": "🎉 Confirmó beneficios"
}

// Formatea mensajes que contienen el marcador [BOTON] para mostrar un botón estilizado
function formatButtonMessage(text) {
    if (!text) return text

    const match = text.match(/\[BOTON\]\s*(.+)/)

    if (!match) return text

    const key = match[1].trim()
    const label = BUTTON_LABELS[key] || key

    return `<span class="button-message">🔘 ${label}</span>`
}

// Formatea la hora a formato "hh:mm"
function formatTime(dateString) {
    const date = new Date(dateString)

    return date.toLocaleTimeString("es-MX", {
        hour: "2-digit",
        minute: "2-digit"
    })
}

// Formatea el texto con estilo de WhatsApp esto por que se ven los mensajes con ese formato, por ejemplo *bold* se convierte en bold pero en negro
function formatWhatsAppText(text) {
    if (!text) return ""

    return text
        // *bold*
        .replace(/\*(.*?)\*/g, "<b>$1</b>")

        // _italic_
        .replace(/_(.*?)_/g, "<i>$1</i>")

        // ~tachado~
        .replace(/~(.*?)~/g, "<s>$1</s>")

        // `codigo`
        .replace(/`(.*?)`/g, "<code>$1</code>")
}


export async function loadChat(sessionId, phone) {

    const isSameChat = currentSessionId === sessionId
    currentSessionId = sessionId

    console.log("CHAT ABIERTO:", sessionId, phone)

    const phoneSafe = phone || "Sin número"

    const header = document.getElementById("chatHeader")
    header.innerText = `📱 +${phoneSafe}`

    // marcar como leídos
    await fetch(`http://localhost:8000/api/panel/conversations/${sessionId}/read`, {
        method: "POST"
    })

    // refrescar sidebar
    if (window.loadSidebar) {
        window.loadSidebar()
    }

    const res = await fetch(`http://localhost:8000/api/panel/messages/${sessionId}`)
    const messages = await res.json()

    const container = document.getElementById("messages")

    // 🔥 SOLO limpiar si cambiaste de chat
    if (!isSameChat) {
        container.innerHTML = ""
    }

    let list = []

    if (Array.isArray(messages)) {
        list = messages
    } else if (Array.isArray(messages.messages)) {
        list = messages.messages
    } else if (Array.isArray(messages.data)) {
        list = messages.data
    } else if (Array.isArray(messages.items)) {
        list = messages.items
    }

    list.forEach(msg => {

        // 🔥 evitar duplicados
        if (container.innerHTML.includes(msg.content)) return

        const div = document.createElement("div")
        div.classList.add("message")

        if (msg.direction === "in") div.classList.add("incoming")
        else if (msg.direction === "out") div.classList.add("outgoing")
        else if (msg.direction === "agent") div.classList.add("agent")

        const time = msg.created_at ? formatTime(msg.created_at) : ""

        const label =
            msg.direction === "out" ? "Bot 🤖" :
            msg.direction === "agent" ? "Tú 🧑‍💻" :
            msg.direction === "in" ? "Cliente 👤" :
            ""

        const content = formatButtonMessage(msg.content)
        const finalText = formatWhatsAppText(content)

        div.innerHTML = `
            <div class="text">${finalText}</div>
            <div class="meta">
                ${label ? `${label} · ${time}` : time}
            </div>
        `

        container.appendChild(div)
    })

    container.scrollTo({
        top: container.scrollHeight,
        behavior: "smooth"
    })
}

window.handleKeyDown = function(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault()
        send()
    }
}

export async function send() {
    const input = document.getElementById("messageInput")
    const content = input.value.trim()

    if (!content || !currentSessionId) return

    const container = document.getElementById("messages")

    const div = document.createElement("div")
    div.classList.add("message", "agent")

    const time = formatTime(new Date())

    div.innerHTML = `
        <div class="text">${formatWhatsAppText(content)}</div>
        <div class="meta">Tú 🧑‍💻 · ${time}</div>
    `

    container.appendChild(div)
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

function showTyping(text = "✍️ escribiendo...") {
    removeTyping()

    const container = document.getElementById("messages")
    const div = document.createElement("div")
    div.id = "typing"
    div.classList.add("typing")
    div.innerText = text

    container.appendChild(div)
    container.scrollTop = container.scrollHeight
}

function removeTyping() {
    const typing = document.getElementById("typing")
    if (typing) typing.remove()
}

export function initWebSocket() {
    socket = new WebSocket("ws://localhost:8000/api/panel/ws")

    socket.onopen = () => {
        console.log("🟢 WebSocket conectado")
    }

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data)
        console.log("WS recibido:", data)

        if (data.type === "typing") {
            if (data.session_id === currentSessionId) {
                showTyping()

                if (typingTimeout) clearTimeout(typingTimeout)
                typingTimeout = setTimeout(() => {
                    removeTyping()
                }, 2000)
            }
            return
        }

        if (data.type === "new_message") {

            const msg = data.message   // 🔥 PRIMERO define esto

            // 🔥 siempre refrescar sidebar
            if (window.loadSidebar) {
                window.loadSidebar()
            }

            if (msg.direction === "agent") return

            if (msg.direction === "in" || msg.direction === "out") {
                removeTyping()
            }

            if (msg.direction === "in") {
                const audio = document.getElementById("notificationSound")
                if (audio) audio.play().catch(() => {})
            }

            if (data.session_id !== currentSessionId) return

            const container = document.getElementById("messages")
            const div = document.createElement("div")
            div.classList.add("message")

            const time = msg.created_at
                ? formatTime(msg.created_at)
                : formatTime(new Date())

            if (msg.direction === "in") {
                div.classList.add("incoming")
            } else if (msg.direction === "out") {
                div.classList.add("outgoing")
            } else if (msg.direction === "agent") {
                div.classList.add("agent")
            }

            const label =
                msg.direction === "out" ? "Bot 🤖" :
                msg.direction === "agent" ? "Tú 🧑‍💻" :
                msg.direction === "in" ? "Cliente 👤" :
                ""

            const content = formatButtonMessage(msg.content)
            const finalText = formatWhatsAppText(content)

            div.innerHTML = `
                <div class="text">${finalText}</div>
                <div class="meta">
                    ${label ? `${label} · ${time}` : time}
                </div>
            `

            container.appendChild(div)
            container.scrollTo({
                top: container.scrollHeight,
                behavior: "smooth"
            })
        }
    }

    socket.onclose = () => {
        console.log("🔴 WebSocket cerrado... reconectando en 2s")
        setTimeout(initWebSocket, 2000)
    }
}

function sendTypingEvent() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return
    if (!currentSessionId) return

    socket.send(JSON.stringify({
        type: "typing",
        session_id: currentSessionId
    }))
}

window.handleTyping = function () {
    const now = Date.now()

    if (now - lastTyping < 1000) return

    lastTyping = now
    sendTypingEvent()
}