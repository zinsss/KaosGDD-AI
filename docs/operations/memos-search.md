# Governor Memos search

## Scope

KaosGovernor provides a narrow, read-only adapter over the production Memos
`0.29.1` REST API. Memos remains authoritative. Governor does not maintain a
parallel memo database, archive, or background copy.

The initial implementation performs live creator-scoped content and tag
filtering through Memos. A derived semantic index can later be placed behind
the same tool contract. Search results contain compact snippets; callers fetch
the current full memo only after choosing a result.

## Configuration

```text
GOVERNOR_API_TOKEN_FILE=/run/secrets/governor_api_token
MEMOS_SEARCH_ENABLED=true
MEMOS_BASE_URL=http://100.94.208.16:5230
MEMOS_ACCESS_TOKEN_FILE=/run/secrets/memos_access_token
MEMOS_CREATOR=users/zin
MEMOS_TIMEOUT_SECONDS=15
MEMOS_SEARCH_MAX_RESULTS=20
```

Mount both files read-only. Use `0600` when the container UID owns the files,
or `0640` with a dedicated supplementary container group when file-backed
Compose secrets preserve host ownership. Direct
`GOVERNOR_API_TOKEN` and `MEMOS_ACCESS_TOKEN` values remain supported for
environments without Compose secrets, but do not set a value and its matching
`_FILE` variable together. Memos PATs are account-scoped but not
capability-scoped. Governor enforces the read-only boundary by exposing only
search and fetch routes. Do not give KaosBrain the Memos PAT. Store only the
Governor bearer token in KaosBrain's secret store.

The production compose currently publishes the API on `127.0.0.1:8097`. When
KaosBrain moves to another host, bind it only to the Governor Tailscale address
and restrict the host firewall to the Brain machine. Do not publish it through
Cloudflare.

## API

### Search

```http
POST /api/v1/memos/search
Authorization: Bearer <GOVERNOR_API_TOKEN>
Content-Type: application/json

{
  "query": "thermal printer",
  "tags": ["server"],
  "limit": 10
}
```

At least one query or tag is required. Limits cannot exceed
`MEMOS_SEARCH_MAX_RESULTS`. Results contain memo identity, timestamps, tags,
visibility, pin state, and a snippet. They do not contain the complete memo.

### Fetch current memo

```http
GET /api/v1/memos/42
Authorization: Bearer <GOVERNOR_API_TOKEN>
```

This always reads the current content from Memos. Brain should fetch only the
small set selected from search results.

## Future semantic search

The semantic index will be derived and rebuildable:

1. Poll memo identities, update timestamps, and content hashes.
2. Store chunks and embeddings in Governor PostgreSQL with `pgvector`.
3. Search the derived index for candidate memo IDs.
4. Fetch current candidate content from Memos before returning it to Brain.
5. Remove index entries when their source memo is deleted.

This does not change Memos' role as source of truth.
