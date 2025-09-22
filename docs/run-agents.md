# API Documentation: Running the Boutique Agents

This document provides instructions on how to interact with the four primary agent endpoints of the Online Boutique application. The refactored architecture exposes each root agent as a distinct, runnable service.

All agent interactions are handled through a single, unified endpoint. The specific agent to run is determined by the `appName` field in the JSON request body.

**Endpoint:** `POST /run`
**Content-Type:** `application/json`

---

## Common Request Format

All requests to the `/run` endpoint must be `POST` requests with a JSON body that conforms to the following structure.

### Key Fields:

-   `appName` (string, **required**): The name of the root agent you want to run.
    -   Example: `"product_discovery_agent"`
-   `userId` (string, **required**): A unique identifier for the user.
-   `sessionId` (string, **required**): A unique identifier for the current conversation session.
-   `newMessage` (object, **required**): Contains the user's input.
    -   `role` (string): Typically `"user"`.
    -   `parts` (array): A list of content parts. For simple text, this will have one element.
        -   `text` (string): The natural language query from the user.
        -   `inlineData` (object): Used to send file data, like images.
            -   `data` (string): The file content, Base64-encoded.
            -   `mimeType` (string): The MIME type of the file (e.g., `"image/jpeg"`).
-   `stateDelta` (object, optional): A JSON object used to pass structured context to the agent (e.g., order IDs, user keys).

### Minimal JSON Body (Text Query):

```json
{
  "appName": "product_discovery_agent",
  "userId": "user-123",
  "sessionId": "session-456",
  "newMessage": {
    "role": "user",
    "parts": [
      {
        "text": "Show me some red shoes."
      }
    ]
  }
}
```

---

## Common Response Format

The API provides a streaming response composed of Server-Sent Events (SSE). Each event has an `event` type and a `data` payload. Key event types include:

-   `start`: Indicates the beginning of the agent run.
-   `thought`: Provides insight into the agent's reasoning process.
-   `tool_code`: Shows the tool the agent is about to execute.
-   `tool_result`: Shows the data returned by the tool.
-   `end`: The final event, containing the agent's conclusive output for the user.

---

## Agent Examples

### 1. Product Discovery Agent

**`appName`: `product_discovery_agent`**

#### Text Search

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
        "appName": "product_discovery_agent",
        "userId": "user-123",
        "sessionId": "session-456",
        "newMessage": {
          "role": "user",
          "parts": [
            { "text": "a pair of sunglasses for the beach" }
          ]
        }
      }'
```

#### Image Search

*Note: The image file must be Base64-encoded.*

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
        "appName": "product_discovery_agent",
        "userId": "user-123",
        "sessionId": "session-456",
        "newMessage": {
          "role": "user",
          "parts": [
            {
              "inlineData": {
                "data": "/9j/4AAQSkZJRg...",
                "mimeType": "image/jpeg"
              }
            }
          ]
        }
      }'
```

---

### 2. Shopping Assistant Agent

**`appName`: `shopping_assistant_agent`**

This agent provides personalized recommendations. Context is passed via `stateDelta`.

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
        "appName": "shopping_assistant_agent",
        "userId": "user-123",
        "sessionId": "session-456",
        "newMessage": {
          "role": "user",
          "parts": [
            { "text": "I need a complete outfit for a formal event." }
          ]
        },
        "stateDelta": {
          "user_key": "user-12345"
        }
      }'
```

---

### 3. Customer Service Agent

**`appName`: `customer_service_agent`**

This agent handles support queries. Structured data like order details are passed via `stateDelta`.

#### Check Order Status

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
        "appName": "customer_service_agent",
        "userId": "user-123",
        "sessionId": "session-456",
        "newMessage": {
          "role": "user",
          "parts": [
            { "text": "I want to check the status of my order." }
          ]
        },
        "stateDelta": {
          "order_id": "ABC-123-XYZ",
          "email": "customer@example.com"
        }
      }'
```

---

### 4. Checkout Agent

**`appName`: `checkout_agent`**

This agent orchestrates the checkout process and is initiated with a `cart_id` in the `stateDelta`.

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
        "appName": "checkout_agent",
        "userId": "user-123",
        "sessionId": "session-456",
        "stateDelta": {
          "cart_id": "cart-98765"
        }
      }'
```
