export async function uploadFile(file) {
    const formData = new FormData()
    formData.append("file", file)

    const res = await fetch("/api/panel/upload", {
        method: "POST",
        body: formData
    })

    if (!res.ok) {
        throw new Error("Error subiendo archivo")
    }

    return await res.json()
}

export async function sendMedia(sessionId, data) {
    const res = await fetch("/api/panel/send-media", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            session_id: sessionId,
            ...data
        })
    })

    if (!res.ok) {
        throw new Error("Error enviando media")
    }

    return await res.json()
}