let currentLayout = "default";

export function setLayout(layout = "default") {
    currentLayout = layout;

    const app = document.getElementById("app");
    const sidebar = document.getElementById("sidebar");
    const content = document.getElementById("content");

    if (!app || !sidebar || !content) return;

    // reset clases globales
    app.classList.remove("layout-default", "layout-chat");
    app.classList.add(layout === "chat" ? "layout-chat" : "layout-default");

    // reset inline styles peligrosos
    content.className = "";
    content.removeAttribute("style");

    sidebar.className = "";
    sidebar.removeAttribute("style");

    if (layout === "chat") {
        sidebar.className = "hidden";

        content.className =
            "flex-1 h-full overflow-hidden min-w-0 min-h-0";

        content.style.padding = "0";
        content.style.height = "100%";
        content.style.display = "flex";
        content.style.flexDirection = "column";

        return;
    }

    sidebar.className =
        "hidden md:block md:w-64 bg-white dark:bg-slate-800 border-r border-gray-200 dark:border-slate-700 transition-all";

    content.className =
        "flex-1 overflow-y-auto min-w-0 min-h-0 p-4 md:p-6 bg-gray-100 dark:bg-slate-900";
}

export function getCurrentLayout() {
    return currentLayout;
}
