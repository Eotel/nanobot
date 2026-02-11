# A2A Protocol Support

nanobot now supports the [A2A (Agent2Agent) Protocol](https://a2a-protocol.org/) for interoperable agent communication.

## Overview

This implementation provides a standards-compliant A2A server interface that allows external agents to:

- Discover nanobot's capabilities via Agent Card
- Send tasks for processing
- Query task status and retrieve results
- Cancel in-flight tasks

## Configuration

Enable A2A in your `~/.nanobot/config.json`:

```json
{
  "a2a": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8080,
    "auth_token": "your-secret-token",
    "max_request_size": 1048576,
    "request_timeout": 30,
    "protocol_version": "0.3"
  }
}
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable/disable A2A server |
| `host` | `"127.0.0.1"` | Bind address (use `0.0.0.0` for external access) |
| `port` | `8080` | Server port |
| `auth_token` | `""` | Bearer token for authentication (empty = no auth) |
| `max_request_size` | `1048576` | Maximum request body size in bytes (1MB) |
| `request_timeout` | `30` | Request timeout in seconds |
| `protocol_version` | `"0.3"` | A2A protocol version |

## Starting the Server

Start nanobot gateway with A2A enabled:

```bash
nanobot gateway
```

The A2A server will start alongside the gateway if enabled in configuration.

## Endpoints

### Discovery

**GET `/.well-known/agent-card.json`**

Returns the Agent Card describing nanobot's capabilities. No authentication required.

```bash
curl http://localhost:8080/.well-known/agent-card.json | jq .
```

### Send Task

**POST `/a2a/tasks:send`**

Create a new task. The task is processed asynchronously by default.

```bash
curl -X POST http://localhost:8080/a2a/tasks:send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "method": "send",
    "input": {
      "messages": [
        {
          "role": "user",
          "content": "What is 2+2?",
          "content_type": "text/plain"
        }
      ]
    },
    "options": {
      "wait": false,
      "timeout_ms": 30000
    }
  }'
```

Response (202 Accepted):
```json
{
  "task": {
    "id": "abc123",
    "state": "submitted",
    "created_at": "2026-02-11T10:00:00Z",
    "updated_at": "2026-02-11T10:00:00Z"
  }
}
```

### Get Task

**GET `/a2a/tasks/{task_id}`**

Retrieve task status and results.

```bash
curl http://localhost:8080/a2a/tasks/abc123 \
  -H "Authorization: Bearer your-token"
```

Response (200 OK):
```json
{
  "task": {
    "id": "abc123",
    "state": "completed",
    "created_at": "2026-02-11T10:00:00Z",
    "updated_at": "2026-02-11T10:00:05Z"
  },
  "output": {
    "messages": [
      {
        "role": "assistant",
        "content": "2+2 equals 4",
        "content_type": "text/plain"
      }
    ]
  }
}
```

### List Tasks

**GET `/a2a/tasks`**

List tasks with optional filtering and pagination.

```bash
# List all tasks
curl "http://localhost:8080/a2a/tasks" \
  -H "Authorization: Bearer your-token"

# Filter by state
curl "http://localhost:8080/a2a/tasks?state=completed" \
  -H "Authorization: Bearer your-token"

# Paginate
curl "http://localhost:8080/a2a/tasks?limit=10&cursor=task-id" \
  -H "Authorization: Bearer your-token"
```

### Cancel Task

**POST `/a2a/tasks/{task_id}:cancel`**

Cancel a running or submitted task.

```bash
curl -X POST http://localhost:8080/a2a/tasks/abc123:cancel \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "method": "cancel",
    "reason": "User requested cancellation"
  }'
