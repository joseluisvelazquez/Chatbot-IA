export function createComposerController({
    emojis,
    onSend,
    onTyping,
}) {
    function autoResize(element) {
        if (!element) return

        element.style.height = "auto"
        const newHeight = Math.min(element.scrollHeight, 120)
        element.style.height = `${newHeight}px`
    }

    function handleKeyDown(event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault()
            onSend()
        }
    }

    function setupInputHandler() {
        const input = document.getElementById("messageInput")

        if (!input) {
            console.warn("No existe #messageInput")
            return
        }

        if (input._handleKeyDownRef) {
            input.removeEventListener("keydown", input._handleKeyDownRef)
        }

        const handler = (event) => {
            if (event.key !== "Enter") return
            if (event.shiftKey) return

            event.preventDefault()
            onSend()
        }

        input._handleKeyDownRef = handler
        input.addEventListener("keydown", handler)
    }

    function setupEmojiPicker() {
        const button = document.getElementById("emojiBtn")
        const container = document.getElementById("emojiPickerContainer")
        const input = document.getElementById("messageInput")

        if (!button || !container || !input) return

        if (!container.dataset.init) {
            container.innerHTML = `
                <input
                    id="emojiSearch"
                    placeholder="Buscar emoji..."
                    class="h-8 mb-3 px-2 rounded border border-gray-600 bg-white dark:bg-slate-800 border-gray-300 dark:border-slate-600 text-black dark:text-white text-sm outline-none focus:border-green-500"
                />
                <div
                    id="emojiGrid"
                    class="flex-1 grid grid-cols-8 gap-1 overflow-y-auto"
                ></div>
            `
            container.dataset.init = "true"
        }

        const grid = container.querySelector("#emojiGrid")
        const search = container.querySelector("#emojiSearch")

        if (!grid || !search) return

        container.classList.add("hidden")

        const render = (items) => {
            grid.innerHTML = ""

            items.forEach((emoji) => {
                const emojiButton = document.createElement("button")
                emojiButton.type = "button"
                emojiButton.className = `
                    flex items-center justify-center text-xl cursor-pointer
                    rounded-lg
                    hover:bg-gray-200 dark:hover:bg-slate-700
                    transition
                `
                emojiButton.textContent = emoji.emoji

                emojiButton.onclick = () => {
                    const start = input.selectionStart ?? input.value.length
                    const end = input.selectionEnd ?? input.value.length

                    input.value =
                        input.value.slice(0, start) +
                        emoji.emoji +
                        input.value.slice(end)

                    const nextPosition = start + emoji.emoji.length
                    input.focus()
                    input.selectionStart = input.selectionEnd = nextPosition

                    autoResize(input)
                    container.classList.add("hidden")
                }

                grid.appendChild(emojiButton)
            })
        }

        render(emojis.slice(0, 200))

        search.oninput = () => {
            const term = search.value.toLowerCase().trim()
            const filtered = emojis.filter((emoji) =>
                emoji.annotation?.toLowerCase().includes(term) ||
                emoji.tags?.some(tag => tag.toLowerCase().includes(term))
            ).slice(0, 200)

            render(filtered)
        }

        button.onclick = (event) => {
            event.stopPropagation()
            container.classList.toggle("hidden")

            if (!container.classList.contains("hidden")) {
                search.focus()
            }
        }

        container.onclick = (event) => {
            event.stopPropagation()
        }

        input.addEventListener("focus", () => {
            container.classList.add("hidden")
        })

        if (!container.dataset.outsideCloseBound) {
            document.addEventListener("click", () => {
                container.classList.add("hidden")
            })
            container.dataset.outsideCloseBound = "true"
        }
    }

    function updateComposerState(session) {
        const composer = document.getElementById("chatComposer")
        const input = document.getElementById("messageInput")
        const sendButton = document.getElementById("sendMessageBtn") || document.getElementById("sendButton")
        const attachButton = document.getElementById("attachFileBtn") || document.getElementById("fileButton")
        const fileInput = document.getElementById("fileInput")
        const hint = document.getElementById("composerHint")

        if (!composer || !input || !sendButton) return

        const setAttachmentDisabled = (disabled) => {
            if (fileInput) fileInput.disabled = disabled
            if (!attachButton) return

            attachButton.classList.toggle("opacity-50", disabled)
            attachButton.classList.toggle("pointer-events-none", disabled)
            attachButton.setAttribute("aria-disabled", String(disabled))
        }

        if (!session) {
            composer.classList.add("opacity-60", "pointer-events-none")
            input.disabled = true
            input.placeholder = "Selecciona una conversacion"
            sendButton.disabled = true
            setAttachmentDisabled(true)

            if (hint) {
                hint.textContent = ""
                hint.className = "text-xs text-gray-500 mt-1"
            }

            return
        }

        const canReply = Boolean(session.can_reply)
        const isSupport = session.status_operativo === "assigned_soporte"
        const isAssistant = session.status_operativo === "assistant_active"
        const isEscalated = session.status_operativo === "escalated"
        const isUnassigned = session.status_operativo === "unassigned"
        const isTest = Boolean(session.test_mode)

        composer.classList.remove("opacity-60", "pointer-events-none")

        if (canReply) {
            input.disabled = false
            sendButton.disabled = false
            setAttachmentDisabled(false)
            input.placeholder = "Escribe un mensaje..."

            if (hint) {
                let text = "Puedes responder esta conversacion."
                let className = "text-xs text-emerald-400 mt-1"

                if (isSupport) {
                    text = "Modo soporte tecnico activo."
                    className = "text-xs text-sky-400 mt-1"
                }

                if (isTest) {
                    text += " (Chat de pruebas)"
                }

                hint.textContent = text
                hint.className = className
            }

            return
        }

        input.disabled = true
        sendButton.disabled = true
        setAttachmentDisabled(true)

        let placeholder = "No puedes responder esta conversacion"
        let hintText = "Solo lectura"
        let hintClass = "text-xs text-gray-400 mt-1"

        if (isAssistant) {
            placeholder = "La conversacion esta atendida por Assistant"
            hintText = "Toma el chat si necesitas intervenir"
            hintClass = "text-xs text-cyan-400 mt-1"
        }

        if (isEscalated) {
            placeholder = "Pendiente de jefe operativo"
            hintText = "Esperando asignacion"
            hintClass = "text-xs text-amber-400 mt-1"
        }

        if (isUnassigned) {
            placeholder = "Chat sin asignar"
            hintText = "Toma el chat para responder"
            hintClass = "text-xs text-amber-400 mt-1"
        }

        if (isSupport) {
            placeholder = "Asignado a soporte tecnico"
            hintText = "Solo soporte puede responder"
            hintClass = "text-xs text-sky-400 mt-1"
        }

        if (isTest) {
            hintText += " (TEST)"
        }

        input.placeholder = placeholder

        if (hint) {
            hint.textContent = hintText
            hint.className = hintClass
        }
    }

    return {
        autoResize,
        handleKeyDown,
        setupInputHandler,
        setupEmojiPicker,
        updateComposerState,
    }
}
