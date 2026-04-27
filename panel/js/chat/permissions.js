export const STATUS_META = {
    unassigned: { label: "Sin dueno", className: "bg-gray-200 text-gray-700 dark:bg-slate-700 dark:text-slate-200" },
    assistant_active: { label: "Assistant", className: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200" },
    assigned_gestor: { label: "Gestor", className: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200" },
    assigned_soporte: { label: "Soporte", className: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-200" },
    waiting_customer: { label: "Esperando", className: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200" },
    escalated: { label: "Escalado", className: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200" },
    closed: { label: "Cerrado", className: "bg-slate-800 text-white dark:bg-black dark:text-slate-200" },
}

export function canOperateSelected(session) {
    return Boolean(session?.can_reply)
}

export function canActOnConversation(session) {
    if (!session) return false

    return Boolean(
        session.can_reply ||
        session.can_take ||
        session.can_assign_manager ||
        session.can_transfer_to_support ||
        session.can_return_to_gestor ||
        session.can_return_to_assistant ||
        session.can_escalate ||
        session.can_close_support
    )
}

export function canActOnSelected(session) {
    return canActOnConversation(session)
}

export function canAssignManager(session) {
    return Boolean(session?.can_assign_manager)
}

export function hasPendingAction(session) {
    return Boolean(session?.has_pending_action)
}

export function isSupportConversation(session) {
    return session?.status_operativo === "assigned_soporte"
}

export function isEscalatedConversation(session) {
    return session?.status_operativo === "escalated"
}

export function isAssistantConversation(session) {
    return session?.status_operativo === "assistant_active"
}

export function isAssignedGestorConversation(session) {
    return session?.status_operativo === "assigned_gestor"
}

export function statusMeta(status) {
    return STATUS_META[status] || STATUS_META.unassigned
}

export function shouldShowActionBadge(session) {
    return hasPendingAction(session)
}