```

## Authentication

When `auth_token` is configured, all endpoints except discovery require a Bearer token:

```bash
-H "Authorization: Bearer your-secret-token"
```

Missing or invalid tokens return:
```json
{
  "error": {
    "code": "auth_required",
    "jsonrpc_code": -32001,
    "http_status": 401,
    "message": "Missing bearer token",
    "details": {}
  }
}
```

## Task Lifecycle

Tasks progress through the following states:

```
submitted → working → completed
    ↓           ↓
    └───────────┴──→ failed
    ↓
    └──────────────→ canceled
```

- **submitted**: Task created, waiting to start
- **working**: Task is being processed
- **completed**: Task finished successfully
- **failed**: Task failed with an error
- **canceled**: Task was canceled by user

## Error Handling

All errors follow the A2A protocol format:

```json
{
  "error": {
    "code": "error_code",
    "jsonrpc_code": -32600,
    "http_status": 400,
    "message": "Human readable message",
    "details": {}
  }
}
```

Common error codes:

| Code | HTTP | Description |
|------|------|-------------|
| `parse_error` | 400 | Invalid JSON payload |
| `invalid_request` | 400 | Invalid request format |
| `invalid_params` | 400 | Missing or invalid parameters |
| `method_not_found` | 404 | Unknown endpoint |
| `task_not_found` | 404 | Task ID does not exist |
| `auth_required` | 401 | Missing authentication |
| `auth_invalid` | 401 | Invalid authentication |
| `unsupported_type` | 415 | Unsupported content type |
| `payload_too_large` | 413 | Request body exceeds limit |

## Content Types

MVP supports text-only content:

- `text/plain`
- `text/markdown`

Other content types will be rejected with error code `unsupported_type`.

## Limitations

This is an MVP implementation with the following limitations:

- **Text-only**: Supports only text/plain and text/markdown content types
- **No streaming**: Real-time streaming responses not supported
- **No push notifications**: Webhook callbacks not supported
- **In-memory storage**: Task state is not persisted across restarts
- **No client mode**: nanobot can only act as an A2A server, not client

## Examples

### Complete Task Flow

```bash
# 1. Discover capabilities
curl http://localhost:8080/.well-known/agent-card.json

# 2. Send a task
TASK_RESULT=$(curl -s -X POST http://localhost:8080/a2a/tasks:send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer token" \
  -d '{"method":"send","input":{"messages":[{"role":"user","content":"Hello"}]}}')
TASK_ID=$(echo $TASK_RESULT | jq -r '.task.id')

# 3. Poll for completion
while true; do
  STATUS=$(curl -s "http://localhost:8080/a2a/tasks/$TASK_ID" \
    -H "Authorization: Bearer token" | jq -r '.task.state')
  echo "Status: $STATUS"
  [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]] && break
  sleep 1
done

# 4. Get result
curl "http://localhost:8080/a2a/tasks/$TASK_ID" \
  -H "Authorization: Bearer token" | jq '.output'
```

### With Wait Option

```bash
# Wait up to 30 seconds for completion
curl -X POST http://localhost:8080/a2a/tasks:send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer token" \
  -d '{
    "method": "send",
    "input": {"messages": [{"role": "user", "content": "Quick question"}]},
    "options": {"wait": true, "timeout_ms": 30000}
  }'
```

## Troubleshooting

### "Connection refused"
- Ensure A2A is enabled in config (`a2a.enabled: true`)
- Verify the gateway is running (`nanobot gateway`)
- Check the configured port is not in use

### "401 Unauthorized"
- Include the Authorization header with correct Bearer token
- Verify `auth_token` is configured if authentication is required
- Discovery endpoint (`/.well-known/agent-card.json`) works without auth

### "415 Unsupported Media Type"
- Ensure Content-Type header is `application/json`
- Check that message content_type is `text/plain` or `text/markdown`

### Tasks stuck in "submitted" state
- Verify nanobot has a configured LLM provider with API key
- Check logs for errors: `nanobot gateway --verbose`

## Further Reading

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [Agent Discovery Guide](https://a2a-protocol.org/latest/topics/agent-discovery/)
- Protocol contract: `docs/a2a-contract.md`
