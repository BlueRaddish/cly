# Workflow roadmap

cly is growing from a shared agent launcher into an agentic workflow-management
tool. The first step keeps active session inventories, resumes native histories,
and builds one local session-memory library with separate capture, review, filing
and verified-publication receipts. Chosen models can propose new curated PARA
notes through a reviewable filing plan. See [workflows](workflows.md) for current
behavior.

## Next useful improvements

- **Native session lifecycle integration:** provider hooks or supported registries
  that reveal a process's current conversation ID, including in-client switches.
  This can reduce manual binding without inferring identities from timing.
- **Broader native readers:** verified current Muse prose, Kimi wire transcripts,
  additional Qwen formats and Antigravity exports. Keep unsupported formats visible
  until fixtures and real-store checks establish their contracts.
- **Existing-note reconciliation:** extend new-note filing plans with reviewable
  merges into existing project/resource/memory notes and hubs. Preserve established
  metadata and edits; keep raw capture, proposed edits and completed filing receipts
  distinct.
- **Hierarchical final reconciliation:** combine exceptionally large collections of
  batch summaries without exceeding the chosen model's input budget. Existing
  message/content fragments already handle oversized individual sessions.
- **Native platform validation:** exercise terminal reopen and real agent resume on
  Windows, macOS and Linux; add device-aware history migration only if needed.
- **Collector startup integration:** optional OS-specific startup/service helpers
  that preserve single-instance behavior and report failures clearly.

## Optional future GUI — queued idea

Consider a GUI later if it makes workflow management easier. A useful first interface
could show active agents, exact native-ID bindings, dated snapshots, restore
preflight, library coverage and pending filing proposals. It should call the same
core operations as the CLI so either interface sees the same state and receipts.

This is an optional idea, not an implementation commitment or a prerequisite for
snapshot and document functionality. No GUI is included in the current feature.
