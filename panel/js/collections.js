import { fetchCollectionManagers, fetchCollections, getCollectionByAccount, refreshCollectionAccount } from "./api.js";
import { dispatch, getState, subscribeStore } from "./store.js";

let currentCollectionFilters = {};
let unsubscribeCollectionsStore = null;
let lastRenderedCollectionVersion = -1;
let lastRenderedFilterSignature = "";
let lastDrawerAccount = null;
let lastDrawerSignature = "";
let collectionRequestId = 0;
let isRenderingCollections = false;
let drawerCloseEventsBound = false;
let lastCollectionMeta = null;
let collectionsOffset = 0;
let collectionsHasMore = false;
let collectionsAbortController = null;
let collectionsDebounceTimer = null;
let isLoadingCollections = false;
let isLoadingMoreCollections = false;
let managersAbortController = null;

const COLLECTIONS_PAGE_SIZE = 25;
const GESTOR_FILTER_ROLES = new Set(["admin", "jefe_operativo", "sistemas"]);

const collectionRowCache = new Map();
const pendingCollectionDetailRequests = new Map();

function reportCollectionError(scope, error) {
    console.error(`[collections] ${scope}:`, error);
}

function getDrawerElements() {
    return {
        drawer: document.getElementById("drawer"),
        body: document.getElementById("drawerBody"),
        overlay: document.getElementById("drawerOverlay"),
    };
}

function setCollectionsState(state) {
    const loadingEl = document.getElementById("collectionsLoading");
    const incrementalLoadingEl = document.getElementById("collectionsIncrementalLoading");
    const errorEl = document.getElementById("collectionsError");
    const emptyEl = document.getElementById("collectionsEmpty");
    const tableWrapper = document.getElementById("collectionsTableWrapper");
    const loadMoreButton = document.getElementById("collectionsLoadMoreButton");
    const endEl = document.getElementById("collectionsEnd");

    if (!loadingEl || !errorEl || !emptyEl || !tableWrapper) return;

    loadingEl.classList.add("hidden");
    incrementalLoadingEl?.classList.add("hidden");
    errorEl.classList.add("hidden");
    emptyEl.classList.add("hidden");
    tableWrapper.classList.add("hidden");
    loadMoreButton?.classList.add("hidden");
    endEl?.classList.add("hidden");

    switch (state.type) {
        case "loading":
            loadingEl.classList.remove("hidden");
            break;
        case "error":
            errorEl.textContent = state.message || "Error";
            errorEl.classList.remove("hidden");
            break;
        case "empty":
            emptyEl.classList.remove("hidden");
            break;
        case "success":
            tableWrapper.classList.remove("hidden");
            if (collectionsHasMore) {
                loadMoreButton?.classList.remove("hidden");
            } else {
                endEl?.classList.remove("hidden");
            }
            break;
        case "incremental":
            tableWrapper.classList.remove("hidden");
            incrementalLoadingEl?.classList.remove("hidden");
            break;
    }
}

function setReloading(isLoading) {
    const button = document.getElementById("collectionsReloadButton");
    if (!button) return;
    button.disabled = Boolean(isLoading);
}

function setLoadMoreLoading(isLoading) {
    const button = document.getElementById("collectionsLoadMoreButton");
    if (!button) return;
    button.disabled = Boolean(isLoading);
}

function filtersSignature(filters = {}) {
    return JSON.stringify(filters || {});
}

function drawerSignature(item = {}) {
    return JSON.stringify({
        no_cuenta: item.no_cuenta || "",
        folio: item.folio || "",
        phone: item.phone || "",
        customer_name: item.customer_name || "",
        account_status: item.account_status || "",
        process: item.process || "",
        classification: item.classification || "",
        balance: item.balance || "",
        overdue_amount: item.overdue_amount || "",
        total_paid: item.total_paid || "",
        last_payment: item.last_payment || "",
        sale_date: item.sale_date || "",
        payments: Array.isArray(item.payments)
            ? item.payments.map((payment) => [
                payment.id,
                payment.amount,
                payment.paid_at,
                payment.balance_after_payment,
                payment.concept,
            ])
            : [],
        siga_bridge: item.siga_bridge || null,
    });
}

