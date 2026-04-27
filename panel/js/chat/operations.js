export function createConversationOperationHandlers({
    api,
    dispatch,
    getCurrentSessionId,
    getState,
    setSelectedSession,
    setCurrentSessionId,
    setLastLoadedSessionId,
    showMobileConversationList,
    showToast,
    renderSelectedConversation,
    renderSidebar,
}) {
    let isChatOperationInFlight = false

    async function applyConversationOperation(operation) {
        const currentSessionId = getCurrentSessionId()
        if (!currentSessionId || isChatOperationInFlight) return

        isChatOperationInFlight = true

        const sessionId = Number(currentSessionId)
        const previousState = getState()
        const previousSession = previousState.conversations.byId[sessionId] || null

        try {
            const updated = await operation(sessionId)

            if (!updated || typeof updated !== "object") {
                throw new Error("Respuesta invalida del servidor")
            }

            if (updated.id) {
                dispatch({
                    type: "conversations/upsert",
                    payload: updated,
                })
            }

            const nextState = getState()
            const visibleSession =
                nextState.conversations.byId[sessionId] ||
                (updated.id ? updated : null)

            if (!visibleSession || !nextState.conversations.byId[sessionId]) {
                setCurrentSessionId(null)
                setLastLoadedSessionId(null)
                setSelectedSession(null)
                localStorage.removeItem("lastSession")
                showMobileConversationList()

                const header = document.getElementById("chatHeader")
                const list = document.getElementById("messages")

                if (header) {
                    header.innerHTML = `
                        <div class="text-sm text-gray-400">
                            La conversacion ya no esta disponible para tu usuario
                        </div>
                    `
                }

                if (list) {
                    list.innerHTML = ""
                }

                showToast(
                    "La conversacion cambio de owner y ya no esta visible para tu usuario",
                    "info"
                )
                return
            }

            renderSelectedConversation(visibleSession)
            renderSidebar(nextState)

            if (previousSession?.status_operativo !== visibleSession.status_operativo) {
                renderSelectedConversation(visibleSession)
            }

            showToast("Operacion realizada correctamente", "success")
        } catch (error) {
            console.error("Operacion de chat fallida:", error)

            const status = Number(error?.status || 0)

            if (status === 403) {
                showToast(
                    error.message || "No tienes permisos para operar este chat",
                    "error"
                )
                return
            }

            if (status === 404) {
                dispatch({
                    type: "conversations/remove",
                    payload: { session_id: sessionId },
                })

                setCurrentSessionId(null)
                setLastLoadedSessionId(null)
                setSelectedSession(null)
                localStorage.removeItem("lastSession")
                showMobileConversationList()

                const header = document.getElementById("chatHeader")
                const list = document.getElementById("messages")

                if (header) {
                    header.innerHTML = `
                        <div class="text-sm text-gray-400">
                            La conversacion ya no existe o ya no esta disponible
                        </div>
                    `
                }

                if (list) {
                    list.innerHTML = ""
                }

                showToast(
                    error.message || "La conversacion ya no existe o ya no esta disponible",
                    "error"
                )
                return
            }

            if (status === 409) {
                showToast(
                    error.message || "La conversacion cambio de estado. Recarga visual aplicada.",
                    "info"
                )

                try {
                    const sessions = await api.getConversations()
                    dispatch({
                        type: "conversations/loaded",
                        payload: sessions,
                    })
                } catch (refreshError) {
                    console.error("No se pudo refrescar conversaciones tras conflicto:", refreshError)
                }

                return
            }

            showToast(
                error.message || "No se pudo actualizar la conversacion",
                "error"
            )
        } finally {
            isChatOperationInFlight = false
        }
    }

    return {
        applyConversationOperation,
        takeCurrentChat() {
            return applyConversationOperation((sessionId) => api.takeConversation(sessionId))
        },
        transferCurrentChat(destination) {
            return applyConversationOperation((sessionId) =>
                api.transferConversation(sessionId, destination)
            )
        },
        returnCurrentChat(destination) {
            return applyConversationOperation((sessionId) =>
                api.returnConversation(sessionId, destination)
            )
        },
        closeSupportToOriginalGestor() {
            return applyConversationOperation((sessionId) =>
                api.closeTechnicalIncident(sessionId, {
                    return_action: "return_to_original_gestor",
                    fallback_destination: "jefe_operativo",
                })
            )
        },
        closeSupportToAssistant() {
            return applyConversationOperation((sessionId) =>
                api.closeTechnicalIncident(sessionId, {
                    return_action: "assistant_active",
                    fallback_destination: "jefe_operativo",
                })
            )
        },
        closeSupportToQueue() {
            return applyConversationOperation((sessionId) =>
                api.closeTechnicalIncident(sessionId, {
                    return_action: "cola_general",
                    fallback_destination: "jefe_operativo",
                })
            )
        },
    }
}
