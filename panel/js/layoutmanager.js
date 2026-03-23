// layoutManager.js
let currentLayout = "default";

export function setLayout(layout) {
    currentLayout = layout;

    const app = document.getElementById("app");

    app.classList.remove("layout-default", "layout-chat");
    app.classList.add(`layout-${layout}`);
}