function rowSignature(item = {}) {
    return JSON.stringify([
        item.no_cuenta || "",
        item.folio || "",
        item.phone || "",
        item.customer_name || "",
        item.account_status || "",
        item.classification || "",
        item.balance || "",
        item.last_payment || "",
        item.sale_date || "",
        item.days_overdue || "",
        item.total_paid || "",
        item.next_payment_reminder_at || "",
        item.payment_reminders_sent_count ?? "",
    ]);
}

function classificationLabel(item = {}) {
    const map = {
        sano: "Sano",
        critico: "Critico",
        juridico: "Critico",
        pagado: "Pagado",
        otro: ui.safeText(item.classification_label, "Otro"),
    };
    return map[item.classification] || ui.safeText(item.classification_label, "Otro");
}

function classificationTone(classification) {
    const map = {
        sano: "success",
        critico: "danger",
        juridico: "danger",
        pagado: "info",
        otro: "neutral",
    };
    return map[classification] || "neutral";
}

function renderClassificationBadge(item = {}) {
    return ui.renderBadge(
        classificationLabel(item),
        classificationTone(item.classification),
    );
}

function bridgeStatusText(meta = {}) {
    const status = meta?.bridge_status || "ok";
    const map = {
        ok: "",
        disabled: "SIGA Bridge deshabilitado. Mostrando datos locales.",
        fallback_local: "SIGA no respondio correctamente. Mostrando respaldo local.",
        timeout: "SIGA tardo demasiado en responder. Mostrando respaldo local.",
        no_scope: "No hay cuentas asignadas para este usuario.",
        paid_requires_filter: "La cuenta esta liquidada. Activa Mostrar pagadas para refrescarla desde SIGA.",
    };
    return map[status] || "";
}

function updateBridgeMessage(meta = null) {
    const messageEl = document.getElementById("collectionsBridgeMessage");
    if (!messageEl) return;

    const message = bridgeStatusText(meta || {});
    messageEl.textContent = message;
    messageEl.classList.toggle("hidden", !message);
}

function updateCollectionsKpis(items = []) {
    const safeItems = Array.isArray(items) ? items : [];
    const total = document.getElementById("collectionsKpiTotal");
    const overdue = document.getElementById("collectionsKpiOverdue");
    const paid = document.getElementById("collectionsKpiPaid");
    const active = document.getElementById("collectionsKpiActive");

    if (total) total.textContent = lastCollectionMeta?.total ?? safeItems.length;
    if (overdue) overdue.textContent = safeItems.filter((item) => item?.has_overdue).length;
    if (paid) paid.textContent = safeItems.filter((item) => item?.is_paid).length;
    if (active) active.textContent = safeItems.filter((item) => item?.is_active).length;
}

function formatDays(value) {
    if (value === null || value === undefined || value === "") return "-";
    const number = Number(value);
    if (!Number.isFinite(number)) return ui.safeText(value);
    return number === 1 ? "1 dia" : `${number} dias`;
}

function formatReminderSummary(item = {}) {
    const sent = Number(item.payment_reminders_sent_count || item.payment_reminders?.sent_count || 0);
    const next = item.next_payment_reminder_at || item.payment_reminders?.next_scheduled_for;
    const nextText = next ? ui.formatDateTime(next) : "Sin programar";
    const sentText = sent > 0 ? `${sent} enviado${sent === 1 ? "" : "s"}` : "Sin enviados";
    return { nextText, sentText };
}

