from app.core.flow.flow import FLOW


def get_flow_summary():
    summary = []

    for state, config in FLOW.items():
        options = config.get("options", {})

        next_states = []

        for v in options.values():
            if v == "__RESUME__":
                continue
            next_states.append(str(v))

        summary.append({
            "state": str(state),
            "next": list(set(next_states))
        })

    return summary