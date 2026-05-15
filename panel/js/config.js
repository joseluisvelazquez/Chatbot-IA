const DEV_PANEL_PORTS = new Set(["5500"]);
const DEFAULT_DEV_BACKEND_ORIGIN = "http://localhost:8000";
const SIGA_LOGIN_URL = "https://siga.mxcomp.mx/index.php";

const panelAssetBaseUrl = new URL("../", import.meta.url);
const panelBasePath = panelAssetBaseUrl.pathname.replace(/\/$/, "");

function isStandalonePanelDev() {
    return window.location.protocol === "file:" || DEV_PANEL_PORTS.has(window.location.port);
}

function getBackendOrigin() {
    if (isStandalonePanelDev()) {
        return DEFAULT_DEV_BACKEND_ORIGIN;
    }

    return window.location.origin;
}

export function isLocalPanelEnvironment() {
    return isStandalonePanelDev() || ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

export function getPanelBasePath() {
    return panelBasePath;
}

export function getPanelHomeUrl() {
    return `${window.location.origin}${panelBasePath || "/"}`;
}

export function getPanelAssetUrl(path = "") {
    return new URL(String(path).replace(/^\/+/, ""), `${window.location.origin}${panelBasePath}/`).toString();
}

export function getPanelPageUrl(path = "") {
    return getPanelAssetUrl(path);
}

export function getApiUrl(path = "") {
    return new URL(String(path).replace(/^\/+/, ""), `${getBackendOrigin()}/api/`).toString();
}

export function getAuthUrl(path = "") {
    return new URL(String(path).replace(/^\/+/, ""), `${getBackendOrigin()}/api/auth/`).toString();
}

export function getWebSocketUrl(path = "/api/panel/ws") {
    const url = new URL(path, getBackendOrigin());
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
}

export function getSigaLoginUrl() {
    return SIGA_LOGIN_URL;
}

export function resolveMediaUrl(path = "") {
    if (!path) return "";
    if (/^https?:\/\//i.test(path)) return path;
    return new URL(path, getBackendOrigin()).toString();
}
