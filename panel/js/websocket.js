import { getWebSocketUrl } from "./config.js";
import { dispatch } from "./store.js";

let socket = null;
const listeners = new Set();
const pendingVerificationPatches = new Map();
let verificationPatchTimer = null;

function stripUndefinedEntries(value) {
    return Object.fromEntries(
        Object.entries(value).filter(([, item]) => item !== undefined)
    );
}

function extractVerificationPayload(data = {}) {
    const payload = data.payload && typeof data.payload === "object"
        ? data.payload
        : data;
    return payload && typeof payload === "object" ? payload : null;
}

function buildVerificationChanges(payload = {}) {
    return stripUndefinedEntries({
        progress_pct: payload.progress_pct,
        current_step: payload.current_step,
        status: payload.status,
        folio: payload.folio,
        phone: payload.phone,
        name: payload.name,
        last_activity: payload.last_activity || payload.updated_at,
        inconsistencias_count: payload.inconsistencias_count,
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

export function initWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return socket;
    }

    socket = new WebSocket(getWebSocketUrl("/api/panel/ws"));

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
            const message = data.message || {};
            const conversation = {
                ...(data.conversation || {}),
                id: sessionId,
                phone: data.phone || data.conversation?.phone || message.phone || null,
                name: data.name || data.conversation?.name || null,
                last_message: message.content || data.conversation?.last_message || "",
                last_message_at: message.created_at || data.conversation?.last_message_at || "",
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

        if (data.type === "dashboard_update" && data.payload) {
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
        if (data.type === "conversation_updated" && data.payload) {
            dispatch({
                type: "conversations/upsert",
                payload: {
                    id: data.payload.session_id || data.session_id,
                    session_id: data.payload.session_id || data.session_id,
                    folio: data.payload.folio,
                    no_cuenta: data.payload.no_cuenta,
                    last_message_at: data.payload.updated_at,
                },
            });
            queueVerificationPatch(data.payload);
        }
        if (["inconsistencia_updated", "inconsistency_updated"].includes(data.type) && data.payload) {
            dispatch({
                type: "verifications/update_inconsistencia",
                payload: data.payload,
            });
        }

        listeners.forEach(fn => fn(data));
    };

    socket.onclose = () => {
        socket = null;
        setTimeout(() => {
            initWebSocket();
        }, 2000);
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
