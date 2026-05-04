import { renderSessionExpired } from "./app.js"
import { getApiUrl } from "./config.js"

const DEFAULT_TIMEOUT = 15000
const RETRYABLE_METHODS = new Set(["GET"])

export class ApiRequestError extends Error {
    constructor(message, options = {}) {
        super(humanizeApiErrorMessage(message, options))
        this.name = "ApiRequestError"
        this.status = options.status ?? null
        this.payload = options.payload ?? null
        this.isNetworkError = Boolean(options.isNetworkError)
        this.isTimeout = Boolean(options.isTimeout)
    }
}

function normalizeEndpoint(endpoint = "") {
    const value = String(endpoint || "").trim()
    return value.startsWith("/") ? value : `/${value}`
}

function buildRequestConfig(options = {}) {
    const config = {
        method: "GET",
        credentials: "include",
        ...options,
    }

    config.method = String(config.method || "GET").toUpperCase()

    const headers = new Headers(options.headers || {})
    const isFormData = config.body instanceof FormData

    if (!headers.has("Accept")) {
        headers.set("Accept", "application/json")
    }

    if (!isFormData && config.body != null && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json")
    }

    if (isFormData) {
        headers.delete("Content-Type")
    }

    config.headers = headers
    return config
}

async function parseResponse(response) {
    if (response.status === 204) return null

    const contentType = response.headers.get("content-type") || ""

    if (contentType.includes("application/json")) {
        return response.json()
    }

    return response.text()
}

function shouldRetry(method, status) {
    if (!RETRYABLE_METHODS.has(method)) return false
    return [408, 429, 502, 503, 504].includes(Number(status))
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
}

function humanizeApiErrorMessage(message = "", options = {}) {
    const raw = String(message || "").trim()
    const lower = raw.toLowerCase()

    if (options.isTimeout || lower.includes("timeout") || lower.includes("tard")) {
        return "Tiempo de espera agotado"
    }

    if (options.isNetworkError || lower.includes("failed to fetch") || lower.includes("network")) {
        return "No se pudo conectar con el servidor"
    }

    if (lower.includes("siga")) {
        if (lower.includes("fallback")) return "Mostrando datos anteriores"
        return "No se pudo conectar con SIGA"
    }

    if (lower.startsWith("http ") || lower.includes("traceback") || lower.includes("sqlalchemy")) {
        return "No se pudo completar la operacion"
    }

    return raw || "No se pudo completar la operacion"
}

async function fetchWithTimeout(url, config, timeoutMs) {
    const controller = new AbortController()
    const externalSignal = config.signal
    const abortFromExternalSignal = () => {
        controller.abort(externalSignal?.reason)
    }

    if (externalSignal) {
        if (externalSignal.aborted) {
            abortFromExternalSignal()
        } else {
            externalSignal.addEventListener("abort", abortFromExternalSignal, { once: true })
        }
    }

    const timer = setTimeout(() => controller.abort(), timeoutMs)

    try {
        return await fetch(url, {
            ...config,
            signal: controller.signal,
        })
    } finally {
        clearTimeout(timer)
        if (externalSignal) {
            externalSignal.removeEventListener("abort", abortFromExternalSignal)
        }
    }
}

export async function apiRequest(endpoint, options = {}) {
    const config = buildRequestConfig(options)
    const method = config.method
    const url = getApiUrl(normalizeEndpoint(endpoint))
    const timeoutMs = Number(options.timeout || DEFAULT_TIMEOUT)

    let attempts = 0
    const maxAttempts = RETRYABLE_METHODS.has(method) ? 2 : 1

    while (attempts < maxAttempts) {
        attempts++

        try {
            const response = await fetchWithTimeout(url, config, timeoutMs)

            if (!response.ok) {
                let detail = `HTTP ${response.status}`
                let payload = null

                try {
                    const errorData = await parseResponse(response)
                    payload = errorData

                    if (typeof errorData === "string" && errorData.trim()) {
                        detail = errorData
                    } else if (errorData?.detail) {
                        detail = errorData.detail
                    }
                } catch {}

                if (response.status === 401) {
                    renderSessionExpired()

                    throw new ApiRequestError("Sesion expirada", {
                        status: 401,
                        payload,
                    })
                }

                if (response.status === 403) {
                    throw new ApiRequestError(detail || "No autorizado", {
                        status: 403,
                        payload,
                    })
                }

                if (response.status === 409) {
                    throw new ApiRequestError(detail || "Conflicto de operación", {
                        status: 409,
                        payload,
                    })
                }

                if (response.status === 422) {
                    throw new ApiRequestError(detail || "Solicitud inválida", {
                        status: 422,
                        payload,
                    })
                }

                if (response.status === 429) {
                    throw new ApiRequestError(detail || "Demasiadas solicitudes", {
                        status: 429,
                        payload,
                    })
                }

                if (response.status >= 500) {
                    if (shouldRetry(method, response.status) && attempts < maxAttempts) {
                        await delay(600)
                        continue
                    }

                    throw new ApiRequestError(
                        detail || "Error interno del servidor",
                        {
                            status: response.status,
                            payload,
                        }
                    )
                }

                throw new ApiRequestError(detail, {
                    status: response.status,
                    payload,
                })
            }

            return await parseResponse(response)

        } catch (error) {
            if (error instanceof ApiRequestError) {
                throw error
            }

            if (error?.name === "AbortError") {
                const wasExternalAbort = Boolean(options.signal?.aborted)
                throw new ApiRequestError(
                    wasExternalAbort ? "Solicitud cancelada" : "Tiempo de espera agotado",
                    {
                        isTimeout: !wasExternalAbort,
                    }
                )
            }

            if (
                error instanceof TypeError ||
                String(error?.message || "").includes("Failed to fetch")
            ) {
                if (attempts < maxAttempts) {
                    await delay(500)
                    continue
                }

                throw new ApiRequestError(
                    "No se pudo conectar con el servidor",
                    {
                        isNetworkError: true,
                    }
                )
            }

            throw new ApiRequestError(
                error?.message || "Error inesperado",
                { payload: error }
            )
        }
    }
}