function updateCollectionRow(row, item) {
    const reminder = formatReminderSummary(item);
    row.className = "cursor-pointer border-b border-gray-100 transition hover:bg-gray-50 dark:border-slate-700 dark:hover:bg-slate-700/40";
    row.innerHTML = `
        <td data-label="No. cuenta" class="px-4 py-4 font-medium">${ui.escapeHtml(ui.safeText(item.no_cuenta))}</td>
        <td data-label="Folio" class="px-4 py-4">${ui.escapeHtml(ui.safeText(item.folio))}</td>
        <td data-label="Telefono" class="px-4 py-4">${ui.escapeHtml(ui.safeText(item.phone))}</td>
        <td data-label="Cliente" class="px-4 py-4 min-w-[180px]">${ui.escapeHtml(ui.safeText(item.customer_name))}</td>
        <td data-label="Estado" class="px-4 py-4">
            <div class="flex flex-col gap-1">
                ${renderClassificationBadge(item)}
                <span class="text-xs text-gray-500 dark:text-slate-400">${ui.escapeHtml(ui.safeText(item.account_status || item.process))}</span>
            </div>
        </td>
        <td data-label="Saldo" class="px-4 py-4 whitespace-nowrap">${ui.escapeHtml(ui.formatMoney(item.balance))}</td>
        <td data-label="Ultimo pago" class="px-4 py-4 whitespace-nowrap">${ui.escapeHtml(ui.formatDateTime(item.last_payment))}</td>
        <td data-label="Fecha venta" class="px-4 py-4 whitespace-nowrap">${ui.escapeHtml(ui.formatDateTime(item.sale_date))}</td>
        <td data-label="Atraso" class="px-4 py-4">${ui.escapeHtml(formatDays(item.days_overdue))}</td>
        <td data-label="Total pagado" class="px-4 py-4 whitespace-nowrap">${ui.escapeHtml(ui.formatMoney(item.total_paid))}</td>
        <td data-label="Recordatorios" class="px-4 py-4 min-w-[170px]">
            <div class="flex flex-col gap-1 text-xs">
                <span class="font-medium text-gray-700 dark:text-slate-200">Prox: ${ui.escapeHtml(reminder.nextText)}</span>
                <span class="text-gray-500 dark:text-slate-400">${ui.escapeHtml(reminder.sentText)}</span>
            </div>
        </td>
    `;
}

function renderCollectionRows(items = [], validKeys = new Set()) {
    const tbody = document.getElementById("collectionsTableBody");
    if (!tbody) return;

    const fragment = document.createDocumentFragment();
    const safeItems = Array.isArray(items) ? items : [];

    safeItems.forEach((item) => {
        const account = ui.safeText(item?.no_cuenta, "");
        if (!account) return;

        const signature = rowSignature(item);
        const cached = collectionRowCache.get(account) || {
            node: document.createElement("tr"),
            signature: "",
        };

        if (cached.signature !== signature) {
            updateCollectionRow(cached.node, item);
            cached.signature = signature;
        }

        cached.node.onclick = () => openCollectionDetail(item);
        collectionRowCache.set(account, cached);
        fragment.appendChild(cached.node);
    });

    tbody.replaceChildren(fragment);

    for (const account of Array.from(collectionRowCache.keys())) {
        if (!validKeys.has(account)) {
            collectionRowCache.delete(account);
        }
    }
}

function renderCollectionsFromState(state) {
    if (isRenderingCollections) return;
    isRenderingCollections = true;

    try {
        const collections = state?.collections || {};
        const items = Array.isArray(collections.order)
            ? collections.order
                .map((account) => collections.byAccount?.[account])
                .filter(Boolean)
            : [];

        updateBridgeMessage(lastCollectionMeta);
        updateCollectionsKpis(items);

        if (!items.length) {
            renderCollectionRows([], new Set());
            setCollectionsState({ type: "empty" });
            return;
        }

        renderCollectionRows(items, new Set(items.map((item) => String(item.no_cuenta))));
        setCollectionsState({ type: "success" });
    } catch (error) {
        reportCollectionError("render_failed", error);
        setCollectionsState({ type: "error", message: "Error renderizando cobranza" });
    } finally {
        isRenderingCollections = false;
    }
}

function canUseGestorFilter() {
    return GESTOR_FILTER_ROLES.has(window.currentUser?.role);
}

function setupGestorFilterVisibility() {
    const group = document.getElementById("collectionFilterGestorGroup");
    const input = document.getElementById("collectionFilterGestor");
    const visible = canUseGestorFilter();

    if (group) {
        group.classList.toggle("hidden", !visible);
    }
    if (input) {
        input.disabled = !visible;
        if (!visible) {
            input.value = "";
        }
    }
}

async function loadCollectionManagers() {
    if (!canUseGestorFilter()) return;

    const select = document.getElementById("collectionFilterGestor");
    if (!select) return;

    if (managersAbortController) {
        managersAbortController.abort();
    }
    managersAbortController = new AbortController();

    try {
        select.disabled = true;
        const response = await fetchCollectionManagers({
            limit: 200,
            signal: managersAbortController.signal,
        });
        const managers = Array.isArray(response?.items) ? response.items : [];
        const currentValue = ui.safeText(select.value, "");
        const options = [
            `<option value="">Todos</option>`,
            ...managers.map((manager) => {
                const value = ui.safeText(manager?.value, "");
                if (!value) return "";
                return `<option value="${ui.escapeHtml(value)}">${ui.escapeHtml(ui.safeText(manager.label, value))}</option>`;
            }),
        ].join("");
        select.innerHTML = options;
        if (currentValue && managers.some((manager) => String(manager.value) === currentValue)) {
            select.value = currentValue;
        }
    } catch (error) {
        if (error?.name !== "AbortError") {
            reportCollectionError("managers_load_failed", error);
        }
    } finally {
        select.disabled = !canUseGestorFilter();
        managersAbortController = null;
    }
}

