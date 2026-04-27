import { formatDateSeparator } from "./utils.js"

export function isUserAtBottom(container) {
    const threshold = 60
    return container.scrollHeight - container.scrollTop - container.clientHeight < threshold
}

export function getLastRenderedDate(list) {
    const nodes = list.querySelectorAll("[data-message-date]")
    if (!nodes.length) return null
    return nodes[nodes.length - 1].dataset.messageDate
}

export function insertDateSeparator(list, dateString) {
    const separator = document.createElement("div")
    separator.className = "flex justify-center my-2"
    separator.dataset.separatorType = "date"

    separator.innerHTML = `
        <div class="text-xs px-3 py-1 rounded-full bg-gray-300 dark:bg-slate-700 text-gray-700 dark:text-gray-200">
            ${formatDateSeparator(dateString)}
        </div>
    `

    list.appendChild(separator)
}

export function ensureNewMessagesSeparator(list) {
    if (document.getElementById("newMessagesSeparator")) return

    const separator = document.createElement("div")
    separator.id = "newMessagesSeparator"
    separator.className = "flex justify-center my-2"
    separator.dataset.separatorType = "new"

    separator.innerHTML = `
        <div class="text-xs px-3 py-1 rounded-full bg-blue-500 text-white">
            Nuevos mensajes
        </div>
    `

    list.appendChild(separator)
}

export function removeNewMessagesSeparator() {
    const separator = document.getElementById("newMessagesSeparator")
    if (separator) separator.remove()
}
