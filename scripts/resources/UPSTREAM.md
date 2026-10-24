# Extension resources

These resources are maintained in coding-cases; installation never reads pi-builds.

- `todo/todo.ts`, `subagent/index.ts`, and `subagent/agents.ts` come from
  earendil-works/pi at commit `4a080252f06caf63a525d7873c5d94d3c23887e0`, under
  `packages/coding-agent/examples/extensions/`. The MIT license is preserved in
  `LICENSE.pi`.
- Subagent definitions are from the same source, with their `model:` frontmatter
  removed. Upstream dispatch code passes the parent model and thinking level when
  no agent model is set. This integration is untested; endpoint, credentials,
  proxy inheritance and usage accounting are not claimed to be verified.
- `skills/` preserves the original diagnosing-bugs/tdd text and companion files.
  See its `UPSTREAM.md` and `LICENSE.mattpocock`. Human approval instructions and
  the missing external `codebase-design` skill reference are not silently changed.
  Discovery checks do not prove autonomous execution compatibility.
- `web-search.json` configures pi-web-access 0.44.0 for search-only exposure without
  browser cookies. Provider authentication and actual behavior are untested.

Plan mode is deliberately disabled until an unattended execution policy exists.
