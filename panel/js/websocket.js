import { dispatch } from "./store.js" 
let socket = null
let listeners = new Set()
export function initWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return socket
    }

    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const url = `${wsProtocol}//${window.location.hostname}:8000/api/panel/ws`

    socket = new WebSocket(url)

    socket.onopen = () => {
        console.log("🟢 WS conectado")
    }

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data)

        console.log(" WS EVENT:", data)

        // -------------------------
        // 💬 MENSAJES
        // -------------------------
        if (data.type === "new_message") {
            const sessionId = data.session_id
            const message = data.message
            
            
            dispatch({
                type: "conversations/upsert",
                payload: {
                    id: sessionId,
                    last_message: message.content,
                    last_message_at: message.created_at
                }
            })

            dispatch({
                type: "messages/add",
                payload: {
                    sessionId,
                    message
                }
            })

            // mover conversación arriba
            dispatch({
                type: "conversations/move_top",
                payload: {
                    session_id: sessionId
                }
            })

            // unread count
            if (typeof data.unread_count === "number") {
                dispatch({
                    type: "conversations/set_unread",
                    payload: {
                        session_id: sessionId,
                        unread_count: data.unread_count
                    }
                })
            }

            // dashboard delta
            if (message?.direction === "in") {
                dispatch({
                    type: "dashboard/apply_delta",
                    payload: {
                        messages_in_delta: 1
                    }
                })
            }

            if (message?.direction === "out" || message?.direction === "agent") {
                dispatch({
                    type: "dashboard/apply_delta",
                    payload: {
                        messages_out_delta: 1
                    }
                })
            }
        }

        // -------------------------
        // 🔔 UNREAD
        // -------------------------
        if (data.type === "update_unread") {
            dispatch({
                type: "conversations/set_unread",
                payload: {
                    session_id: data.session_id,
                    unread_count: data.unread_count ?? 0
                }
            })
        }

        // -------------------------
        // 📊 DASHBOARD
        // -------------------------
        if (data.type === "dashboard_update" && data.payload) {
            dispatch({
                type: "dashboard/apply_delta",
                payload: data.payload
            })
        }

        // -------------------------
        // 📋 VERIFICATIONS
        // -------------------------
        if (data.type === "verification_update" && data.payload) {
            dispatch({
                type: "verifications/upsert",
                payload: data.payload
            })
        }

        // -------------------------
        // 👀 listeners opcionales (typing, etc.)
        // -------------------------
        listeners.forEach(fn => fn(data))
    }

    socket.onclose = () => {
        console.warn("🔴 WS cerrado")
        socket = null
        setTimeout(() => {
            initWebSocket()
        }, 2000)
    }

    socket.onerror = (err) => {
        console.error("WS error:", err)
    }

    return socket
}

export function getWebSocket() {
    return socket
}

export function subscribe(fn) {
    listeners.add(fn)

    return () => {
        listeners.delete(fn)
    }
}