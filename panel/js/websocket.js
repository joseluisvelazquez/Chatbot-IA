import { getWebSocketUrl } from "./config.js";
import { dispatch } from "./store.js";

let socket = null;
const listeners = new Set();

function stripUndefinedEntries(value) {
    return Object.fromEntries(
        Object.entries(value).filter(([, item]) => item !== undefined)
    );
}

export function initWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return socket;
    }

    socket = new WebSocket(getWebSocketUrl("/api/panel/ws"));

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);

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
        

        if (data.type === "verification_update" && data.payload) {
            const payload = data.payload;

            dispatch({
                type: "verifications/patch",
                payload: {
                    session_id: payload.session_id,
                    changes: stripUndefinedEntries({
                        progress_pct: payload.progress_pct,
                        current_step: payload.current_step,
                        status: payload.status,
                        last_activity: payload.last_activity,
                        inconsistencias_count: payload.inconsistencias_count,
                        inconsistencias: payload.inconsistencias,
                        severity_counts: payload.severity_counts,
                        highest_severity: payload.highest_severity,
                        no_cuenta: payload.no_cuenta,
                        siga_url: payload.siga_url,
                    }),
                },
            });
        }
        if (data.type === "inconsistencia_updated" && data.payload) {
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
