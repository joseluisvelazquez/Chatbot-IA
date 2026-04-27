const BUTTON_LABELS = {
    MENU_VERIFICACION: "Menu de verificacion",
    FOLIO_SI: "Confirmo folio",
    NOMBRE_SI: "Confirmo nombre",
    DOM_SI: "Confirmo domicilio",
    FECHA_SI: "Confirmo fecha",
    PROD_SI: "Confirmo producto",
    PRODESTADOSI: "Producto en buen estado",
    PAGO_SI: "Confirmo pago",
    PAGOS_OK: "Entendio pagos",
    PLAN3_OK: "Acepto plan 3 meses",
    PLANES_OK: "Reviso planes",
    BEN_OK: "Confirmo beneficios",
}

function getToastContainer() {
    let container = document.getElementById("chatToastContainer")
    if (container) return container

    container = document.createElement("div")
    container.id = "chatToastContainer"
    container.className = "fixed right-4 top-4 z-[70] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2"
    document.body.appendChild(container)
    return container
}

export function showToast(message, tone = "info") {
    const container = getToastContainer()
    const toast = document.createElement("div")
    const tones = {
        success: "bg-emerald-600 text-white",
        error: "bg-red-600 text-white",
        info: "bg-slate-900 text-white",
    }

    toast.className = `rounded-lg px-3 py-2 text-sm shadow-lg ${tones[tone] || tones.info}`
    toast.textContent = message
    container.appendChild(toast)

    window.setTimeout(() => {
        toast.remove()
        if (!container.childElementCount) {
            container.remove()
        }
    }, 3000)
}

export function escapeHtml(value) {
    if (value == null) return ""

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
}

export function formatTime(dateString) {
    const date = new Date(dateString)
    return date.toLocaleTimeString("es-MX", {
        hour: "2-digit",
        minute: "2-digit",
    })
}

export function formatDateSeparator(dateString) {
    const date = new Date(dateString)
    const today = new Date()

    const isToday = date.toDateString() === today.toDateString()

    const yesterday = new Date()
    yesterday.setDate(today.getDate() - 1)

    const isYesterday = date.toDateString() === yesterday.toDateString()

    if (isToday) return "Hoy"
    if (isYesterday) return "Ayer"

    return date.toLocaleDateString("es-MX", {
        weekday: "long",
        day: "numeric",
        month: "long",
    })
}

export function formatWhatsAppText(text) {
    if (!text) return ""

    return escapeHtml(text)
        .replace(/\n/g, "<br>")
        .replace(/\*(.*?)\*/g, "<b>$1</b>")
        .replace(/_(.*?)_/g, "<i>$1</i>")
        .replace(/~(.*?)~/g, "<s>$1</s>")
        .replace(/`(.*?)`/g, "<code>$1</code>")
}

export function formatButtonMessage(text) {
    if (!text) return text

    const match = text.match(/\[BOTON\]\s*(.+)/)
    if (!match) return text

    const key = match[1].trim()
    let label = BUTTON_LABELS[key] || key.replaceAll("_", " ").toLowerCase()

    if (!BUTTON_LABELS[key]) {
        if (key.endsWith("_SI")) {
            label = `Confirmo ${key.replace("_SI", "").toLowerCase()}`
        } else if (key.endsWith("_NO")) {
            label = `Rechazo ${key.replace("_NO", "").toLowerCase()}`
        } else if (key.endsWith("_DUDA")) {
            label = "Tiene dudas"
        } else if (key.endsWith("_OK")) {
            label = "Confirmo"
        }
    }

    return `
        <span class="
            inline-flex items-center gap-1
            bg-gray-100 dark:bg-slate-500
            text-gray-800 dark:text-white
            border border-gray-200 dark:border-slate-400
            px-3 py-1 rounded-md text-xs font-medium
            shadow-none dark:shadow-sm
        ">
            ${escapeHtml(label)}
        </span>
    `
}
