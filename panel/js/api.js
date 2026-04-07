
import { renderSessionExpired, renderNetworkError } from "./app.js"
const API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:8000/api`


export async function apiRequest(endpoint, options = {}) {
    const config = {
        method: "GET",
        headers: {
            "Content-Type": "application/json"
        },
        credentials: "include",
        ...options
    };

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

        if (!response.ok) {
            let detail = `HTTP ${response.status}`;

            try {
                const errorData = await response.json();
                detail = errorData.detail || detail;
            } catch (_) {}

            //  MANEJO PRO
            if (response.status === 401) {
                renderSessionExpired()
                throw new Error("Sesión expirada")
            }

            if (response.status === 403) {
                throw new Error("No autorizado")
            }

            throw new Error(detail);
        }

        return await response.json();

    } catch (error) {
        //  NETWORK ERROR
        if (error.message.includes("Failed to fetch")) {
            renderNetworkError()
        }

        throw error;
    }
}

export async function fetchVerifications(status = "") {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return apiRequest(`/panel/verifications${query}`);
}
export async function getConversations() {
    return apiRequest("/panel/conversations");
}

export async function getMessages(sessionId) {
    return apiRequest(`/panel/messages/${sessionId}`);
}

export async function sendMessage(payload) {
    return apiRequest("/panel/messages", {
        method: "POST",
        body: JSON.stringify(payload)
    });
}
// --------------------
// DASHBOARD
// --------------------

export async function getDashboardSummary() {
    return apiRequest("/panel/dashboard/summary");
}

export async function getDashboardFunnel(days = 7) {
    return apiRequest(`/panel/dashboard/funnel?days=${days}`);
}

export async function getDashboardStateTimes(days = 7) {
    return apiRequest(`/panel/dashboard/state-times?days=${days}`);
}
export async function getAuthMe() {
    return apiRequest("/auth/me")
}