function readFilters() {
    const form = document.getElementById("collectionsFilterForm");
    if (!form) return {};

    const data = new FormData(form);
    const filters = {
        no_cuenta: ui.safeText(data.get("no_cuenta"), ""),
        folio: ui.safeText(data.get("folio"), ""),
        phone: ui.safeText(data.get("phone"), ""),
        name: ui.safeText(data.get("name"), ""),
        status: ui.safeText(data.get("status"), ""),
        date_from: ui.safeText(data.get("date_from"), ""),
        date_to: ui.safeText(data.get("date_to"), ""),
        overdue_only: data.get("overdue_only") === "on",
        include_paid: data.get("include_paid") === "on",
    };

    if (filters.status === "pagado" || filters.status === "all") {
        filters.include_paid = true;
    }

    if (canUseGestorFilter()) {
        filters.gestor = ui.safeText(data.get("gestor"), "");
    }

    return filters;
}

function normalizeCollectionsResponse(response = {}) {
    const meta = response?.meta || {};
    const items = Array.isArray(response?.items)
        ? response.items
        : Array.isArray(response?.data)
            ? response.data
            : [];

    return {
        items,
        total: response?.total ?? meta?.total ?? items.length,
        hasMore: Boolean(response?.has_more),
        nextCursor: response?.next_cursor ?? null,
        meta: {
            total: response?.total ?? meta?.total ?? items.length,
            source: meta?.source || response?.source,
            bridge_status: meta?.bridge_status || response?.bridge_status,
            bridge_error: meta?.bridge_error || response?.bridge_error,
            classification_options: response?.classification_options,
            warnings: Array.isArray(meta?.warnings) ? meta.warnings : [],
            include_paid: Boolean(meta?.include_paid),
            active_only: meta?.active_only !== false,
            limit: Number(meta?.limit || response?.limit || COLLECTIONS_PAGE_SIZE),
            offset: Number(meta?.offset || response?.offset || 0),
        },
    };
}

function cancelCollectionsRequest() {
    if (collectionsAbortController) {
        collectionsAbortController.abort();
    }
    collectionsAbortController = null;
}

async function loadCollections(filters = readFilters(), options = {}) {
    const append = Boolean(options.append);
    if (append && (!collectionsHasMore || isLoadingMoreCollections)) return;

    if (!append) {
        cancelCollectionsRequest();
        collectionsOffset = 0;
    }

    const requestId = ++collectionRequestId;
    currentCollectionFilters = filters || {};
    const offset = append ? collectionsOffset : 0;
    const controller = new AbortController();
    collectionsAbortController = controller;
    isLoadingCollections = !append;
    isLoadingMoreCollections = append;

    setCollectionsState({ type: append ? "incremental" : "loading" });
    setReloading(!append);
    setLoadMoreLoading(append);

    try {
        const response = await fetchCollections(
            currentCollectionFilters,
            COLLECTIONS_PAGE_SIZE,
            offset,
            { signal: controller.signal },
        );
        if (requestId !== collectionRequestId) return;

        const normalized = normalizeCollectionsResponse(response);
        lastCollectionMeta = normalized.meta;
        collectionsHasMore = normalized.hasMore;
        collectionsOffset = Number(normalized.nextCursor || (offset + normalized.items.length));

        dispatch({
            type: append ? "collections/append" : "collections/loaded",
            payload: normalized.items,
        });
    } catch (error) {
        if (error?.name === "AbortError") return;
        if (requestId !== collectionRequestId) return;
        lastCollectionMeta = null;
        collectionsHasMore = false;
        setCollectionsState({
            type: "error",
            message: error?.message || "Error cargando cobranza",
        });
    } finally {
        if (requestId === collectionRequestId) {
            if (collectionsAbortController === controller) {
                collectionsAbortController = null;
            }
            isLoadingCollections = false;
            isLoadingMoreCollections = false;
            setReloading(false);
            setLoadMoreLoading(false);
        }
    }
}

