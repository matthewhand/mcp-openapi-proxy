# Asana Project Layout Convention (demo resource)

Agents creating Asana projects through the bridge MUST follow this layout:

1. **Project name**: `<initiative> — <short purpose>`, e.g. `MCP bridge demo — example verification sweep`.
2. **Project notes**: state what created the project and link the tool's repository.
3. **One task per unit of verifiable work**; task name = `<subject> — <result summary>`.
4. **Task notes** carry caveats or follow-ups (PR links, known issues), never credentials.
5. Agents may create projects and tasks; they MUST NOT delete or complete tasks a human created.

Serve this file to agents via:

```
ADDITIONAL_RESOURCES="asana-project-layout=/path/to/asana-project-layout.md"
```
