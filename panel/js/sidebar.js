import {getConversations} from "./api.js"
import {loadChat} from "./chat.js"
import {navigateTo} from "./app.js" 

export async function loadSidebar(){

    const sessions = await getConversations()

    const list = document.getElementById("conversationList")

    list.innerHTML=""

    sessions.forEach(s=>{

        const item = document.createElement("div")

        item.className="conversation"

        item.innerHTML = `
        <b>${s.phone}</b>
        <br>
        <small>${s.last_message ?? ""}</small>
        `

        item.onclick = ()=>loadChat(s.id)

        list.appendChild(item)

    })
}

export function initSidebar() {
    const toggle = document.getElementById("toggleSidebar");
    const sidebar = document.getElementById("sidebar");

    if (!toggle || !sidebar) return;

    // 🔥 COLAPSO
    toggle.addEventListener("click", () => {
        sidebar.classList.toggle("collapsed");
    });

    // 🔥 NAVEGACIÓN
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", () => {

            const page = item.dataset.page;

            // activar estilo
            document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));
            item.classList.add("active");

            // cambiar contenido
            navigateTo(page);
        });
    });
}