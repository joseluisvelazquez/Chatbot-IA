const API_BASE_URL = "http://localhost:8000/api/panel";

async function apiRequest(endpoint, options = {}) {
    const config = {
        method: "GET",
        headers: {
            "Content-Type": "application/json"
            // "x-api-key": "tu_api_key" // si aplica
        },
        ...options
    };

    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const errorData = await response.json();
            detail = errorData.detail || detail;
        } catch (_) {}
        throw new Error(detail);
    }

    return await response.json();
}

export async function fetchVerifications(status = "") {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return apiRequest(`/verifications${query}`);
}
export async function getConversations() {
    return apiRequest("/conversations");
}

export async function getMessages(sessionId) {
    return apiRequest(`/messages/${sessionId}`);
}

export async function sendMessage(payload) {
    return apiRequest("/messages", {
        method: "POST",
        body: JSON.stringify(payload)
    });
}