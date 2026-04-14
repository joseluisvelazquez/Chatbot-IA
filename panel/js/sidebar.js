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
            sidebar.classList.toggle("w-64");
            sidebar.classList.toggle("w-20");

            sidebar.querySelectorAll("span").forEach((el) => {
                el.classList.toggle("hidden");
            });
        };
    }

    document.querySelectorAll("#sidebar .nav-item").forEach(item => {
        const page = item.dataset.page || "";
        const isActive = page === activePage;

        item.classList.remove(
            "bg-blue-500",
            "text-white",
            "dark:bg-blue-600"
        );

        if (isActive) {
            item.classList.add("bg-blue-500", "text-white", "dark:bg-blue-600");
        }

        item.onclick = () => {
            navigateTo(page);
        };
    });
}