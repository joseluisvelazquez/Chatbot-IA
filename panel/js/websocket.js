import { getWebSocketUrl } from "./config.js"
import { dispatch } from "./store.js"

let socket = null

const listeners = new Set()
const seenEventIds = new Set()

let heartbeatTimer = null
let reconnectTimer = null
let reconnectAttempts = 0
let manuallyClosed = false
let lastConnectAt = 0

const MAX_EVENT_CACHE = 1000
const HEARTBEAT_MS = 30000
const MIN_RECONNECT_MS = 1000
const MAX_RECONNECT_MS = 30000
const STALE_CONNECT_GUARD_MS = 1500

function clearReconnectTimer() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
    }
}

function clearHeartbeat() {
    if (heartbeatTimer) {
        clearInterval(heartbeatTimer)
        heartbeatTimer = null
    }
}

function trimSeenEvents() {
    while (seenEventIds.size > MAX_EVENT_CACHE) {
        const first = seenEventIds.values().next().value
        seenEventIds.delete(first)
    }
}

function shouldReconnect(code) {
    const numeric = Number(code || 0)

    if ([1000, 1001, 1003].includes(numeric)) {
        return false
    }

    if ([1008, 4401, 4403].includes(numeric)) {
        window.location.href = "/panel/"
        return false
    }

    return true
}

function reconnectDelay() {
    const exp = Math.min(reconnectAttempts, 5)
    return Math.min(
        MAX_RECONNECT_MS,
        MIN_RECONNECT_MS * (2 ** exp)
    )
}

function scheduleReconnect() {
    if (manuallyClosed) return

    clearReconnectTimer()
    reconnectAttempts += 1

    const delay = reconnectDelay()
    emit({
        type: "socket_status",
        status: "reconnecting",
        delay,
    })

    reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        initWebSocket()
    }, delay)
}

function stripUndefinedEntries(value) {
    return Object.fromEntries(
        Object.entries(value || {}).filter(
            ([, item]) => item !== undefined
        )
    )
}

function emit(data) {
    listeners.forEach(fn => {
        try {
            fn(data)
        } catch (error) {
            console.error("WS listener error:", error)
        }
    })
}

function handleNewMessage(data) {
    const sessionId = Number(data.session_id)
    if (!sessionId) return

    const message = data.message || {}

    const conversation = {
        ...(data.conversation || {}),
        id: sessionId,
        phone:
            data.phone ||
            data.conversation?.phone ||
            message.phone ||
            null,
        name:
            data.name ||
            data.conversation?.name ||
            null,
        last_message:
            message.content ||
            data.conversation?.last_message ||
            "",
        last_message_at:
            message.created_at ||
            data.conversation?.last_message_at ||
            "",
    }

    dispatch({
        type: "conversations/upsert",
        payload: conversation,
    })

    dispatch({
        type: "messages/add",
        payload: {
            sessionId,
            message,
            conversation,
        },
    })

    dispatch({
        type: "conversations/move_top",
        payload: {
            session_id: sessionId,
        },
    })

    if (typeof data.unread_count === "number") {
        dispatch({
            type: "conversations/set_unread",
            payload: {
                session_id: sessionId,
                unread_count: data.unread_count,
            },
        })
    }
}

function handleConversationUpsert(payload) {
    if (!payload?.id) return

    dispatch({
        type: "conversations/upsert",
        payload,
    })
}

function handleVerificationPatch(payload) {
    if (!payload?.session_id) return

    dispatch({
        type: "verifications/patch",
        payload: {
            session_id: payload.session_id,
            changes: stripUndefinedEntries({
                progress_pct: payload.progress_pct,
                current_step: payload.current_step,
                status: payload.status,
                folio: payload.folio,
                phone: payload.phone,
                last_activity: payload.last_activity,
                inconsistencias_count: payload.inconsistencias_count,
                inconsistencias: payload.inconsistencias,
                severity_counts: payload.severity_counts,
                highest_severity: payload.highest_severity,
                no_cuenta: payload.no_cuenta,
                siga_url: payload.siga_url,
                confirmed_count: payload.confirmed_count,
                total_steps: payload.total_steps,
            }),
        },
    })
}

function processMessage(data) {
    if (!data || typeof data !== "object") return

    if (data.event_id) {
        if (seenEventIds.has(data.event_id)) return

        seenEventIds.add(data.event_id)
        trimSeenEvents()
    }

    switch (data.type) {
        case "pong":
        case "heartbeat":
            return

        case "new_message":
            handleNewMessage(data)
            break

        case "update_unread":
            dispatch({
                type: "conversations/set_unread",
                payload: {
                    session_id: data.session_id,
                    unread_count: data.unread_count ?? 0,
                },
            })
            break

        case "conversation_update":
        case "chat_operation":
            handleConversationUpsert(data.payload)
            break

        case "conversation_removed":
            if (data.payload?.session_id) {
                dispatch({
                    type: "conversations/remove",
                    payload: {
                        session_id: data.payload.session_id,
                    },
                })
            }
            break

        case "dashboard_update":
            if (data.payload) {
                dispatch({
                    type: "dashboard/apply_delta",
                    payload: data.payload,
                })
            }
            break

        case "verification_update":
            handleVerificationPatch(data.payload)
            break

        case "inconsistencia_updated":
            if (data.payload) {
                dispatch({
                    type: "verifications/update_inconsistencia",
                    payload: data.payload,
                })
            }
            break
    }

    emit(data)
}

export function initWebSocket() {
    const now = Date.now()

    if (
        socket &&
        (
            socket.readyState === WebSocket.OPEN ||
            socket.readyState === WebSocket.CONNECTING
        )
    ) {
        return socket
    }

    if (now - lastConnectAt < STALE_CONNECT_GUARD_MS) {
        return socket
    }

    lastConnectAt = now
    manuallyClosed = false

    clearReconnectTimer()
    clearHeartbeat()

    try {
        if (socket) socket.close()
    } catch {}

    socket = new WebSocket(
        getWebSocketUrl("/api/panel/ws")
    )

    socket.onopen = () => {
        reconnectAttempts = 0
        clearReconnectTimer()
        clearHeartbeat()

        heartbeatTimer = setInterval(() => {
            if (socket?.readyState === WebSocket.OPEN) {
                try {
                    socket.send(JSON.stringify({
                        type: "ping",
                        ts: Date.now(),
                    }))
                } catch {}
            }
        }, HEARTBEAT_MS)

        emit({
            type: "socket_status",
            status: "connected",
        })
    }

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data)
            processMessage(data)
        } catch (error) {
            console.error(
                "WS payload invalido:",
                event.data
            )
        }
    }

    socket.onclose = (event) => {
        clearHeartbeat()
        socket = null

        emit({
            type: "socket_status",
            status: "disconnected",
            code: event.code,
        })

        if (shouldReconnect(event.code)) {
            scheduleReconnect()
        }
    }

    socket.onerror = (event) => {
        console.error("WebSocket error:", event)

        emit({
            type: "socket_status",
            status: "error",
        })

        try {
            socket?.close()
        } catch {}
    }

    return socket
}

export function getWebSocket() {
    return socket
}

export function closeWebSocket() {
    manuallyClosed = true
    clearReconnectTimer()
    clearHeartbeat()

    try {
        socket?.close(1000)
    } catch {}

    socket = null
}

export function subscribe(fn) {
    listeners.add(fn)

    return () => {
        listeners.delete(fn)
    }
}
