const API_URL = "http://localhost:5500";

async function apiRequest(endpoint, options = {}) {
    try {
        const res = await fetch(`${API_URL}${endpoint}`, {
            headers: {
                "Content-Type": "application/json"
            },
            ...options
        });

        if (!res.ok) {
            throw new Error(`Error ${res.status}`);
        }

        return await res.json();

    } catch (error) {
        console.error("API ERROR:", error);
        return null;
    }
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