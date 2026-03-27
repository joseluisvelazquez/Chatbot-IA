import { getConversations, getMessages } from "../js/api.js";

let currentSessionId = null;
let socket = null;
let lastTyping = 0;
let typingTimeout = null;
let hasOpenedFromURL = false;

// =========================
// URL
// =========================

function getSessionIdFromURL() {
    const params = new URLSearchParams(window.location.search);
    return params.get("session_id");
}

// =========================
// INIT
// =========================

export function initConversationsPage() {

    window.send = send;
    window.handleTyping = handleTyping;
    window.handleKeyDown = handleKeyDown;

    setupInputHandler();
    initWebSocket();

    loadSidebar().then((sessions) => {
        openConversationFromURL(sessions);
    });
}

// =========================
// INPUT HANDLER
// =========================

function setupInputHandler() {
    const input = document.getElementById("messageInput");

    if (!input) return;

    input.removeEventListener("keydown", input._handler);

    const handler = function (event) {
        if (event.key !== "Enter") return;

        if (event.shiftKey) return;

        event.preventDefault();
        send();
    };

    input._handler = handler;
    input.addEventListener("keydown", handler);
}

// =========================
// SIDEBAR
// =========================

export async function loadSidebar() {

    const sessions = await getConversations();
    const list = document.getElementById("conversationList");

    if (!list) return sessions;

    list.innerHTML = "";

    sessions.forEach(s => {

        const div = document.createElement("div");

        div.className = `
            px-4 py-3 cursor-pointer border-b
            border-gray-200 dark:border-slate-700
            hover:bg-gray-100 dark:hover:bg-slate-700
            transition
        `;

        div.innerHTML = `
            <div class="min-w-0 flex justify-between items-center">
                <div class="min-w-0">
                    <div class="font-semibold truncate">${s.phone}</div>
                    <div class="text-xs text-gray-500">${s.last_message_at ?? ""}</div>
                </div>
                ${
                    s.unread_count > 0
                        ? `<span class="bg-green-500 text-white text-xs px-2 py-1 rounded-full shrink-0">${s.unread_count}</span>`
                        : ""
                }
            </div>
        `;

        div.onclick = () => {
            loadChat(s.id, s.phone);

            // 🔥 actualizar URL al hacer click manual
            const url = new URL(window.location);
            url.searchParams.set("view", "conversations");
            url.searchParams.set("session_id", s.id);
            window.history.replaceState({}, "", url);
        };

        list.appendChild(div);
    });

    return sessions;
}

// =========================
// ABRIR DESDE URL (SIN LOOP)
// =========================

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

    // 🔥 limpiar URL después de usarla
    const url = new URL(window.location);
    url.searchParams.delete("session_id");
    window.history.replaceState({}, "", url);
}

// =========================
// CHAT
// =========================

export async function loadChat(sessionId, phone) {

    if (currentSessionId === sessionId) return;

    currentSessionId = sessionId;

    updateHeader(phone);

    const messages = await getMessages(sessionId);

    const container = document.getElementById("messages");
    if (!container) return;

    container.innerHTML = "";

    messages.forEach(m => {
        container.appendChild(createMessageNode(m));
    });

    container.scrollTop = container.scrollHeight;
}

// =========================
// HEADER
// =========================

function updateHeader(phone) {

    const header = document.getElementById("chatHeader");
    if (!header) return;

    header.innerHTML = `
        <div class="flex flex-col">
            <span class="font-semibold">${phone}</span>
            <span class="text-xs text-gray-400">En conversación</span>
        </div>
    `;
}

// =========================
// MENSAJES
// =========================

function createMessageNode(message) {

    const wrapper = document.createElement("div");

    wrapper.className =
        "w-full flex opacity-0 translate-y-2 transition-all duration-300";

    const isMine = message.direction === "agent";

    wrapper.innerHTML = `
        <div class="${
            isMine
                ? "ml-auto bg-green-500 text-white"
                : "bg-white dark:bg-slate-700 text-gray-900 dark:text-white"
        } px-3 py-2 rounded-lg max-w-xs shadow">
            ${message.content}
        </div>
    `;

    requestAnimationFrame(() => {
        wrapper.classList.remove("opacity-0", "translate-y-2");
    });

    return wrapper;
}

// =========================
// SEND
// =========================

export function send() {

    const input = document.getElementById("messageInput");
    if (!input || !input.value.trim()) return;

    const message = input.value;

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(
            JSON.stringify({
                type: "message",
                session_id: currentSessionId,
                content: message,
            })
        );
    }

    input.value = "";
}

// =========================
// TYPING
// =========================

export function handleTyping() {

    const now = Date.now();

    if (now - lastTyping < 2000) return;

    lastTyping = now;

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(
            JSON.stringify({
                type: "typing",
                session_id: currentSessionId,
            })
        );
    }

    clearTimeout(typingTimeout);

    typingTimeout = setTimeout(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(
                JSON.stringify({
                    type: "stop_typing",
                    session_id: currentSessionId,
                })
            );
        }
    }, 2000);
}

// =========================
// WEBSOCKET
// =========================

function initWebSocket() {

    if (socket) return;

    socket = new WebSocket("ws://localhost:8000/ws/panel");

    socket.onmessage = (event) => {

        const data = JSON.parse(event.data);

        if (data.type === "new_message") {

            if (data.session_id === currentSessionId) {

                const container = document.getElementById("messages");
                if (!container) return;

                container.appendChild(createMessageNode(data.message));
                container.scrollTop = container.scrollHeight;
            }

            // 🔥 solo refresca sidebar, sin abrir chat otra vez
            loadSidebar();
        }
    };
}