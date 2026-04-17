import { renderNetworkError, renderSessionExpired } from "./app.js";
import { getApiUrl } from "./config.js";

function buildRequestConfig(options = {}) {
    const config = {
        method: "GET",
        credentials: "include",
        ...options,
    };

    const headers = new Headers(options.headers || {});
    const isFormData = config.body instanceof FormData;

    if (!headers.has("Accept")) {
        headers.set("Accept", "application/json");
    }

    if (!isFormData && config.body != null && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }

    if (isFormData) {
        headers.delete("Content-Type");
    }

    config.headers = headers;
    return config;
}

async function parseResponse(response) {
    if (response.status === 204) {
        return null;
    }

    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
        return response.json();
    }

    return response.text();
}

export async function apiRequest(endpoint, options = {}) {
    const config = buildRequestConfig(options);

    try {
        const response = await fetch(getApiUrl(endpoint), config);

        if (!response.ok) {
            let detail = `HTTP ${response.status}`;

            try {
                const errorData = await parseResponse(response);

                if (typeof errorData === "string" && errorData.trim()) {
                    detail = errorData;
                } else if (errorData?.detail) {
                    detail = errorData.detail;
                }
            } catch (_) {}

            if (response.status === 401) {
                renderSessionExpired();
                throw new Error("Sesion expirada");
            }

            if (response.status === 403) {
                throw new Error("No autorizado");
            }

            throw new Error(detail);
        }

        return await parseResponse(response);
    } catch (error) {
        if (error instanceof TypeError || error?.message?.includes("Failed to fetch")) {
            renderNetworkError();
        }

        throw error;
    }
}

export async function fetchVerifications(status = "", limit = 500, offset = 0) {
    const params = new URLSearchParams();

    if (status) params.set("status", status);
    params.set("limit", String(limit));
    params.set("offset", String(offset));

    return apiRequest(`/panel/verifications?${params.toString()}`);
}

export async function getVerificationBySession(sessionId) {
    return apiRequest(`/panel/verifications/${sessionId}`);
}

export async function updateInconsistenciaPanelResolution(inconsistenciaId, resolvedByPanel, uiId = null) {
    return apiRequest(`/panel/inconsistencias/${inconsistenciaId}/resolution`, {
        method: "PATCH",
        body: JSON.stringify({
            resolved_by_panel: Boolean(resolvedByPanel),
            ui_id: uiId,
        }),
    });
}

export async function getConversations(limit = 500, offset = 0) {
    return apiRequest(`/panel/conversations?limit=${limit}&offset=${offset}`);
}

export async function getMessages(sessionId, limit = 30, offset = 0) {
    return apiRequest(`/panel/messages/${sessionId}?limit=${limit}&offset=${offset}`);
}

export async function markConversationRead(sessionId) {
    return apiRequest(`/panel/conversations/${sessionId}/read`, {
        method: "POST",
    });
}

export async function sendMessage(payload) {
    return apiRequest("/panel/messages", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function sendFileMessage(payload) {
    return apiRequest("/panel/messages/file", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export async function uploadPanelFile(file) {
    const formData = new FormData();
    formData.append("file", file);

    return apiRequest("/panel/upload", {
        method: "POST",
        body: formData,
    });
}

export async function getDashboardSummary() {
    return apiRequest("/panel/dashboard/summary");
}

export async function getDashboardFunnel(days = 7) {
    return apiRequest(`/panel/dashboard/funnel?days=${days}`);
}

export async function getDashboardStateTimes(days = 7) {
    return apiRequest(`/panel/dashboard/state-times?days=${days}`);
}