function loadMoreCollections() {
    void loadCollections(currentCollectionFilters, { append: true });
}

function closeCollectionsDrawer() {
    const { drawer, overlay } = getDrawerElements();
    if (!drawer || !overlay) return;

    cancelStaleCollectionDetailRequests(null);
    dispatch({
        type: "collections/select",
        payload: null,
    });

    drawer.classList.remove("translate-x-0");
    drawer.classList.add("translate-x-full");

    overlay.classList.remove("opacity-100");
    overlay.classList.add("opacity-0", "pointer-events-none");
}

function cancelStaleCollectionDetailRequests(activeAccount = null) {
    for (const [account, requestState] of pendingCollectionDetailRequests.entries()) {
        if (activeAccount != null && account === activeAccount) continue;
        requestState.cancelled = true;
        pendingCollectionDetailRequests.delete(account);
    }
}

function isDetailRequestActive(noCuenta) {
    return pendingCollectionDetailRequests.has(String(noCuenta || ""));
}

function shouldIncludePaidDetail() {
    return Boolean(
        currentCollectionFilters?.include_paid
        || currentCollectionFilters?.status === "pagado"
        || currentCollectionFilters?.status === "all"
    );
}

function renderPaymentsList(payments = []) {
    const safePayments = Array.isArray(payments) ? payments : [];
    if (!safePayments.length) {
        return `
            <div class="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300">
                Sin pagos registrados desde SIGA.
            </div>
        `;
    }

    return `
        <div class="space-y-3">
            ${safePayments.slice(0, 20).map((payment) => `
                <div class="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-slate-700 dark:bg-slate-900/60">
                    <div class="flex flex-wrap items-start justify-between gap-3">
                        <div class="min-w-0">
                            <div class="text-sm font-semibold text-gray-900 dark:text-white">
                                ${ui.escapeHtml(ui.formatMoney(payment.amount))}
                            </div>
                            <div class="mt-1 text-xs text-gray-500 dark:text-slate-400">
                                ${ui.escapeHtml(ui.formatDateTime(payment.paid_at))}
                            </div>
                        </div>
                        <div class="text-right text-xs text-gray-500 dark:text-slate-400">
                            Saldo: ${ui.escapeHtml(ui.formatMoney(payment.balance_after_payment))}
                        </div>
                    </div>
                    <div class="mt-2 text-sm text-gray-700 dark:text-slate-200">
                        ${ui.escapeHtml(ui.safeText(payment.concept || payment.product, "Pago"))}
                    </div>
                    <div class="mt-1 text-xs text-gray-500 dark:text-slate-400">
                        ${ui.escapeHtml(ui.safeText(payment.user || payment.payment_method, ""))}
                    </div>
                </div>
            `).join("")}
        </div>
    `;
}

function renderDrawerBase(item) {
    const { body } = getDrawerElements();
    if (!body) return;

    body.innerHTML = `
        <div class="flex h-full min-h-0 flex-col text-gray-900 dark:text-white">
            <div id="collectionsDrawerHeader" class="flex-none border-b border-gray-200 bg-gray-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-900 md:px-5"></div>

            <div class="drawer-scroll space-y-4 px-4 py-4 md:px-5">
                <section class="drawer-section">
                    <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Cliente</h4>
                    <div id="collectionsDrawerCustomer"></div>
                </section>

                <section class="drawer-section">
                    <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Cuenta</h4>
                    <div id="collectionsDrawerAccount"></div>
                </section>

                <section class="drawer-section">
                    <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Resumen financiero</h4>
                    <div id="collectionsDrawerFinancial"></div>
                </section>

                <section class="drawer-section">
                    <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
                        <h4 class="text-sm font-semibold text-gray-900 dark:text-white">Historial de pagos</h4>
                        <span id="collectionsDrawerPaymentsCount"></span>
                    </div>
                    <div id="collectionsDrawerPayments"></div>
                </section>
            </div>

            <div id="collectionsDrawerFooter" class="flex-none border-t border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900 md:p-5"></div>
        </div>
    `;

    updateDrawer(item);
}

