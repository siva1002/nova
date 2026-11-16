"""Generated or thin HTTP clients for OTHER services, built from contracts/openapi/*.yaml.

This is the ONLY way to reach another service. Every call: 2 s timeout, forward Authorization and X-Request-Id,
fail closed (raise DependencyUnavailable), retry reads only. Never import another service's package.
Sprint 3: events replace most of these calls with local copies; the client interface stays so use cases do not change."""
