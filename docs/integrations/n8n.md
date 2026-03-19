# n8n Integration

Use this guide to integrate n8n workflows with CENTCOM approvals using built-in nodes.

## Recommended approach (no custom node required)

Use built-in n8n nodes for a reliable first integration:

1. `HTTP Request` node -> create CENTCOM request (`POST /v1/requests`)
2. `Wait` node (`On Webhook Call`) -> pause workflow until approval callback
3. Continue flow based on approval payload (`approved` / `value`)

This works immediately in n8n without building a custom community node.

## Minimal workflow shape

1. Trigger (Webhook/Cron/Manual)
2. Build approval payload (Set node)
3. HTTP Request:
   - Method: `POST`
   - URL: `https://api.contro1.com/api/centcom/v1/requests`
   - Headers:
     - `Authorization: Bearer cc_live_xxx`
     - `Content-Type: application/json`
   - Body JSON:
     - `type`, `question`, `context`
     - `callback_url`: use your n8n resume endpoint
4. Wait node:
   - Resume: `On Webhook Call`
   - optional auth enabled
5. IF/Switch node:
   - Approved -> execute action
   - Rejected -> stop or fallback branch

## Sample request body

```json
{
  "type": "approval",
  "question": "Approve CRM write-back?",
  "context": "Sync 240 customer records from staging to production.",
  "callback_url": "https://your-n8n-host/webhook/centcom-resume",
  "priority": "urgent",
  "required_role": "manager",
  "metadata": {
    "workflow": "crm-sync",
    "execution_id": "{{$execution.id}}"
  }
}
```

## When to build a custom n8n node

Build a dedicated `n8n-nodes-centcom` package only if you need:

- reusable UX for many teams,
- centralized credential handling inside n8n UI,
- marketplace-style distribution for self-hosted n8n environments.

For most teams, HTTP Request + Wait is faster and easier to maintain.

## Deployment caveat

Unverified community nodes from npm are limited in n8n cloud contexts and are primarily a self-hosted path. Prefer docs/templates first unless there is clear demand for a managed node.

## Official references

- n8n HTTP Request node: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/
- n8n Wait node: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/
- n8n community-node install constraints: https://docs.n8n.io/integrations/community-nodes/installation/