function updateDrawer(item) {
    try {
        const header = document.getElementById("collectionsDrawerHeader");
        if (header) {
            const bridgeStatus = item?.siga_bridge?.status;
            const bridgeBadge = bridgeStatus && bridgeStatus !== "ok"
                ? ui.renderBadge("Fallback local", "warning")
                : ui.renderBadge("SIGA", "success");

            header.innerHTML = `
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                        <h2 class="truncate text-lg font-semibold md:text-xl">
                            Cuenta ${ui.escapeHtml(ui.safeText(item.no_cuenta))}
                        </h2>
                        <div class="mt-2 flex flex-wrap items-center gap-2">
                            ${renderClassificationBadge(item)}
                            ${bridgeBadge}
                        </div>
                        <div class="mt-2 text-xs text-gray-500 dark:text-slate-400">
                            Folio ${ui.escapeHtml(ui.safeText(item.folio))}
                        </div>
                    </div>
                    <button
                        id="collectionsDrawerCloseButton"
                        type="button"
                        class="h-10 w-10 shrink-0 rounded-lg bg-gray-100 text-gray-700 transition hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
                        aria-label="Cerrar"
                    >
                        X
                    </button>
                </div>
            `;

            const closeButton = document.getElementById("collectionsDrawerCloseButton");
            if (closeButton) closeButton.onclick = closeCollectionsDrawer;
        }

        const customer = document.getElementById("collectionsDrawerCustomer");
        if (customer) {
            const phones = Array.isArray(item.phones) && item.phones.length
                ? item.phones.join(", ")
                : item.phone;
            customer.innerHTML = ui.renderKeyValueGrid([
                { label: "Nombre", value: item.customer_name || item.customer?.name },
                { label: "Telefonos", value: phones },
                { label: "Codigo cliente", value: item.customer?.customer_code },
                { label: "Domicilio", value: item.customer?.address_text },
            ]);
        }

        const account = document.getElementById("collectionsDrawerAccount");
        if (account) {
            const reminder = formatReminderSummary(item);
            account.innerHTML = ui.renderKeyValueGrid([
                { label: "No. cuenta", value: item.no_cuenta },
                { label: "Folio", value: item.folio },
                { label: "Estado de cuenta", value: item.account_status },
                { label: "Proceso", value: item.process },
                { label: "Clasificacion", value: classificationLabel(item) },
                { label: "Proximo recordatorio", value: reminder.nextText },
                { label: "Recordatorios enviados", value: reminder.sentText },
                { label: "Producto", value: item.product },
                { label: "Fecha venta", value: ui.formatDateTime(item.sale_date) },
                { label: "Ultimo pago", value: ui.formatDateTime(item.last_payment) },
                { label: "Asesor", value: item.advisor },
                { label: "Gestor", value: item.collector },
            ]);
        }

        const financial = document.getElementById("collectionsDrawerFinancial");
        if (financial) {
            const summary = item.financial_summary || {};
            financial.innerHTML = ui.renderKeyValueGrid([
                { label: "Saldo / adeudo", value: ui.formatMoney(summary.debt || item.debt || item.balance) },
                { label: "Saldo", value: ui.formatMoney(summary.balance || item.balance) },
                { label: "Vencido", value: ui.formatMoney(summary.overdue_amount || item.overdue_amount) },
                { label: "Moratorio", value: ui.formatMoney(summary.late_fee) },
                { label: "Liquidacion", value: ui.formatMoney(summary.liquidation_amount) },
                { label: "Pago inicial", value: ui.formatMoney(summary.initial_payment) },
                { label: "Pago minimo", value: ui.formatMoney(summary.minimum_payment) },
                { label: "Total pagado", value: ui.formatMoney(summary.total_paid || item.total_paid) },
                { label: "Dias de atraso", value: formatDays(item.days_overdue) },
                { label: "Pagos registrados", value: summary.payments_count ?? item.payments_count },
            ]);
        }

        const paymentsCount = document.getElementById("collectionsDrawerPaymentsCount");
        if (paymentsCount) {
            paymentsCount.innerHTML = ui.renderBadge(item.payments_count || 0, "neutral");
        }

        const payments = document.getElementById("collectionsDrawerPayments");
        if (payments) {
            payments.innerHTML = renderPaymentsList(item.payments);
        }

        const footer = document.getElementById("collectionsDrawerFooter");
        if (footer) {
            const isRefreshing = isDetailRequestActive(item.no_cuenta);
            footer.innerHTML = `
                <div class="flex flex-col gap-2 sm:flex-row">
                    <button
                        id="collectionsRefreshSigaButton"
                        type="button"
                        class="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-blue-500 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                        ${isRefreshing ? "disabled" : ""}
                    >
                        <i data-lucide="refresh-cw" class="h-4 w-4"></i>
                        <span>${isRefreshing ? "Actualizando..." : "Actualizar SIGA"}</span>
                    </button>
                    ${item.siga_url ? `
                        <button
                            id="collectionsGoToSigaButton"
                            type="button"
                            class="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
                        >
                            <i data-lucide="external-link" class="h-4 w-4"></i>
                            <span>Ir a SIGA</span>
                        </button>
                    ` : ""}
                </div>
            `;

            const refreshButton = document.getElementById("collectionsRefreshSigaButton");
            if (refreshButton) {
                refreshButton.onclick = () => {
                    void refreshCollectionDetail(item, { force: true });
                };
            }

            const sigaButton = document.getElementById("collectionsGoToSigaButton");
            if (sigaButton) {
                sigaButton.onclick = () => {
                    window.open(item.siga_url, "_blank", "noopener");
                };
            }
        }

        if (window.lucide) {
            window.lucide.createIcons();
        }
    } catch (error) {
        reportCollectionError("update_drawer_failed", error);
    }
}

