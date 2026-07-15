# Public repository — no infra or personal details, ever

`origin` is a **public** GitHub repository. Everything committed here is world-readable, permanently: git history, forks and mirrors all keep it, so deleting a leak later does not undo it.

**Never commit — and never write into any tracked file (code, docs, KB, memory, commit messages, PR/issue text):**
- How or where this is deployed or hosted — server/box topology, hostnames, IPs, ports, reverse-proxy / tunnel / CDN wiring, container or stack layout, on-host filesystem paths, orchestration or auto-update mechanics.
- Secrets, tokens, credentials (if a location must be referenced, cite the path, never the value).
- The owner's personal details — names, email addresses, home network, physical location.

Keep the codebase **deployment-agnostic**: it must read as generic, self-hostable software that anyone could run, not a description of one operator's environment. Any deployment specifics belong only in the operator's own private infra repo, never here.

**How to apply:** before every commit/PR, read the diff and confirm it carries no host / infra / personal specifics. When docs or examples need config, use placeholders (`example.com`, `YOUR_TOKEN`, `/path/to/data`) — never real values. This is a hard boundary, not a preference: when in doubt, leave it out and ask.
