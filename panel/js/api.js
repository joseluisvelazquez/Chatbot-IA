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

export async function fetchCollections(filters = {}, limit = 25, offset = 0, options = {}) {
    const params = new URLSearchParams();

    const map = {
        no_cuenta: "no_cuenta",
        cuenta: "cuenta",
        folio: "folio",
        phone: "phone",
        telefono: "telefono",
        name: "name",
        nombre: "nombre",
        cliente: "cliente",
        status: "status",
        classification: "classification",
        gestor: "gestor",
        date_from: "date_from",
        date_to: "date_to",
    };

    Object.entries(map).forEach(([key, param]) => {
        const value = filters?.[key];
        if (value !== undefined && value !== null && String(value).trim()) {
            params.set(param, String(value).trim());
        }
    });

    ["overdue_only", "paid_only", "include_paid", "active_only"].forEach((key) => {
        if (filters?.[key]) {
            params.set(key, "true");
        }
    });

    params.set("limit", String(limit));
    params.set("offset", String(offset));

    return apiRequest(`/panel/collections?${params.toString()}`, {
        signal: options.signal,
    });
}

export async function fetchCollectionManagers(options = {}) {
    const params = new URLSearchParams();
    const limit = Number(options.limit || 100);
    if (options.search) params.set("search", String(options.search).trim());
    params.set("limit", String(Math.max(1, Math.min(200, limit))));

    return apiRequest(`/panel/collections/managers?${params.toString()}`, {
        signal: options.signal,
    });
}

function includePaidQuery(options = {}) {
    const params = new URLSearchParams();
    if (options.includePaid) params.set("include_paid", "true");
    const query = params.toString();
    return query ? `?${query}` : "";
}

export async function getCollectionByAccount(noCuenta, options = {}) {
    return apiRequest(`/panel/collections/${encodeURIComponent(noCuenta)}${includePaidQuery(options)}`);
}

export async function getCollectionPayments(noCuenta, options = {}) {
    return apiRequest(`/panel/collections/${encodeURIComponent(noCuenta)}/payments${includePaidQuery(options)}`);
}

export async function refreshCollectionAccount(noCuenta, options = {}) {
    return apiRequest(`/panel/collections/${encodeURIComponent(noCuenta)}/refresh${includePaidQuery(options)}`, {
        method: "POST",
    });
}

export async function getVerificationBySession(sessionId, options = {}) {
    const params = new URLSearchParams();

    if (options.refreshSiga) {
        params.set("refresh_siga", "true");
    }

    const query = params.toString();
    return apiRequest(`/panel/verifications/${sessionId}${query ? `?${query}` : ""}`);
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

export async function resumeBotControlApi(sessionId) {
    return apiRequest(`/panel/conversations/${sessionId}/resume-bot`, {
        method: "POST",
    });
}

export async function verifyByCallApi(sessionId) {
    return apiRequest(`/panel/conversations/${sessionId}/verify-by-call`, {
        method: "POST",
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

export async function getSigaBridgeMetrics() {
    return apiRequest("/panel/siga-bridge/metrics");
}