function openCollectionDetail(item) {
    const { drawer, overlay } = getDrawerElements();
    if (!drawer || !overlay) return;

    const account = ui.safeText(item?.no_cuenta, "");
    if (!account) return;

    cancelStaleCollectionDetailRequests(account);
    lastDrawerAccount = account;
    lastDrawerSignature = drawerSignature(item);

    dispatch({
        type: "collections/select",
        payload: account,
    });

    renderDrawerBase(item);

    drawer.classList.remove("translate-x-full");
    drawer.classList.add("translate-x-0");

    overlay.classList.remove("opacity-0", "pointer-events-none");
    overlay.classList.add("opacity-100");

    void refreshCollectionDetail(item);
}

async function refreshCollectionDetail(item, options = {}) {
    const account = ui.safeText(item?.no_cuenta, "");
    if (!account) return;

    const activeRequest = pendingCollectionDetailRequests.get(account);
    if (activeRequest) return activeRequest.promise;

    const requestState = {
        cancelled: false,
        promise: null,
    };

    requestState.promise = (async () => {
        try {
            let latest = options.force
                ? await refreshCollectionAccount(account, { includePaid: shouldIncludePaidDetail() })
                : await getCollectionByAccount(account, { includePaid: shouldIncludePaidDetail() });

            if (!Array.isArray(latest?.payments) || !latest.payments.length) {
                try {
                    const paymentsResponse = await getCollectionPayments(account, { includePaid: true });
                    const paymentItems = Array.isArray(paymentsResponse?.data)
                        ? paymentsResponse.data
                        : Array.isArray(paymentsResponse)
                            ? paymentsResponse
                            : [];
                    if (paymentItems.length) {
                        latest = {
                            ...latest,
                            payments: paymentItems,
                            payments_count: paymentItems.length,
                            financial_summary: {
                                ...(latest?.financial_summary || {}),
                                payments_count: paymentItems.length,
                            },
                        };
                    }
                } catch (paymentsError) {
                    console.warn("No se pudo cargar historial de pagos:", paymentsError);
                }
            }

            if (requestState.cancelled || String(lastDrawerAccount || "") !== account) {
                return;
            }

            if (!latest?.no_cuenta || String(latest.no_cuenta) !== account) {
                return;
            }

            dispatch({
                type: "collections/upsert",
                payload: latest,
            });
        } catch (error) {
            console.warn("No se pudo refrescar detalle de cobranza:", error);
        } finally {
            if (pendingCollectionDetailRequests.get(account) === requestState) {
                pendingCollectionDetailRequests.delete(account);
            }

            if (!requestState.cancelled && String(lastDrawerAccount || "") === account) {
                const next = getState().collections.byAccount?.[account] || item;
                updateDrawer(next);
            }
        }
    })();

    pendingCollectionDetailRequests.set(account, requestState);
    if (String(lastDrawerAccount || "") === account) {
        const current = getState().collections.byAccount?.[account] || item;
        updateDrawer(current);
    }

    return requestState.promise;
}

