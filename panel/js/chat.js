import {getMessages,sendMessage} from "./api.js"

let currentSession = null

export async function loadChat(sessionId){

    currentSession = sessionId

    const messages = await getMessages(sessionId)

    const box = document.getElementById("messages")
    box.innerHTML=""

    messages.forEach(m => {

        const div = document.createElement("div")

        div.className = m.direction

        div.innerText = m.content

        box.appendChild(div)

    })
}

export async function send(){

    const input = document.getElementById("messageInput")

    const text = input.value

    if(!text)return

    await sendMessage(currentSession,text)

    input.value=""

    loadChat(currentSession)

}