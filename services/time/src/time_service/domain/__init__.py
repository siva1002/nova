"""PURE business rules and types. Dataclasses, enums, validation functions, domain errors.

No web, no database, no HTTP, no clock reads (take `now` as an argument). Fast to unit test.
May import: common.errors and the standard library only. (import-linter enforces this.)"""
