# Teamworker development

- Keep this a small Telegram-to-pi bridge, not an agent framework.
- Prefer pi built-ins, AGENTS.md instructions, self-contained skills and existing
  CLIs/MCP servers over application code.
- One configured group, one operator, one persistent session, one ordered worker.
- Only explicit Telegram @mentions trigger group tasks. Private chat is admin-only.
- Enforce routing and operator identity in code. Never claim prompts are security boundaries.
- Never log or commit credentials, private messages, browser state or workspace data.
- Do not add personal assistant features, contact management, schedulers or role systems.
- Preserve attribution for code imported from oliverruoff/pi.lot.
- Tests: `python -m unittest discover -s tests -v`.
- Runtime team instructions live in `teamworker/AGENTS.md`; the entrypoint seeds
  `/workspace/AGENTS.md` once. Existing operator customizations must not be overwritten.
