const API_BASE = "/api/panel"

export async function getConversations(){
    const res = await fetch(`${API_BASE}/conversations`)
    return await res.json()
}

export async function getMessages(sessionId){
    const res = await fetch(`${API_BASE}/messages/${sessionId}`)
    return await res.json()
}

export async function sendMessage(sessionId,message){

    const res = await fetch(`${API_BASE}/send`,{
        method:"POST",
        headers:{
            "Content-Type":"application/json"
        },
        body:JSON.stringify({
            session_id:sessionId,
            message:message
        })
    })

    return await res.json()
}