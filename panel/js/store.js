const state = {
    dashboard: {
        total_sessions: 0,
        active_sessions: 0,
        messages_in: 0,
        messages_out: 0,
        issues_open: 0,
        funnel: [],
        loaded: false,
        _funnelVersion: 0,
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
    auth: {
        user: null,
    },
}

const listeners = new Set()

function cloneState() {
    return {
        ...state,
        dashboard: {
            ...state.dashboard,
            funnel: [...state.dashboard.funnel],
        },
        conversations: {
            ...state.conversations,
            byId: { ...state.conversations.byId },
            order: [...state.conversations.order],
        },
        messages: {
            bySessionId: state.messages.bySessionId,
            versionsBySessionId: { ...state.messages.versionsBySessionId },
        },
        chat: structuredClone(state.chat),
        verifications: {
            ...state.verifications,
            bySessionId: state.verifications.bySessionId,
            order: [...state.verifications.order],
        },
        auth: { ...state.auth },
    }
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

function normalizeDateValue(value) {
    if (!value) return null
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date
}

function isIncomingConversationStale(current = {}, incoming = {}) {
    const currentDate = normalizeDateValue(current.last_message_at)
    const incomingDate = normalizeDateValue(incoming.last_message_at)

    if (!currentDate || !incomingDate) return false

    return incomingDate.getTime() < currentDate.getTime()
}

function normalizeConversation(session = {}) {
    const id = toSessionId(session.id ?? session.session_id)
    if (!id) return null

    const current = state.conversations.byId[id] || {}
    const phone = session.phone ?? current.phone ?? null
    const name = session.name ?? current.name ?? null

    const merged = {
        ...current,
        ...session,
        id,
        phone,
        name,
    }

    if (isIncomingConversationStale(current, session)) {
        merged.last_message = current.last_message
        merged.last_message_at = current.last_message_at
        merged.unread_count = current.unread_count ?? merged.unread_count
    }

    merged.display_name = merged.name || merged.phone || "Cliente sin nombre"

    return merged
}

function shallowEqualObjects(a = {}, b = {}) {
    const aKeys = Object.keys(a)
    const bKeys = Object.keys(b)

    if (aKeys.length !== bKeys.length) return false

    for (const key of aKeys) {
        if (a[key] !== b[key]) return false
    }

    return true
}

function upsertConversation(session) {
    const normalized = normalizeConversation(session)
    if (!normalized) return false

    const current = state.conversations.byId[normalized.id]
    if (current && shallowEqualObjects(current, normalized)) {
        return false
    }

    state.conversations.byId[normalized.id] = normalized

    const exists = state.conversations.order.includes(normalized.id)
    if (!exists) {
        state.conversations.order.unshift(normalized.id)
    }

    return true
}

function moveConversationToTop(sessionId) {
    const id = toSessionId(sessionId)
    if (!id) return false

    const currentOrder = state.conversations.order
    if (!currentOrder.includes(id)) return false
    if (currentOrder[0] === id) return false

    state.conversations.order = [
        id,
        ...currentOrder.filter(item => item !== id),
    ]
    return true
}

function getMessageKey(message) {
    if (!message) return null
    return (
        message.id ??
        message.message_id ??
        `${message.content || message.media_url || "message"}-${message.created_at || ""}`
    )
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
    const current = state.verifications.bySessionId[sessionKey] || {}
    const next = {
        ...current,
        ...item,
    }

    if (JSON.stringify(current) === JSON.stringify(next)) {
        return false
    }

    state.verifications.bySessionId[sessionKey] = next

    const exists = state.verifications.order.includes(sessionKey)
    if (!exists) {
        state.verifications.order.unshift(sessionKey)
    }

    return true
}

function setSelectedSession(payload) {
    if (payload == null) {
        if (
            state.chat.selectedSessionId == null &&
            state.chat.selectedSession == null
        ) {
            return false
        }

        state.chat.selectedSessionId = null
        state.chat.selectedSession = null
        state.chat._version++
        return true
    }

    const sessionId = toSessionId(
        payload.sessionId ?? payload.id ?? payload.session_id
    )
    if (!sessionId) return false

    const session =
        normalizeConversation({
            id: sessionId,
            phone: payload.phone ?? null,
            name: payload.name ?? null,
        }) || {
            id: sessionId,
            phone: payload.phone ?? null,
            name: payload.name ?? null,
            display_name: payload.name || payload.phone || "Cliente sin nombre",
        }

    const nextSelectedSessionId = toSessionKey(sessionId)
    const nextSelectedSession = {
        sessionId,
        phone: session.phone,
        name: session.name,
        display_name: session.display_name,
    }

    const sameSelection =
        state.chat.selectedSessionId === nextSelectedSessionId &&
        JSON.stringify(state.chat.selectedSession) === JSON.stringify(nextSelectedSession)

    if (sameSelection) return false

    state.chat.selectedSessionId = nextSelectedSessionId
    state.chat.selectedSession = nextSelectedSession
    state.chat._version++
    return true
}

function clampIndex(index, length) {
    if (!length) return 0

    const numericIndex = Number(index)
    if (!Number.isFinite(numericIndex)) return 0

    return Math.max(0, Math.min(length - 1, Math.trunc(numericIndex)))
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

function findVerificationKeyByInconsistencia({ session_id, ui_id, id }) {
    const explicitSessionKey = toSessionKey(session_id)

    if (explicitSessionKey && state.verifications.bySessionId[explicitSessionKey]) {
        return explicitSessionKey
    }

    if (
        state.verifications.selected &&
        state.verifications.bySessionId[state.verifications.selected]
    ) {
        const selectedVerification =
            state.verifications.bySessionId[state.verifications.selected]
        const selectedItems = Array.isArray(selectedVerification.inconsistencias)
            ? selectedVerification.inconsistencias
            : []

        if (selectedItems.some(item => matchesInconsistencia(item, { ui_id, id }))) {
            return state.verifications.selected
        }
    }

    return (
        Object.keys(state.verifications.bySessionId).find((sessionKey) => {
            const verification = state.verifications.bySessionId[sessionKey]
            const items = Array.isArray(verification?.inconsistencias)
                ? verification.inconsistencias
                : []

            return items.some(item => matchesInconsistencia(item, { ui_id, id }))
        }) || null
    )
}

function normalizeSeverity(value) {
    const severity = String(value || "").trim().toLowerCase()
    return ["leve", "moderada", "critica"].includes(severity) ? severity : null
}

function summarizeInconsistencias(items = []) {
    const openItems = items.filter(
        item => String(item.estado || "").toUpperCase() === "ABIERTA"
    )

    const severityCounts = {
        leve: 0,
        moderada: 0,
        critica: 0,
        total: openItems.length,
    }

    const severityOrder = {
        leve: 1,
        moderada: 2,
        critica: 3,
    }

    let highestSeverity = null
    let highestPriority = 0

    openItems.forEach((item) => {
        const severity = normalizeSeverity(item.severidad)
        if (!severity) return

        severityCounts[severity]++

        if (severityOrder[severity] > highestPriority) {
            highestSeverity = severity
            highestPriority = severityOrder[severity]
        }
    })

    return {
        inconsistencias_count: openItems.length,
        severity_counts: severityCounts,
        highest_severity: highestSeverity,
    }
}

function isVerificationStalled(verification) {
    if (!verification?.last_activity) return false

    const lastActivity = new Date(verification.last_activity)
    if (Number.isNaN(lastActivity.getTime())) return false

    return Date.now() - lastActivity.getTime() > 30 * 60 * 1000
}

function resolveVerificationStatus(verification, inconsistencias) {
    if (verification.status === "human_required") {
        return "human_required"
    }

    const hasOpen = inconsistencias.some(
        inc => String(inc.estado || "").toUpperCase() === "ABIERTA"
    )

    if (hasOpen) {
        return "inconsistent"
    }

    const isCompleted = Number(verification.progress_pct || 0) >= 100
    if (isCompleted) {
        return "completed"
    }

    if (isVerificationStalled(verification)) {
        return "stalled"
    }

    return "in_progress"
}

function addMetric(current, delta) {
    return Math.max(0, Number(current || 0) + Number(delta || 0))
}

function normalizeFunnel(items = []) {
    const funnel = Array.isArray(items)
        ? items
            .map(item => ({
                step: String(item.step || ""),
                total: Math.max(0, Number(item.total || 0)),
                drop_off: Math.max(0, Number(item.drop_off || 0)),
                conversion_pct: Number(item.conversion_pct || 0),
            }))
            .filter(item => item.step)
        : []

    return recalculateFunnel(funnel)
}

function recalculateFunnel(funnel) {
    for (let i = 0; i < funnel.length; i++) {
        const current = Number(funnel[i].total || 0)
        const next = Number(funnel[i + 1]?.total || 0)

        funnel[i].drop_off = Math.max(current - next, 0)
        funnel[i].conversion_pct =
            current > 0
                ? Math.round((next / current) * 10000) / 100
                : 0
    }

    return funnel
}

function applyFunnelDeltas(payload = {}) {
    const rawDeltas = Array.isArray(payload.funnel_steps_delta)
        ? payload.funnel_steps_delta
        : payload.funnel_step_delta
            ? [payload.funnel_step_delta]
            : []

    if (!rawDeltas.length) return false

    const byStep = new Map(state.dashboard.funnel.map(item => [item.step, item]))
    let mutated = false

    rawDeltas.forEach((item) => {
        const step = String(item?.step || "")
        if (!step) return

        const delta = Number(item.delta || 0)
        if (!Number.isFinite(delta) || delta === 0) return

        if (!byStep.has(step)) {
            const created = { step, total: 0, drop_off: 0, conversion_pct: 0 }
            byStep.set(step, created)
            state.dashboard.funnel.push(created)
        }

        const entry = byStep.get(step)
        entry.total = Math.max(0, Number(entry.total || 0) + delta)
        mutated = true
    })

    if (!mutated) return false

    recalculateFunnel(state.dashboard.funnel)
    state.dashboard._funnelVersion++
    return true
}

export function dispatch(action) {
    if (!action?.type) return

    let changed = false

    switch (action.type) {
        case "dashboard/loaded": {
            state.dashboard = {
                ...state.dashboard,
                ...action.payload,
                loaded: true,
            }
            changed = true
            break
        }

        case "auth/set_user": {
            const nextUser = action.payload || null
            if (state.auth.user === nextUser) break

            state.auth.user = nextUser
            changed = true
            break
        }

        case "dashboard/funnel_loaded": {
            state.dashboard.funnel = normalizeFunnel(action.payload)
            state.dashboard._funnelVersion++
            changed = true
            break
        }

        case "dashboard/apply_delta": {
            const p = action.payload || {}

            const prev = {
                messages_in: state.dashboard.messages_in,
                messages_out: state.dashboard.messages_out,
                issues_open: state.dashboard.issues_open,
                total_sessions: state.dashboard.total_sessions,
                active_sessions: state.dashboard.active_sessions,
            }

            state.dashboard.messages_in = addMetric(state.dashboard.messages_in, p.messages_in_delta)
            state.dashboard.messages_out = addMetric(state.dashboard.messages_out, p.messages_out_delta)
            state.dashboard.issues_open = addMetric(state.dashboard.issues_open, p.issues_open_delta)
            state.dashboard.total_sessions = addMetric(state.dashboard.total_sessions, p.total_sessions_delta)
            state.dashboard.active_sessions = addMetric(state.dashboard.active_sessions, p.active_sessions_delta)

            const funnelChanged = applyFunnelDeltas(p)

            changed =
                funnelChanged ||
                prev.messages_in !== state.dashboard.messages_in ||
                prev.messages_out !== state.dashboard.messages_out ||
                prev.issues_open !== state.dashboard.issues_open ||
                prev.total_sessions !== state.dashboard.total_sessions ||
                prev.active_sessions !== state.dashboard.active_sessions

            break
        }

        case "conversations/loaded": {
            const items = Array.isArray(action.payload) ? action.payload : []

            state.conversations.byId = {}
            state.conversations.order = []

            items.forEach(item => {
                upsertConversation(item)
            })

            if (
                state.chat.selectedSessionId &&
                !state.conversations.byId[Number(state.chat.selectedSessionId)]
            ) {
                state.chat.selectedSessionId = null
                state.chat.selectedSession = null
                state.chat._version++
            }

            state.conversations.loaded = true
            state.conversations._version++
            changed = true
            break
        }

        case "conversations/upsert": {
            if (upsertConversation(action.payload)) {
                state.conversations._version++
                changed = true
            }
            break
        }

        case "conversations/move_top": {
            if (
                action.payload?.session_id &&
                moveConversationToTop(action.payload.session_id)
            ) {
                state.conversations._version++
                changed = true
            }
            break
        }

        case "conversations/set_unread": {
            const { session_id, unread_count } = action.payload || {}
            const id = toSessionId(session_id)
            if (!id || !state.conversations.byId[id]) break

            if (state.conversations.byId[id].unread_count === unread_count) break

            state.conversations.byId[id] = {
                ...state.conversations.byId[id],
                unread_count,
            }
            state.conversations._version++
            changed = true
            break
        }

        case "conversations/remove": {
            const id = toSessionId(action.payload?.session_id ?? action.payload?.id)
            if (!id || !state.conversations.byId[id]) break

            delete state.conversations.byId[id]
            state.conversations.order = state.conversations.order.filter(item => item !== id)

            delete state.messages.bySessionId[String(id)]
            delete state.messages.versionsBySessionId[String(id)]

            if (state.chat.selectedSessionId === String(id)) {
                state.chat.selectedSessionId = null
                state.chat.selectedSession = null
                state.chat._version++
            }

            state.conversations._version++
            changed = true
            break
        }

        case "messages/loaded": {
            const { sessionId, items } = action.payload || {}
            const key = toSessionKey(sessionId)
            if (!key) break

            const nextItems = Array.isArray(items) ? items : []
            state.messages.bySessionId[key] = nextItems
            bumpMessagesVersion(key)
            changed = true
            break
        }

        case "messages/add": {
            const { sessionId, message, conversation } = action.payload || {}
            const added = upsertMessage(sessionId, message)

            if (conversation) {
                const upserted = upsertConversation(conversation)
                if (upserted) {
                    state.conversations._version++
                    changed = true
                }
            }

            if (added && sessionId && state.conversations.byId[Number(sessionId)]) {
                state.conversations.byId[Number(sessionId)] = {
                    ...state.conversations.byId[Number(sessionId)],
                    last_message_at:
                        message.created_at ||
                        state.conversations.byId[Number(sessionId)].last_message_at,
                    last_message:
                        message.content ||
                        state.conversations.byId[Number(sessionId)].last_message,
                }

                if (moveConversationToTop(sessionId)) {
                    state.conversations._version++
                } else {
                    state.conversations._version++
                }

                changed = true
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
            changed = true
            break
        }

        case "chat/select_session": {
            changed = setSelectedSession(action.payload) || changed
            break
        }

        case "chat/set_loading": {
            const sessionId = action.payload?.sessionId
            const nextValue = sessionId == null ? null : toSessionKey(sessionId)

            if (state.chat.loadingSessionId === nextValue) break

            state.chat.loadingSessionId = nextValue
            state.chat._version++
            changed = true
            break
        }

        case "chat/next_load_request": {
            state.chat.loadRequestId++
            state.chat._version++
            changed = true
            break
        }

        case "chat/preview/set_files": {
            const files = Array.isArray(action.payload?.files)
                ? action.payload.files.filter(Boolean)
                : []
            const nextIndex = clampIndex(action.payload?.selectedIndex || 0, files.length)

            const sameFiles =
                state.chat.preview.files.length === files.length &&
                state.chat.preview.files.every((file, index) => file === files[index])

            if (sameFiles && state.chat.preview.selectedIndex === nextIndex) break

            state.chat.preview.files = files
            state.chat.preview.selectedIndex = nextIndex
            state.chat._previewVersion++
            changed = true
            break
        }

        case "chat/preview/select": {
            const length = state.chat.preview.files.length
            const index = Number(action.payload?.index)

            if (!length) {
                if (state.chat.preview.selectedIndex !== 0) {
                    state.chat.preview.selectedIndex = 0
                    state.chat._previewVersion++
                    changed = true
                }
                break
            }

            if (!Number.isFinite(index) || index < 0 || index >= length) {
                break
            }

            const nextIndex = Math.trunc(index)
            if (state.chat.preview.selectedIndex === nextIndex) break

            state.chat.preview.selectedIndex = nextIndex
            state.chat._previewVersion++
            changed = true
            break
        }

        case "chat/preview/remove_at": {
            const length = state.chat.preview.files.length
            const rawIndex = Number(action.payload?.index)

            if (!length || !Number.isFinite(rawIndex)) break

            const index = Math.trunc(rawIndex)
            if (index < 0 || index >= length) break

            const previousSelectedIndex = clampIndex(state.chat.preview.selectedIndex, length)
            state.chat.preview.files = state.chat.preview.files.filter((_, itemIndex) => itemIndex !== index)

            const nextSelectedIndex =
                index < previousSelectedIndex
                    ? previousSelectedIndex - 1
                    : previousSelectedIndex

            state.chat.preview.selectedIndex = clampIndex(
                nextSelectedIndex,
                state.chat.preview.files.length
            )
            state.chat._previewVersion++
            changed = true
            break
        }

        case "chat/preview/clear": {
            if (!state.chat.preview.files.length && state.chat.preview.selectedIndex === 0) break

            state.chat.preview.files = []
            state.chat.preview.selectedIndex = 0
            state.chat._previewVersion++
            changed = true
            break
        }

        case "chat/viewer/set_images": {
            const images = Array.isArray(action.payload?.images)
                ? action.payload.images.filter(Boolean)
                : []
            const nextIndex = clampIndex(action.payload?.selectedIndex || 0, images.length)

            const sameImages =
                state.chat.viewer.images.length === images.length &&
                state.chat.viewer.images.every((image, index) => image === images[index])

            if (sameImages && state.chat.viewer.selectedIndex === nextIndex) break

            state.chat.viewer.images = images
            state.chat.viewer.selectedIndex = nextIndex
            state.chat._viewerVersion++
            changed = true
            break
        }

        case "chat/viewer/open": {
            const images = Array.isArray(action.payload?.images)
                ? action.payload.images.filter(Boolean)
                : state.chat.viewer.images

            const nextIndex = clampIndex(action.payload?.selectedIndex || 0, images.length)

            const sameImages =
                state.chat.viewer.images.length === images.length &&
                state.chat.viewer.images.every((image, index) => image === images[index])

            if (
                sameImages &&
                state.chat.viewer.selectedIndex === nextIndex &&
                state.chat.viewer.open === true
            ) {
                break
            }

            state.chat.viewer.images = images
            state.chat.viewer.selectedIndex = nextIndex
            state.chat.viewer.open = true
            state.chat._viewerVersion++
            changed = true
            break
        }

        case "chat/viewer/show": {
            const nextIndex = clampIndex(action.payload?.index, state.chat.viewer.images.length)
            if (state.chat.viewer.selectedIndex === nextIndex) break

            state.chat.viewer.selectedIndex = nextIndex
            state.chat._viewerVersion++
            changed = true
            break
        }

        case "chat/viewer/close": {
            if (state.chat.viewer.open === false) break

            state.chat.viewer.open = false
            state.chat._viewerVersion++
            changed = true
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
            changed = true
            break
        }

        case "verifications/upsert": {
            if (upsertVerification(action.payload)) {
                state.verifications._version++
                changed = true
            }
            break
        }

        case "verifications/patch": {
            const session_id = toSessionKey(action.payload?.session_id)
            const changes = action.payload?.changes || {}
            if (!session_id) break

            const current = state.verifications.bySessionId[session_id]
            if (!current) {
                const canUpsert = [
                    "folio",
                    "phone",
                    "status",
                    "progress_pct",
                    "current_step",
                    "no_cuenta",
                ].some(key => changes[key] != null)

                if (!canUpsert) break

                const upserted = upsertVerification({
                    session_id: Number(session_id),
                    ...changes,
                })

                if (upserted) {
                    state.verifications._version++
                    changed = true
                }
                break
            }

            const next = {
                ...current,
                ...changes,
            }

            if (JSON.stringify(current) === JSON.stringify(next)) break

            state.verifications.bySessionId[session_id] = next
            state.verifications._version++
            changed = true
            break
        }

        case "verifications/select": {
            const nextSelected = toSessionKey(action.payload)
            if (state.verifications.selected === nextSelected) break

            state.verifications.selected = nextSelected
            changed = true
            break
        }

        case "verifications/update_inconsistencia": {
            const { id, ui_id, session_id, resolved_by_panel, resolved_by_siga } = action.payload || {}

            if (!id && !ui_id) break

            const verificationKey = findVerificationKeyByInconsistencia({
                session_id,
                ui_id,
                id,
            })
            if (!verificationKey) break

            const verification = state.verifications.bySessionId[verificationKey]
            if (!verification?.inconsistencias) break

            let inconsistenciaChanged = false

            const updatedInconsistencias = verification.inconsistencias.map(inc => {
                if (!matchesInconsistencia(inc, { ui_id, id })) return inc

                inconsistenciaChanged = true

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

            if (!inconsistenciaChanged) break

            const summary = summarizeInconsistencias(updatedInconsistencias)

            state.verifications.bySessionId[verificationKey] = {
                ...verification,
                inconsistencias: updatedInconsistencias,
                inconsistencias_count: summary.inconsistencias_count,
                severity_counts: summary.severity_counts,
                highest_severity: summary.highest_severity,
                status: resolveVerificationStatus(verification, updatedInconsistencias),
            }

            state.verifications._version++
            changed = true
            break
        }

        default:
            return
    }

    if (changed) {
        emit()
    }
}
