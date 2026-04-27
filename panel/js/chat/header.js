import { hasPendingAction, statusMeta } from "./permissions.js"
import { escapeHtml } from "./utils.js"

const ACTION_DEFINITIONS = [
    {
        id: "btnTakeChat",
        label: "Tomar chat",
        icon: "hand",
        tone: "default",
        visible: (session) => Boolean(session?.can_take),
        handler: "onTakeChat",
    },
    {
        id: "btnAssignManager",
        label: "Asignar gestor",
        icon: "user-plus",
        tone: "default",
        visible: (session) => Boolean(session?.can_assign_manager),
        handler: "onAssignManager",
    },
    {
        id: "btnSendSupport",
        label: "Enviar a soporte",
        icon: "wrench",
        tone: "default",
        visible: (session) => Boolean(session?.can_transfer_to_support),
        handler: "onTransferToSupport",
    },
    {
        id: "btnReturnGestor",
        label: "Regresar a gestor",
        icon: "undo-2",
        tone: "default",
        visible: (session) => Boolean(session?.can_return_to_gestor),
        handler: "onReturnToGestor",
    },
    {
        id: "btnReturnAssistant",
        label: "Regresar a assistant",
        icon: "sparkles",
        tone: "default",
        visible: (session) => Boolean(session?.can_return_to_assistant),
        handler: "onReturnToAssistant",
    },
    {
        id: "btnCloseSupport",
        label: "Cerrar soporte",
        icon: "check-check",
        tone: "success",
        visible: (session) => Boolean(session?.can_close_support),
        handler: "onCloseSupport",
    },
]

function bindAction(id, handler) {
    const element = document.getElementById(id)
    if (!element || typeof handler !== "function") return
    element.onclick = handler
}

function badgeClassNames() {
    return "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold"
}

function actionToneClasses(tone = "default") {
    if (tone === "success") {
        return [
            "border-emerald-200 bg-emerald-50 text-emerald-700",
            "hover:bg-emerald-100 hover:border-emerald-300",
            "focus-visible:ring-emerald-500",
            "dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:bg-emerald-500/20",
        ].join(" ")
    }

    if (tone === "danger") {
        return [
            "border-rose-200 bg-rose-50 text-rose-700",
            "hover:bg-rose-100 hover:border-rose-300",
            "focus-visible:ring-rose-500",
            "dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300 dark:hover:bg-rose-500/20",
        ].join(" ")
    }

    return [
        "border-slate-200 bg-white text-slate-700",
        "hover:bg-slate-100 hover:border-slate-300",
        "focus-visible:ring-sky-500",
        "dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700",
    ].join(" ")
}

function buildTooltip(id, label) {
    return `
        <span
            id="${id}"
            role="tooltip"
            class="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-max max-w-[12rem] -translate-x-1/2 rounded-md bg-slate-950 px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition group-hover:opacity-100 group-focus-within:opacity-100 dark:bg-slate-100 dark:text-slate-900"
        >
            ${escapeHtml(label)}
        </span>
    `
}

function buildActionButton(definition) {
    const tooltipId = `${definition.id}Tooltip`

    return `
        <div class="group relative">
            <button
                id="${definition.id}"
                type="button"
                class="inline-flex h-10 w-10 items-center justify-center rounded-xl border transition focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 ${actionToneClasses(definition.tone)}"
                aria-label="${escapeHtml(definition.label)}"
                aria-describedby="${tooltipId}"
            >
                <i data-lucide="${definition.icon}" class="h-4 w-4"></i>
                <span class="sr-only">${escapeHtml(definition.label)}</span>
            </button>
            ${buildTooltip(tooltipId, definition.label)}
        </div>
    `
}

function buildBadge(className, label) {
    return `
        <span class="${badgeClassNames()} ${className}">
            ${escapeHtml(label)}
        </span>
    `
}

export function renderHeader({
    session,
    displayName,
    phone,
    onBack,
    onTakeChat,
    onTransferToSupport,
    onReturnToAssistant,
    onReturnToGestor,
    onAssignManager,
    onCloseSupport,
}) {
    const header = document.getElementById("chatHeader")
    if (!header) return

    if (!session) {
        header.innerHTML = `
            <div class="text-sm text-gray-400">
                Selecciona una conversacion
            </div>
        `
        return
    }

    const meta = statusMeta(session.status_operativo)
    const safeName = escapeHtml(
        displayName ||
        session.display_name ||
        session.name ||
        phone ||
        "Cliente sin nombre"
    )
    const safePhone = escapeHtml(phone || session.phone || "")
    const ownerLabel = escapeHtml(
        session.assigned_user_id ||
        session.assigned_role ||
        session.owner_type ||
        "Sin asignar"
    )

    const actionHandlers = {
        onTakeChat,
        onTransferToSupport,
        onReturnToAssistant,
        onReturnToGestor,
        onAssignManager,
        onCloseSupport,
    }

    const actionButtons = ACTION_DEFINITIONS
        .filter((definition) => definition.visible(session))
        .map((definition) => buildActionButton(definition))
        .join("")

    const badges = [
        buildBadge(meta.className, meta.label),
    ]

    if (hasPendingAction(session)) {
        badges.push(
            buildBadge(
                "border-amber-300 bg-amber-500/15 text-amber-700 dark:border-amber-500/30 dark:text-amber-300",
                "Accion requerida"
            )
        )
    }

    if (session.test_mode) {
        badges.push(
            buildBadge(
                "border-fuchsia-300 bg-fuchsia-500/15 text-fuchsia-700 dark:border-fuchsia-500/30 dark:text-fuchsia-300",
                "TEST"
            )
        )
    }

    const backButton = typeof onBack === "function"
        ? `
            <button
                id="btnChatBack"
                type="button"
                class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-700 transition hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 dark:focus-visible:ring-offset-slate-900 md:hidden"
                aria-label="Volver a conversaciones"
            >
                <i data-lucide="arrow-left" class="h-4 w-4"></i>
                <span class="sr-only">Volver a conversaciones</span>
            </button>
        `
        : ""

    const actionRow = actionButtons
        ? `
            <div class="flex flex-wrap items-center gap-2">
                ${actionButtons}
            </div>
        `
        : ""

    header.innerHTML = `
        <div class="flex w-full flex-col gap-3">
            <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div class="min-w-0 space-y-2">
                    <div class="flex min-w-0 items-start gap-3">
                        ${backButton}
                        <div class="min-w-0">
                            <div class="truncate text-base font-semibold text-slate-900 dark:text-white">
                                ${safeName}
                            </div>
                            <div class="truncate text-xs text-slate-500 dark:text-slate-400">
                                ${safePhone || "Sin telefono"}
                            </div>
                        </div>
                    </div>

                    <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                        <span class="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                            Owner
                        </span>
                        <span class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                            ${ownerLabel}
                        </span>
                    </div>
                </div>

                <div class="flex flex-col gap-2 lg:min-w-[12rem] lg:items-end">
                    <div class="flex flex-wrap items-center gap-2 lg:justify-end">
                        ${badges.join("")}
                    </div>
                    ${actionRow}
                </div>
            </div>
        </div>
    `

    if (typeof onBack === "function") {
        bindAction("btnChatBack", onBack)
    }

    ACTION_DEFINITIONS.forEach((definition) => {
        bindAction(definition.id, actionHandlers[definition.handler])
    })

    if (window.lucide) {
        window.lucide.createIcons()
    }
}
