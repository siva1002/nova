"""Outbox event builders (and, from sprint 3, consumers).

Build the payload for each event type here, matching contracts/events/*.schema.json, so use cases just call
`events.add("time.entry.created", ...)`. From sprint 3 the Kafka consumers and their inbox dedupe live here."""
