async function loadComponent(id, path) {
    const res = await fetch(path);
    document.getElementById(id).innerHTML = await res.text();
}

async function init() {
    await loadComponent("header", "components/header.html");
    await loadComponent("sidebar", "components/sidebar.html");

    loadDashboardData();
}

async function loadDashboardData() {
    const data = await getConversations();

    if (!data) return;

    document.getElementById("activeChats").innerText = data.length;
}

init();