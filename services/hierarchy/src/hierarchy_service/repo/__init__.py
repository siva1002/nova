"""SQL ONLY. One class or module of async functions per aggregate. Each takes the request's session.

No permission checks, no business rules, never commit (the transaction belongs to the api/ layer).
Every query is already scoped to the workspace by forced RLS; still include workspace_id in inserts.
May import: domain (to return domain types), sqlalchemy, common."""
