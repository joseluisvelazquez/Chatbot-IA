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
    separator.className = "sticky top-2 z-10 flex justify-center my-3 pointer-events-none"
    separator.dataset.separatorType = "date"

    separator.innerHTML = `
        <div class="rounded-full border border-slate-200 bg-white/90 px-3 py-1 text-[11px] font-semibold text-slate-500 shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/90 dark:text-slate-300">
            ${formatDateSeparator(dateString)}
        </div>
    `

    list.appendChild(separator)
}

export function ensureNewMessagesSeparator(list) {
    if (document.getElementById("newMessagesSeparator")) return

    const separator = document.createElement("div")
    separator.id = "newMessagesSeparator"
    separator.className = "flex items-center gap-3 my-4"
    separator.dataset.separatorType = "new"

    separator.innerHTML = `
        <div class="h-px flex-1 bg-blue-200 dark:bg-blue-900"></div>
        <div class="rounded-full bg-blue-600 px-3 py-1 text-[11px] font-semibold text-white shadow-sm">
            Nuevos mensajes
        </div>
        <div class="h-px flex-1 bg-blue-200 dark:bg-blue-900"></div>
    `

    list.appendChild(separator)
}

export function removeNewMessagesSeparator() {
    const separator = document.getElementById("newMessagesSeparator")
    if (separator) separator.remove()
}
