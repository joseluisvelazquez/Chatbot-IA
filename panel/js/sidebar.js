import {getConversations} from "./api.js"
import {loadChat} from "./chat.js"
import {navigateTo} from "./app.js" 

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


export function initSidebar(activePage = "") {
    const toggle = document.getElementById("toggleSidebar");
    const sidebar = document.getElementById("sidebar");

    if (toggle && sidebar) {
        toggle.onclick = () => {
            sidebar.classList.toggle("collapsed");
        };
    }

    document.querySelectorAll("#sidebar .nav-item").forEach(item => {
        const page = item.dataset.page || "";

        item.classList.toggle("active", page === activePage);

        item.onclick = () => {
            document.querySelectorAll("#sidebar .nav-item")
                .forEach(i => i.classList.remove("active"));

            item.classList.add("active");
            navigateTo(page);
        };
    });
}