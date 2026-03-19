# CrewAI Integration

Use this guide to route CrewAI human-review steps through CENTCOM.

## Recommended approach

Use CrewAI webhook-based HITL for production:

1. Start execution with `humanInputWebhook` in kickoff.
2. Receive the CrewAI human-input webhook in your integration service.
3. Create a CENTCOM request from CrewAI task output.
4. When CENTCOM operator responds, call CrewAI resume endpoint.

## Kickoff example

```bash
curl -X POST {BASE_URL}/kickoff \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": { "topic": "AI Research" },
    "humanInputWebhook": {
      "url": "https://your-app.com/crewai/hitl",
      "authentication": {
        "strategy": "bearer",
        "token": "your-webhook-secret-token"
      }
    }
  }'
```

## CENTCOM bridge mapping

- Incoming from CrewAI webhook:
  - `execution_id`
  - `task_id`
  - task output/context for reviewer
- Create CENTCOM request:
  - `type`: `approval` or `free_text`
  - `question`: what should be approved
  - `context`: CrewAI output and relevant metadata
  - `metadata`: include `execution_id` and `task_id`
- Resume CrewAI after operator decision:
  - `is_approve`: true/false
  - `human_feedback`: operator comment or value
  - include webhook URLs again if your CrewAI setup requires it

## Resume example

```bash
curl -X POST {BASE_URL}/resume \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "execution_id": "abcd1234-5678-90ef",
    "task_id": "review_task",
    "human_feedback": "Approved with condition: add rollback step",
    "is_approve": true,
    "taskWebhookUrl": "https://your-app.com/webhooks/task",
    "stepWebhookUrl": "https://your-app.com/webhooks/step",
    "crewWebhookUrl": "https://your-app.com/webhooks/crew"
  }'
```

## Production notes

- Keep callback metadata small and deterministic.
- Validate signatures/auth for inbound webhooks.
- Add idempotency protection in your bridge service.
- Enforce `required_role` in CENTCOM for sensitive tasks.

## Official references

- CrewAI HITL workflows: https://docs.crewai.com/en/learn/human-in-the-loop