/* ===========================
   ENDPOINTS
=========================== */

export const fetchVerifications = (status = "", limit = 500, offset = 0, options = {}) => {
    const params = new URLSearchParams()
    if (status) params.set("status", status)
    params.set("limit", String(limit))
    params.set("offset", String(offset))
    return apiRequest(`/panel/verifications?${params}`, {
        signal: options.signal,
    })
}

export const getVerificationBySession = (sessionId, options = {}) => {
    const params = new URLSearchParams()
    if (options.refreshSiga) {
        params.set("refresh_siga", "true")
    }

    const query = params.toString()
    return apiRequest(`/panel/verifications/${sessionId}${query ? `?${query}` : ""}`, {
        signal: options.signal,
    })
}

export const updateInconsistenciaPanelResolution = (
    inconsistenciaId,
    resolvedByPanel,
    uiId = null
) =>
    apiRequest(`/panel/inconsistencias/${inconsistenciaId}/resolution`, {
        method: "PATCH",
        body: JSON.stringify({
            resolved_by_panel: Boolean(resolvedByPanel),
            ui_id: uiId,
        }),
    })

export const getConversations = (limit = 100, offset = 0, options = {}) =>
    apiRequest(`/panel/conversations?limit=${limit}&offset=${offset}`, {
        signal: options.signal,
    })

export const getAvailableManagers = (options = {}) =>
    apiRequest("/panel/gestores-disponibles", {
        signal: options.signal,
    })

export const assignConversationManager = (sessionId, username, reason = null) =>
    apiRequest(`/panel/chats/${sessionId}/assign-manager`, {
        method: "POST",
        body: JSON.stringify({ username, reason }),
    })

export const syncInactiveManagerAssignments = () =>
    apiRequest("/panel/maintenance/reassign-inactive-managers", {
        method: "POST",
    })

export const getMessages = (sessionId, limit = 30, offset = 0, options = {}) =>
    apiRequest(`/panel/messages/${sessionId}?limit=${limit}&offset=${offset}`, {
        signal: options.signal,
    })

export const markConversationRead = (sessionId, options = {}) =>
    apiRequest(`/panel/conversations/${sessionId}/read`, {
        method: "POST",
        signal: options.signal,
    })

export const sendMessage = (payload) =>
    apiRequest("/panel/messages", {
        method: "POST",
        body: JSON.stringify(payload),
    })

export const sendFileMessage = (payload) =>
    apiRequest("/panel/messages/file", {
        method: "POST",
        body: JSON.stringify(payload),
    })

export const takeConversation = (sessionId, targetRole = null) =>
    apiRequest(`/panel/conversations/${sessionId}/take`, {
        method: "POST",
        body: JSON.stringify({ target_role: targetRole }),
    })

export const releaseConversation = (sessionId, reason = null) =>
    apiRequest(`/panel/conversations/${sessionId}/release`, {
        method: "POST",
        body: JSON.stringify({ reason }),
    })

export const transferConversation = (sessionId, destination, options = {}) =>
    apiRequest(`/panel/conversations/${sessionId}/transfer`, {
        method: "POST",
        body: JSON.stringify({
            destination,
            destination_user_id: options.destination_user_id || null,
            reason: options.reason || null,
        }),
    })

export const returnConversation = (sessionId, destination, options = {}) =>
    apiRequest(`/panel/conversations/${sessionId}/return/${destination}`, {
        method: "POST",
        body: JSON.stringify({
            destination_user_id: options.destination_user_id || null,
            reason: options.reason || null,
        }),
    })

export const closeTechnicalIncident = (sessionId, options = {}) =>
    apiRequest(`/panel/conversations/${sessionId}/technical/close`, {
        method: "POST",
        body: JSON.stringify({
            resolution: options.resolution || null,
            return_action:
                options.return_action || "return_to_original_gestor",
            fallback_destination:
                options.fallback_destination || "jefe_operativo",
        }),
    })

export const getFeatureFlags = () =>
    apiRequest("/panel/feature-flags")

export const updateFeatureFlag = (name, enabled, description = null) =>
    apiRequest(`/panel/feature-flags/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled, description }),
    })

export const uploadPanelFile = (file) => {
    const formData = new FormData()
    formData.append("file", file)

    return apiRequest("/panel/upload", {
        method: "POST",
        body: formData,
    })
}

export const getDashboardSummary = () =>
    apiRequest("/panel/dashboard/summary")

export const getDashboardFunnel = (days = 7) =>
    apiRequest(`/panel/dashboard/funnel?days=${days}`)

export const getDashboardStateTimes = (days = 7) =>
    apiRequest(`/panel/dashboard/state-times?days=${days}`)

export const getSigaBridgeMetrics = () =>
    apiRequest("/panel/siga-bridge/metrics")
