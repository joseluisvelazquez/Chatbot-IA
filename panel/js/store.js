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
    collections: {
        byAccount: {},
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

function hasCollectionValue(value) {
    if (value == null) return false
    if (typeof value === "string") {
        const trimmed = value.trim()
        return trimmed !== "" && trimmed !== "-"
    }
    if (Array.isArray(value)) return value.length > 0
    if (typeof value === "object") return Object.keys(value).length > 0
    return true
}

function mergeCollectionObject(existing = {}, incoming = {}) {
    const merged = { ...(existing || {}) }

    Object.entries(incoming || {}).forEach(([key, value]) => {
        if (hasCollectionValue(value) || !hasCollectionValue(merged[key])) {
            merged[key] = value
        }
    })

    return merged
}

function mergeCollectionRecord(existing = {}, incoming = {}) {
    const merged = mergeCollectionObject(existing, incoming)

    if (existing?.customer || incoming?.customer) {
        merged.customer = mergeCollectionObject(existing.customer, incoming.customer)
    }

    if (existing?.financial_summary || incoming?.financial_summary) {
        merged.financial_summary = mergeCollectionObject(
            existing.financial_summary,
            incoming.financial_summary,
        )
    }

    return merged
}

function upsertCollection(item, options = {}) {
    const account = item?.no_cuenta == null ? null : String(item.no_cuenta)
    if (!account) return false

    state.collections.byAccount[account] = mergeCollectionRecord(
        state.collections.byAccount[account] || {},
        item,
    )

    const exists = state.collections.order.includes(account)
    if (!exists) {
        if (options.append) {
            state.collections.order.push(account)
        } else {
            state.collections.order.unshift(account)
        }
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
        ? items.map(item => ({
            step: String(item.step || ""),
            total: Math.max(0, Number(item.total || 0)),
            drop_off: Math.max(0, Number(item.drop_off || 0)),
            conversion_pct: Number(item.conversion_pct || 0),
        })).filter(item => item.step)
        : []

    return recalculateFunnel(sortFunnel(funnel))
}

const FUNNEL_STEP_ORDER = [
    "folio",
    "nombre",
    "domicilio",
    "fecha",
    "producto",
    "componentes",
    "pagoInicial",
    "pagos",
    "bancos",
    "comprobanteAcceso",
    "plan3meses",
    "planes",
    "beneficios",
    "finalizado",
]

function sortFunnel(funnel) {
    const index = new Map(FUNNEL_STEP_ORDER.map((step, idx) => [step, idx]))
    funnel.sort((a, b) => {
        const aIdx = index.has(a.step) ? index.get(a.step) : Number.MAX_SAFE_INTEGER
        const bIdx = index.has(b.step) ? index.get(b.step) : Number.MAX_SAFE_INTEGER
        if (aIdx !== bIdx) return aIdx - bIdx
        return String(a.step).localeCompare(String(b.step))
    })
    return funnel
}

function recalculateFunnel(funnel) {
    for (let i = 0; i < funnel.length; i++) {
        const current = Number(funnel[i].total || 0)
        const next = Number(funnel[i + 1]?.total || 0)

        funnel[i].drop_off = Math.max(current - next, 0)
        funnel[i].conversion_pct = current > 0
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
    let changed = false

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
        changed = true
    })

    if (!changed) return false

    recalculateFunnel(sortFunnel(state.dashboard.funnel))
    state.dashboard._funnelVersion++
    return true
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

        case "dashboard/funnel_loaded": {
            state.dashboard.funnel = normalizeFunnel(action.payload)
            state.dashboard._funnelVersion++
            break
        }

        case "dashboard/apply_delta": {
            const p = action.payload || {}

            state.dashboard.messages_in = addMetric(state.dashboard.messages_in, p.messages_in_delta)
            state.dashboard.messages_out = addMetric(state.dashboard.messages_out, p.messages_out_delta)
            state.dashboard.issues_open = addMetric(state.dashboard.issues_open, p.issues_open_delta)
            state.dashboard.total_sessions = addMetric(state.dashboard.total_sessions, p.total_sessions_delta)
            state.dashboard.active_sessions = addMetric(state.dashboard.active_sessions, p.active_sessions_delta)
            applyFunnelDeltas(p)
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
            const length = state.chat.preview.files.length
            const index = Number(action.payload?.index)

            if (!length) {
                state.chat.preview.selectedIndex = 0
                state.chat._previewVersion++
                break
            }

            if (!Number.isFinite(index) || index < 0 || index >= length) {
                break
            }

            state.chat.preview.selectedIndex = Math.trunc(index)
            state.chat._previewVersion++
            break
        }

        case "chat/preview/remove_at": {
            const length = state.chat.preview.files.length
            const rawIndex = Number(action.payload?.index)

            if (!length || !Number.isFinite(rawIndex)) {
                break
            }

            const index = Math.trunc(rawIndex)

            if (index < 0 || index >= length) {
                break
            }

            const previousSelectedIndex = clampIndex(state.chat.preview.selectedIndex, length)
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

                upsertVerification({
                    session_id: Number(session_id),
                    ...changes,
                })
                state.verifications._version++
                break
            }

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

            break
        }

        case "collections/loaded": {
            const items = Array.isArray(action.payload) ? action.payload : []

            state.collections.byAccount = {}
            state.collections.order = []

            items.forEach(item => {
                upsertCollection(item, { append: true })
            })

            state.collections.loaded = true
            state.collections._version++
            break
        }

        case "collections/append": {
            const items = Array.isArray(action.payload) ? action.payload : []
            let changed = false

            items.forEach(item => {
                changed = upsertCollection(item, { append: true }) || changed
            })

            if (changed || items.length) {
                state.collections.loaded = true
                state.collections._version++
            }
            break
        }

        case "collections/upsert": {
            if (upsertCollection(action.payload)) {
                state.collections._version++
            }
            break
        }

        case "collections/select": {
            state.collections.selected = action.payload == null ? null : String(action.payload)
            break
        }

        default:
            return
    }

    emit()
}
