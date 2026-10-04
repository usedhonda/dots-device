# Answer event accepted, but Dot chat unavailable

Use this runbook when the device has selected an answer or an MCP Events endpoint has accepted an event, but the expected response does not appear in ordinary chat. Follow the [architecture](architecture.md) and [Dot instructions](dot-instructions.md) for the intended flow. This is a diagnosis procedure, not a firmware repair or a guarantee of delivery time.

## Keep the stages separate

| Stage | Evidence that establishes it | What it does not establish |
| --- | --- | --- |
| Selected and persisted | Device answer state contains the expected question/interaction ID, choice ID and request ID | Event delivery, Dot processing or chat delivery |
| Event accepted | The matching event attempt received HTTP 2xx from the Events endpoint | A subscriber received it, a receiver ran, or an owner conversation was reachable |
| Dot read the answer | A successful `device_read_answer(question_id)` result, correlated to the question the Dot published, with matching IDs, a valid choice and `source: real` | Receipt persistence or an ordinary chat message |
| Receipt recorded | Successful `device_record_receipt` and device readback of the matching receipt ID and summary | Delivery of a message to ordinary chat |
| Ordinary chat delivered | Supported chat delivery evidence for the intended conversation, or the user's observation of the message | A device receipt unless separately checked |

A tap returning HOME is local UI evidence. An HTTP 2xx is acceptance evidence. Neither proves the complete route. Record each stage as confirmed, failed, unknown or not attempted; do not fill gaps from adjacent successes.

## Preserve and correlate evidence

1. Preserve the existing answer and pending state. Do not replace the question, tap again, replay the event or restart components merely to produce fresh logs.
2. Collect the smallest available device status and event-attempt record. Correlate question/interaction ID, choice ID, request ID, event ID where available, attempt timestamp, HTTP result and receipt ID. Use one bounded record for the affected answer, not unrelated answer history.
3. With authorized service diagnostics, trace that same event through its subscription, subscriber and receiver invocation. Establish whether the subscription was active for the correct event type and device, whether a receiver was invoked, and which owner conversation it targeted. A subscription count without matching identity and invocation evidence is insufficient.
4. Correlate the receiver's identity and target with the intended Dot and owner conversation. Keep thread availability, plugin/tool authorization and event subscription as separate checks. Record the exact failing operation and error; do not infer a deleted conversation or expired subscription from a generic availability error.
5. Compare the read-answer and receipt stages with ordinary chat delivery. A successful device tool in a diagnostic thread does not prove that an event receiver can use the owner's ordinary conversation.

Store diagnostics in ignored local files. Do not publish credentials, subscription secrets, private conversation contents or raw identity values. This runbook uses no chat-read tool: if chat reading is forbidden, keep it forbidden and use permitted routing diagnostics or the user's direct observation for delivery evidence. If a required diagnostic surface is unavailable, name the missing evidence and leave that stage unknown.

## Owner-conversation availability failure

Several durable conversations can share the same Dot title while serving different roles:

| Conversation role | Evidence to identify it |
| --- | --- |
| Normal-chat root | The intended owner binding and ordinary user delivery context; successful normal message delivery can establish this route |
| Event automation receiver | The matching webhook/automation invocation and event delivery context |
| Developer diagnostic thread | Diagnostic tool calls and developer context; access here does not establish the owner's route |

Select by role, owner binding and delivery context, not title or recency. A normal message can succeed in the normal-chat root while a developer thread reports the error below. An event automation receiver can be separate from both. These observations narrow the diagnosis but do not establish the actual callback mapping: correlate the affected event to its receiver and owner target before naming the root cause.

An observed error is:

```text
The user's dot or its owner conversation is unavailable to this thread.
```

This establishes that the attempted operation could not access the Dot or its owner conversation from that thread. It does not identify which binding failed, and it does not undo a previously accepted event or persisted answer. Record the tool or receiver operation that returned it, its time and the correlated event/request IDs. Do not promote HTTP acceptance to chat success, and do not create a receipt claiming an unread answer was processed.

If no binding-repair tool is exposed, do not invent one or edit undocumented identifiers/configuration. The next useful evidence is the subscription-to-receiver-to-owner-conversation mapping and the receiver's failure record. If the service cannot expose those records, report the boundary explicitly: the event was accepted, but receiver execution or owner-conversation delivery remains unverified.

## Supported recovery, then one bounded confirmation

After diagnosis identifies a stale, missing or unavailable connection, use only the service's supported plugin/Dot reconnection or conversation-selection UI for that specific connection. Preserve the answer IDs and existing subscription evidence first. If reconnection requires user authentication or a physical action, prepare the supported flow and state the one remaining action. Do not indiscriminately remove subscriptions, switch owner conversations or recreate a Dot.

Reconnection is a recovery attempt, not proof. Confirm the repaired mapping and use the affected answer only if the supported workflow can safely reconcile it without duplicate processing. Otherwise, use an explicitly identified synthetic test question and answer, with new IDs and existing authorization. Never turn a test selection or diagnostic event into a user preference, stored instruction or authorization for unrelated action.

Check only the previously unproved stages: matching receiver invocation, a real-answer read when applicable, a matching receipt, and ordinary chat delivery. Stop once the intended route has direct evidence. If any result is unknown, preserve it as unknown; do not automatically resend an answer, receipt or chat message. Saved Dot instructions are not an automatic hook, and poll timing, event acceptance or reconnection does not guarantee latency.

Report the confirmed stages, exact failed/unknown stage, supported recovery performed, and remaining evidence needed. Keep ordinary chat content free of device JSON and machine IDs.
