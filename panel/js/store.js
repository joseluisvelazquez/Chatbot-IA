const state = {
    dashboard: {
        total_sessions: 0,
        active_sessions: 0,
        messages_in: 0,
        messages_out: 0,
        issues_open: 0,
        loaded: false,
    },
    conversations: {
        byId: {},
        order: [],
        loaded: false,
        _version: 0
    },
    messages: {
        bySessionId: {},
    },
    verifications: {
        bySessionId: {},
        order: [],
        loaded: false,
    },
}

const listeners = new Set()

function cloneState() {
    return structuredClone(state)
}

export function getState() {
    return cloneState()
}

export function subscribeStore(listener) {
    listeners.add(listener)
    return () => listeners.delete(listener)
}

function emit() {
    const snapshot = cloneState()
    listeners.forEach(fn => fn(snapshot))
}

function upsertConversation(session) {
    if (!session?.id) return

    state.conversations.byId[session.id] = {
        ...(state.conversations.byId[session.id] || {}),
        ...session,
    }

    const exists = state.conversations.order.includes(session.id)
    if (!exists) {
        state.conversations.order.unshift(session.id)
    }
}

function moveConversationToTop(sessionId) {
    state.conversations.order = [
        sessionId,
        ...state.conversations.order.filter(id => id !== sessionId),
    ]
}

function upsertMessage(sessionId, message) {
    if (!sessionId || !message) return

    if (!state.messages.bySessionId[sessionId]) {
        state.messages.bySessionId[sessionId] = []
    }

    const list = state.messages.bySessionId[sessionId]
    const messageId = message.id ?? `${message.content}-${message.created_at}`

    const exists = list.some(m => (m.id ?? `${m.content}-${m.created_at}`) === messageId)
    if (exists) return

    list.push(message)
}

function upsertVerification(item) {
    if (!item?.session_id) return

    state.verifications.bySessionId[item.session_id] = {
        ...(state.verifications.bySessionId[item.session_id] || {}),
        ...item,
    }

    const exists = state.verifications.order.includes(item.session_id)
    if (!exists) {
        state.verifications.order.unshift(item.session_id)
    }
}

export function dispatch(action) {
    if (!action?.type) return

    switch (action.type) {
        case "dashboard/loaded": {
            state.dashboard = {
                ...state.dashboard,
                ...action.payload,
                loaded: true,
            }
            break
        }

        case "dashboard/apply_delta": {
            const p = action.payload || {}

            state.dashboard.messages_in += Number(p.messages_in_delta || 0)
            state.dashboard.messages_out += Number(p.messages_out_delta || 0)
            state.dashboard.issues_open += Number(p.issues_open_delta || 0)
            state.dashboard.total_sessions += Number(p.total_sessions_delta || 0)
            state.dashboard.active_sessions += Number(p.active_sessions_delta || 0)
            break
        }

        case "conversations/loaded": {
            const items = Array.isArray(action.payload) ? action.payload : []

            state.conversations.byId = {}
            state.conversations.order = []

            items.forEach(item => {
                upsertConversation(item)
            })

            state.conversations.loaded = true
            state.conversations._version++
            break
        }

        case "conversations/upsert": {
            upsertConversation(action.payload)
            state.conversations._version++
            break
        }

        case "conversations/move_top": {
            if (action.payload?.session_id) {
                moveConversationToTop(action.payload.session_id)
                state.conversations._version++
            }
            break
        }

        case "conversations/set_unread": {
            const { session_id, unread_count } = action.payload || {}
            if (!session_id || !state.conversations.byId[session_id]) break

            state.conversations.byId[session_id] = {
                ...state.conversations.byId[session_id],
                unread_count,
            }
            state.conversations._version++
            break
        }

        case "messages/loaded": {
            const { sessionId, items } = action.payload || {}
            if (!sessionId) break

            state.messages.bySessionId[sessionId] = Array.isArray(items) ? items : []
            break
        }

        case "messages/add": {
            const { sessionId, message } = action.payload || {}
            upsertMessage(sessionId, message)

            if (sessionId && state.conversations.byId[sessionId]) {
                state.conversations.byId[sessionId] = {
                    ...state.conversations.byId[sessionId],
                    last_message_at: message.created_at || state.conversations.byId[sessionId].last_message_at,
                    last_message: message.content || state.conversations.byId[sessionId].last_message,
                }

                moveConversationToTop(sessionId)
                state.conversations._version++
            }

            break
        }
        case "messages/prepend": {
            const { sessionId, items } = action.payload

            const current = state.messages.bySessionId[sessionId] || []

            return {
                ...state,
                messages: {
                    ...state.messages,
                    bySessionId: {
                        ...state.messages.bySessionId,
                        [sessionId]: [...items, ...current]
                    }
                }
            }
        }

        case "verifications/loaded": {
            const items = Array.isArray(action.payload) ? action.payload : []

            state.verifications.bySessionId = {}
            state.verifications.order = []

            items.forEach(item => {
                upsertVerification(item)
            })

            state.verifications.loaded = true
            break
        }

        case "verifications/upsert": {
            upsertVerification(action.payload)
            break
        }
        case "verifications/patch": {
            const session_id = String(action.payload.session_id)
            const changes = action.payload.changes

            const current = state.verifications.bySessionId[session_id]
            if (!current) break

            // MUTAR ESTADO REAL
            state.verifications.bySessionId[session_id] = {
                ...current,
                ...changes
            }

            if (state.verifications.selected?.session_id == session_id) {
                state.verifications.selected = state.verifications.bySessionId[session_id]
            }

            break
        }
        case "verifications/select": {
            state.verifications.selected = String(action.payload)
            break
        }

        default:
            return
    }

    emit()
}