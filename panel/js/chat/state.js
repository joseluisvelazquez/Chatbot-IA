export const DEFAULT_PAGE_SIZE = 30

export function createPaginationState(overrides = {}) {
    return {
        offset: 0,
        loading: false,
        hasMore: true,
        ...overrides,
    }
}

export function createChatRuntimeState() {
    return {
        currentSessionId: null,
        lastTyping: 0,
        lastLoadTrigger: 0,
        lastLoadedSessionId: null,
        isLoadingChat: false,
        isSendingMessage: false,
        isFirstLoad: true,
        firstViewerOpen: true,
        forceRender: false,
        viewerShortcutsBound: false,
        chatLoadRequestId: 0,
        lastMessagesVersion: -1,
        lastMessagesSessionKey: null,
        lastPreviewVersion: -1,
    }
}
