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
        _version: 0,
    },
    messages: {
        bySessionId: {},
        versionsBySessionId: {},
    },
    chat: {
        selectedSessionId: null,
        selectedSession: null,
        loadingSessionId: null,
        loadRequestId: 0,
        preview: {
            files: [],
            selectedIndex: 0,
        },
        viewer: {
            images: [],
            selectedIndex: 0,
            open: false,
        },
        _version: 0,
        _previewVersion: 0,
        _viewerVersion: 0,
    },
    verifications: {
        bySessionId: {},
        order: [],
        loaded: false,
        selected: null,
        _version: 0,
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

function toSessionKey(value) {
    if (value == null) return null
    return String(value)
}

function toSessionId(value) {
    const id = Number(value)
    return Number.isFinite(id) && id > 0 ? id : null
}

function normalizeConversation(session = {}) {
    const id = toSessionId(session.id ?? session.session_id)
    if (!id) return null

    const current = state.conversations.byId[id] || {}
    const phone = session.phone ?? current.phone ?? null
    const name = session.name ?? current.name ?? null

    return {
        ...current,
        ...session,
        id,
        phone,
        name,
        display_name: name || phone || "Cliente sin nombre",
    }
}

function upsertConversation(session) {
    const normalized = normalizeConversation(session)
    if (!normalized) return false

    state.conversations.byId[normalized.id] = normalized

    const exists = state.conversations.order.includes(normalized.id)
    if (!exists) {
        state.conversations.order.unshift(normalized.id)
    }

    return true
}

function moveConversationToTop(sessionId) {
    const id = toSessionId(sessionId)
    if (!id) return

    state.conversations.order = [
        id,
        ...state.conversations.order.filter(item => item !== id),
    ]
}

function getMessageKey(message) {
    if (!message) return null
    return message.id ?? message.message_id ?? `${message.content || message.media_url || "message"}-${message.created_at || ""}`
}

function bumpMessagesVersion(sessionId) {
    const key = toSessionKey(sessionId)
    if (!key) return

    state.messages.versionsBySessionId[key] =
        (state.messages.versionsBySessionId[key] || 0) + 1
}

function upsertMessage(sessionId, message) {
    const key = toSessionKey(sessionId)
    if (!key || !message) return false

    if (!state.messages.bySessionId[key]) {
        state.messages.bySessionId[key] = []
    }

    const list = state.messages.bySessionId[key]
    const messageKey = getMessageKey(message)
    if (!messageKey) return false

    const exists = list.some(item => getMessageKey(item) === messageKey)
    if (exists) return false

    list.push(message)
    bumpMessagesVersion(key)
    return true
}

function upsertVerification(item) {
    if (!item?.session_id) return false

    const sessionKey = toSessionKey(item.session_id)

    state.verifications.bySessionId[sessionKey] = {
        ...(state.verifications.bySessionId[sessionKey] || {}),
        ...item,
    }

    const exists = state.verifications.order.includes(sessionKey)
    if (!exists) {
        state.verifications.order.unshift(sessionKey)
    }

    return true
}

function setSelectedSession(payload) {
    if (payload == null) {
        state.chat.selectedSessionId = null
        state.chat.selectedSession = null
        state.chat._version++
        return
    }

    const sessionId = toSessionId(payload.sessionId ?? payload.id ?? payload.session_id)
    if (!sessionId) return

    const session = normalizeConversation({
        id: sessionId,
        phone: payload.phone ?? null,
        name: payload.name ?? null,
    }) || {
        id: sessionId,
        phone: payload.phone ?? null,
        name: payload.name ?? null,
        display_name: payload.name || payload.phone || "Cliente sin nombre",
    }

    state.chat.selectedSessionId = toSessionKey(sessionId)
    state.chat.selectedSession = {
        sessionId,
        phone: session.phone,
        name: session.name,
        display_name: session.display_name,
    }
    state.chat._version++
}

function clampIndex(index, length) {
    if (!length) return 0

    const numericIndex = Number(index)
    if (!Number.isFinite(numericIndex)) return 0

    return Math.max(0, Math.min(length - 1, numericIndex))
}

function findVerificationKeyByInconsistencia({ session_id, ui_id, id }) {
    const explicitSessionKey = toSessionKey(session_id)

    if (explicitSessionKey && state.verifications.bySessionId[explicitSessionKey]) {
        return explicitSessionKey
    }

    if (state.verifications.selected && state.verifications.bySessionId[state.verifications.selected]) {
        const selectedVerification = state.verifications.bySessionId[state.verifications.selected]
        const selectedItems = Array.isArray(selectedVerification.inconsistencias)
            ? selectedVerification.inconsistencias
            : []

        if (selectedItems.some(item => matchesInconsistencia(item, { ui_id, id }))) {
            return state.verifications.selected
        }
    }

    return Object.keys(state.verifications.bySessionId).find((sessionKey) => {
        const verification = state.verifications.bySessionId[sessionKey]
        const items = Array.isArray(verification?.inconsistencias)
            ? verification.inconsistencias
            : []

        return items.some(item => matchesInconsistencia(item, { ui_id, id }))
    }) || null
}

function matchesInconsistencia(item, { ui_id, id }) {
    if (!item) return false

    if (ui_id != null && String(item.ui_id || "") === String(ui_id)) {
        return true
    }

    if (ui_id == null && id != null && String(item.id || "") === String(id)) {
        return true
    }

    return false
}

function resolveVerificationStatus(verification, inconsistencias) {
    if (verification.status === "human_required") {
        return "human_required"
    }

    const isCompleted = Number(verification.progress_pct || 0) >= 100
    if (isCompleted) {
        return "completed"
    }

    const hasOpen = inconsistencias.some(
        inc => String(inc.estado || "").toUpperCase() === "ABIERTA"
    )

    return hasOpen ? "inconsistent" : "in_progress"
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
            if (upsertConversation(action.payload)) {
                state.conversations._version++
            }
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
            const id = toSessionId(session_id)
            if (!id || !state.conversations.byId[id]) break

            state.conversations.byId[id] = {
                ...state.conversations.byId[id],
                unread_count,
            }
            state.conversations._version++
            break
        }

        case "messages/loaded": {
            const { sessionId, items } = action.payload || {}
            const key = toSessionKey(sessionId)
            if (!key) break

            state.messages.bySessionId[key] = Array.isArray(items) ? items : []
            bumpMessagesVersion(key)
            break
        }

        case "messages/add": {
            const { sessionId, message, conversation } = action.payload || {}
            const added = upsertMessage(sessionId, message)

            if (conversation) {
                upsertConversation(conversation)
                state.conversations._version++
            }

            if (added && sessionId && state.conversations.byId[Number(sessionId)]) {
                state.conversations.byId[Number(sessionId)] = {
                    ...state.conversations.byId[Number(sessionId)],
                    last_message_at: message.created_at || state.conversations.byId[Number(sessionId)].last_message_at,
                    last_message: message.content || state.conversations.byId[Number(sessionId)].last_message,
                }

                moveConversationToTop(sessionId)
                state.conversations._version++
            }

            break
        }

        case "messages/prepend": {
            const { sessionId, items } = action.payload || {}
            const key = toSessionKey(sessionId)
            if (!key) break

            const current = state.messages.bySessionId[key] || []
            const incoming = Array.isArray(items) ? items : []
            const existingKeys = new Set(current.map(getMessageKey))
            const deduped = incoming.filter(item => !existingKeys.has(getMessageKey(item)))

            if (!deduped.length) break

            state.messages.bySessionId[key] = [...deduped, ...current]
            bumpMessagesVersion(key)
            break
        }

        case "chat/select_session": {
            setSelectedSession(action.payload)
            break
        }

        case "chat/set_loading": {
            const sessionId = action.payload?.sessionId
            state.chat.loadingSessionId = sessionId == null ? null : toSessionKey(sessionId)
            state.chat._version++
            break
        }

        case "chat/next_load_request": {
            state.chat.loadRequestId++
            state.chat._version++
            break
        }

        case "chat/preview/set_files": {
            const files = Array.isArray(action.payload?.files) ? action.payload.files.filter(Boolean) : []
            state.chat.preview.files = files
            state.chat.preview.selectedIndex = clampIndex(action.payload?.selectedIndex || 0, files.length)
            state.chat._previewVersion++
            break
        }

        case "chat/preview/select": {
            state.chat.preview.selectedIndex = clampIndex(action.payload?.index, state.chat.preview.files.length)
            state.chat._previewVersion++
            break
        }

        case "chat/preview/remove_at": {
            const index = clampIndex(action.payload?.index, state.chat.preview.files.length)
            const previousSelectedIndex = state.chat.preview.selectedIndex
            state.chat.preview.files = state.chat.preview.files.filter((_, itemIndex) => itemIndex !== index)

            const nextSelectedIndex =
                index < previousSelectedIndex
                    ? previousSelectedIndex - 1
                    : previousSelectedIndex

            state.chat.preview.selectedIndex = clampIndex(nextSelectedIndex, state.chat.preview.files.length)
            state.chat._previewVersion++
            break
        }

        case "chat/preview/clear": {
            state.chat.preview.files = []
            state.chat.preview.selectedIndex = 0
            state.chat._previewVersion++
            break
        }

        case "chat/viewer/set_images": {
            const images = Array.isArray(action.payload?.images) ? action.payload.images.filter(Boolean) : []
            state.chat.viewer.images = images
            state.chat.viewer.selectedIndex = clampIndex(action.payload?.selectedIndex || 0, images.length)
            state.chat._viewerVersion++
            break
        }

        case "chat/viewer/open": {
            const images = Array.isArray(action.payload?.images) ? action.payload.images.filter(Boolean) : state.chat.viewer.images
            state.chat.viewer.images = images
            state.chat.viewer.selectedIndex = clampIndex(action.payload?.selectedIndex || 0, images.length)
            state.chat.viewer.open = true
            state.chat._viewerVersion++
            break
        }

        case "chat/viewer/show": {
            state.chat.viewer.selectedIndex = clampIndex(action.payload?.index, state.chat.viewer.images.length)
            state.chat._viewerVersion++
            break
        }

        case "chat/viewer/close": {
            state.chat.viewer.open = false
            state.chat._viewerVersion++
            break
        }

        case "verifications/loaded": {
            const items = Array.isArray(action.payload) ? action.payload : []

            state.verifications.bySessionId = {}
            state.verifications.order = []

            items.forEach(item => {
                upsertVerification(item)
            })

            state.verifications.loaded = true
            state.verifications._version++
            break
        }

        case "verifications/upsert": {
            if (upsertVerification(action.payload)) {
                state.verifications._version++
            }
            break
        }

        case "verifications/patch": {
            const session_id = toSessionKey(action.payload?.session_id)
            const changes = action.payload?.changes || {}
            if (!session_id) break

            const current = state.verifications.bySessionId[session_id]
            if (!current) break

            state.verifications.bySessionId[session_id] = {
                ...current,
                ...changes,
            }

            state.verifications._version++
            break
        }

        case "verifications/select": {
            state.verifications.selected = toSessionKey(action.payload)
            break
        }
        
        case "verifications/update_inconsistencia": {
            const { id, ui_id, session_id, resolved_by_panel, resolved_by_siga } = action.payload || {}

            if (!id && !ui_id) return

            const verificationKey = findVerificationKeyByInconsistencia({ session_id, ui_id, id })
            if (!verificationKey) return

            const verification = state.verifications.bySessionId[verificationKey]
            if (!verification?.inconsistencias) return

            let changed = false
            const updatedInconsistencias = verification.inconsistencias.map(inc => {
                if (!matchesInconsistencia(inc, { ui_id, id })) return inc

                changed = true

                const nextPanelValue =
                    typeof resolved_by_panel === "boolean"
                        ? resolved_by_panel
                        : Boolean(inc.resolved_by_panel)

                const nextSigaValue =
                    typeof resolved_by_siga === "boolean"
                        ? resolved_by_siga
                        : Boolean(inc.resolved_by_siga)

                const isResolved = nextPanelValue || nextSigaValue

                return {
                    ...inc,
                    resolved_by_panel: nextPanelValue,
                    resolved_by_siga: nextSigaValue,
                    estado: isResolved ? "RESUELTA" : "ABIERTA",
                }
            })

            if (!changed) return

            state.verifications.bySessionId[verificationKey] = {
                ...verification,
                inconsistencias: updatedInconsistencias,
                status: resolveVerificationStatus(verification, updatedInconsistencias),
            }

            state.verifications._version++

            break
        }

        default:
            return
    }

    emit()
}
