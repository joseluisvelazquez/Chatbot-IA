import { getConversations } from "./api.js"
import { loadChat } from "./chat.js"

export async function loadSidebar(){

    const sessions = await getConversations()

    const list = document.getElementById("conversationList")

    list.innerHTML = ""

    sessions.forEach(s => {

        const item = document.createElement("div")

        item.className = "conversation"

        item.innerHTML = `
        <b>${s.phone}</b>
        <br>
        <small>${s.last_message_at ?? ""}</small>
        `

        item.onclick = () => loadChat(s.id)

        list.appendChild(item)

    })
}