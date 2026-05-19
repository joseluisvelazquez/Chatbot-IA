import { getWebSocketUrl } from "./config.js";
import { dispatch } from "./store.js";

let socket = null;
const listeners = new Set();
const pendingVerificationPatches = new Map();
let verificationPatchTimer = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
let hasConnectedOnce = false;

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;

function stripUndefinedEntries(value) {
    return Object.fromEntries(
        Object.entries(value).filter(([, item]) => item !== undefined)
    );
}

function extractVerificationPayload(data = {}) {
    const payload = data.payload && typeof data.payload === "object"
        ? data.payload
        : {};
    const patch = data.patch && typeof data.patch === "object"
        ? data.patch
        : {};
    const merged = {
        ...payload,
        ...patch,
        session_id: payload.session_id ?? data.session_id,
        folio: payload.folio ?? data.folio,
        no_cuenta: payload.no_cuenta ?? data.no_cuenta,
        status: payload.status ?? data.status ?? patch.state,
        updated_at: payload.updated_at ?? data.updated_at,
        last_activity: payload.last_activity ?? data.updated_at,
    };
    return merged && typeof merged === "object" ? merged : null;
}

function buildVerificationChanges(payload = {}) {
    return stripUndefinedEntries({
        progress_pct: payload.progress_pct ?? payload.progress,
        current_step: payload.current_step,
        status: payload.status ?? payload.state,
        folio: payload.folio,
        phone: payload.phone,
        name: payload.name,
        last_activity: payload.last_activity || payload.updated_at,
        inconsistencias_count: payload.inconsistencias_count,
        has_inconsistency: payload.has_inconsistency,
        inconsistencias: payload.inconsistencias,
        severity_counts: payload.severity_counts,
        highest_severity: payload.highest_severity,
        no_cuenta: payload.no_cuenta,
        siga_url: payload.siga_url,
        siga: payload.siga,
        siga_bridge: payload.siga_bridge,
        confirmed_count: payload.confirmed_count,
        total_steps: payload.total_steps,
        session_state: payload.session_state,
        previous_state: payload.previous_state,
    });
}

function queueVerificationPatch(payload = {}) {
    const sessionId = payload.session_id;
    if (!sessionId) return;

    const key = String(sessionId);
    const previous = pendingVerificationPatches.get(key) || {};
    pendingVerificationPatches.set(key, {
        ...previous,
        ...payload,
    });

    if (verificationPatchTimer) return;

    verificationPatchTimer = window.setTimeout(() => {
        const entries = Array.from(pendingVerificationPatches.values());
        pendingVerificationPatches.clear();
        verificationPatchTimer = null;

        entries.forEach((item) => {
            dispatch({
                type: "verifications/patch",
                payload: {
                    session_id: item.session_id,
                    changes: buildVerificationChanges(item),
                },
            });
        });
    }, 80);
}

function notifySocketEvent(name, detail = {}) {
    window.dispatchEvent(new CustomEvent(name, { detail }));
}

function notifyMessage(data) {
    notifySocketEvent("panel:ws-message", data);
    listeners.forEach(fn => fn(data));
}

function scheduleReconnect() {
    if (reconnectTimer) return;

    const exponentialDelay = Math.min(
        RECONNECT_MAX_MS,
        RECONNECT_BASE_MS * (2 ** reconnectAttempts)
    );
    const jitter = Math.floor(Math.random() * 250);
    const delay = exponentialDelay + jitter;

    reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        reconnectAttempts += 1;
        initWebSocket();
    }, delay);
}

export function initWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return socket;
    }

    socket = new WebSocket(getWebSocketUrl("/api/panel/ws"));

    socket.onopen = () => {
        const wasReconnect = hasConnectedOnce;
        hasConnectedOnce = true;
        reconnectAttempts = 0;
        if (wasReconnect) {
            notifySocketEvent("panel:ws-reconnected");
        }
    };

    socket.onmessage = (event) => {
        let data = null;
        try {
            data = JSON.parse(event.data);
        } catch (error) {
            console.warn("[websocket] mensaje invalido:", error);
            return;
        }

        if (data.type === "new_message") {
            const sessionId = data.session_id;
            const message = {
                ...(data.message || {}),
                id: data.message?.id ?? data.message_id,
                message_id: data.message?.message_id ?? data.message_id,
                direction: data.message?.direction ?? data.direction,
                created_at: data.message?.created_at ?? data.created_at,
                content: data.message?.content ?? data.preview,
            };
            const conversationPatch = data.conversation_patch || {};
            const conversation = {
                ...(data.conversation || {}),
                ...conversationPatch,
                id: sessionId,
                phone: data.phone || data.conversation?.phone || message.phone || null,
                name: data.name || data.conversation?.name || null,
                last_message: conversationPatch.last_message || message.content || data.conversation?.last_message || "",
                last_message_at: conversationPatch.last_message_at || message.created_at || data.conversation?.last_message_at || "",
                last_customer_message_at: data.conversation?.last_customer_message_at || null,
            };

            dispatch({
                type: "conversations/upsert",
                payload: conversation,
            });

            dispatch({
                type: "messages/add",
                payload: {
                    sessionId,
                    message,
                    conversation,
                },
            });

            dispatch({
                type: "conversations/move_top",
                payload: {
                    session_id: sessionId,
                },
            });

            if (typeof data.unread_count === "number") {
                dispatch({
                    type: "conversations/set_unread",
                    payload: {
                        session_id: sessionId,
                        unread_count: data.unread_count,
                    },
                });
            }
        }

        if (data.type === "update_unread") {
            dispatch({
                type: "conversations/set_unread",
                payload: {
                    session_id: data.session_id,
                    unread_count: data.unread_count ?? 0,
                },
            });
        }

        if (["dashboard_update", "dashboard_updated"].includes(data.type) && data.payload) {
            dispatch({
                type: "dashboard/apply_delta",
                payload: data.payload,
            });
        }


        if (
            ["verification_update", "verification_updated", "siga_snapshot_updated"].includes(data.type)
            && extractVerificationPayload(data)
        ) {
            queueVerificationPatch(extractVerificationPayload(data));
        }
        if (data.type === "conversation_updated" && (data.payload || data.patch)) {
            const payload = data.payload || {};
            const patch = data.patch || {};
            const sessionId = payload.session_id || data.session_id;
            dispatch({
                type: "conversations/upsert",
                payload: {
                    id: sessionId,
                    session_id: sessionId,
                    ...patch,
                    folio: patch.folio ?? payload.folio,
                    no_cuenta: patch.no_cuenta ?? payload.no_cuenta,
                    last_message_at: patch.last_message_at ?? payload.last_message_at ?? payload.updated_at,
                },
            });
            queueVerificationPatch({ ...payload, ...patch, session_id: sessionId });
        }
        if (["inconsistencia_updated", "inconsistency_updated"].includes(data.type) && data.payload) {
            dispatch({
                type: "verifications/update_inconsistencia",
                payload: data.payload,
            });
        }
        if (data.type === "inconsistency_created") {
            queueVerificationPatch({
                session_id: data.session_id,
                folio: data.folio,
                has_inconsistency: true,
                last_activity: data.created_at,
            });
        }

        notifyMessage(data);
    };

    socket.onclose = () => {
        socket = null;
        scheduleReconnect();
    };

    socket.onerror = () => {
        socket?.close();
    };

    return socket;
}

export function getWebSocket() {
    return socket;
}

export function subscribe(fn) {
    listeners.add(fn);

    return () => {
        listeners.delete(fn);
    };
}
