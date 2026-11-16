"""ADAPTERS: implementations of use-case ports that are neither SQL (repo/) nor another service (clients/).

Here: password hashing (Argon2id), token signing (Ed25519), the in-process rate limiter.
They wrap a library behind a Protocol from usecases/ports.py, so use cases never import the library
and unit tests swap in fakes.
May import: domain, common, third-party libraries. Never api/ or usecases/ logic.
"""
