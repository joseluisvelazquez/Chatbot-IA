def handle_out_of_flow(session, text):
    """
    Retorna:
    {
        "action": "respond" | "redirect" | "escalate",
        "reply": "...",
        "next_state": ChatState | None
    }
    """

    # Aquí iría tu llamada a OpenAI
    # response = call_openai(...)
