# OpenAI Agents SDK Integration

Use this guide to connect OpenAI Agents SDK approval interruptions to CENTCOM so risky tool calls are reviewed by human operators.

## Why this integration works well

OpenAI Agents SDK already supports human-in-the-loop interruptions with resumable run state. CENTCOM can provide the approval UI, routing, roles, and audit trail while your app controls pause/resume.

## Integration pattern

1. Mark sensitive tools with `needs_approval`.
2. Run the agent and inspect `result.interruptions`.
3. For each interruption, create a CENTCOM request (`POST /v1/requests`).
4. Wait for CENTCOM decision (webhook or polling).
5. Call `state.approve(...)` or `state.reject(...)`.
6. Resume with `Runner.run(agent, state)`.

## Minimal Python example

```python
from agents import Agent, Runner, function_tool
from centcom import CentcomClient

centcom = CentcomClient(api_key="cc_live_xxx")

@function_tool(needs_approval=True)
async def cancel_order(order_id: int) -> str:
    return f"Cancelled order {order_id}"

agent = Agent(name="Ops", instructions="Handle requests safely.", tools=[cancel_order])
result = await Runner.run(agent, "Cancel order 42")

while result.interruptions:
    state = result.to_state()
    for interruption in result.interruptions:
        req = centcom.create_request(
            type="approval",
            question=f"Approve tool call: {interruption.name}?",
            context=f"Arguments: {interruption.arguments}",
            required_role="manager",
            metadata={"tool_name": interruption.name, "tool_args": interruption.arguments},
        )
        decision = centcom.wait_for_response(req["id"], interval=3, timeout=600)
        approved = bool((decision.get("response") or {}).get("approved"))
        if approved:
            state.approve(interruption)
        else:
            state.reject(interruption, rejection_message="Rejected in CENTCOM")

    result = await Runner.run(agent, state)
```

## Production notes

- Prefer webhook-first approval delivery for lower latency and less polling load.
- Persist run state if approvals can take minutes or hours.
- Use `required_role` for `manager`/`admin` gating on risky actions.
- Keep rejection messages explicit so the model can adapt safely.

## Official references

- OpenAI Agents SDK (Python HITL): https://openai.github.io/openai-agents-python/human_in_the_loop/
- OpenAI Agents SDK (JS HITL): https://openai.github.io/openai-agents-js/guides/human-in-the-loop/