function bindCollectionFilters() {
    const form = document.getElementById("collectionsFilterForm");
    setupGestorFilterVisibility();

    if (form) {
        form.onsubmit = (event) => {
            event.preventDefault();
            void loadCollections(readFilters());
        };

        const debouncedInputs = [
            "collectionFilterAccount",
            "collectionFilterFolio",
            "collectionFilterPhone",
            "collectionFilterName",
        ];

        debouncedInputs.forEach((id) => {
            const input = document.getElementById(id);
            if (!input || input.disabled) return;
            input.oninput = () => {
                window.clearTimeout(collectionsDebounceTimer);
                collectionsDebounceTimer = window.setTimeout(() => {
                    void loadCollections(readFilters());
                }, 350);
            };
        });

        [
            "collectionFilterStatus",
            "collectionFilterDateFrom",
            "collectionFilterDateTo",
            "collectionFilterOverdue",
            "collectionFilterIncludePaid",
            "collectionFilterGestor",
        ].forEach((id) => {
            const input = document.getElementById(id);
            if (!input) return;
            input.onchange = () => {
                void loadCollections(readFilters());
            };
        });
    }

    const clearButton = document.getElementById("collectionsClearFiltersButton");
    if (clearButton && form) {
        clearButton.onclick = () => {
            form.reset();
            setupGestorFilterVisibility();
            void loadCollections({});
        };
    }

    const reloadButton = document.getElementById("collectionsReloadButton");
    if (reloadButton) {
        reloadButton.onclick = () => {
            void loadCollections(currentCollectionFilters);
        };
    }

    const loadMoreButton = document.getElementById("collectionsLoadMoreButton");
    if (loadMoreButton) {
        loadMoreButton.onclick = loadMoreCollections;
    }
}

function bindDrawerCloseEvents() {
    const overlay = document.getElementById("drawerOverlay");
    if (overlay) {
        overlay.onclick = closeCollectionsDrawer;
    }

    if (drawerCloseEventsBound) return;

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeCollectionsDrawer();
        }
    });

    drawerCloseEventsBound = true;
}

export function initCollectionsPage() {
    try {
        bindCollectionFilters();
        bindDrawerCloseEvents();

        lastRenderedCollectionVersion = -1;
        lastRenderedFilterSignature = "";
        lastDrawerAccount = null;
        lastDrawerSignature = "";
        collectionsOffset = 0;
        collectionsHasMore = false;
        cancelCollectionsRequest();
        if (managersAbortController) {
            managersAbortController.abort();
            managersAbortController = null;
        }
        window.clearTimeout(collectionsDebounceTimer);
        cancelStaleCollectionDetailRequests(null);

        void loadCollectionManagers();
        void loadCollections();

        if (unsubscribeCollectionsStore) {
            unsubscribeCollectionsStore();
        }

        unsubscribeCollectionsStore = subscribeStore((state) => {
            try {
                const collectionVersion = Number(state?.collections?._version || 0);
                const filterSignature = filtersSignature(currentCollectionFilters);

                if (
                    collectionVersion !== lastRenderedCollectionVersion
                    || filterSignature !== lastRenderedFilterSignature
                ) {
                    renderCollectionsFromState(state);
                    lastRenderedCollectionVersion = collectionVersion;
                    lastRenderedFilterSignature = filterSignature;
                }

                const selected = state?.collections?.selected;
                if (!selected) {
                    cancelStaleCollectionDetailRequests(null);
                    lastDrawerAccount = null;
                    lastDrawerSignature = "";
                    return;
                }

                const account = String(selected);
                const updated = state.collections.byAccount?.[account];
                if (!updated) return;

                const signature = drawerSignature(updated);
                if (account !== lastDrawerAccount) {
                    cancelStaleCollectionDetailRequests(account);
                    renderDrawerBase(updated);
                    lastDrawerAccount = account;
                    lastDrawerSignature = signature;
                    return;
                }

                if (signature !== lastDrawerSignature) {
                    updateDrawer(updated);
                    lastDrawerSignature = signature;
                }
            } catch (error) {
                reportCollectionError("store_subscription_failed", error);
                setCollectionsState({ type: "error", message: "Error actualizando cobranza" });
            }
        });
    } catch (error) {
        reportCollectionError("init_failed", error);
        setCollectionsState({ type: "error", message: "Error iniciando cobranza" });
    }
}

window.closeCollectionsDrawer = closeCollectionsDrawer;
