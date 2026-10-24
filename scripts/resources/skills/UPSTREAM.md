# Vendored Skills — upstream attribution

Two Skills and their companion materials are copied **unchanged** from
[mattpocock/skills](https://github.com/mattpocock/skills) at commit
`5beb35b040e3de97e54fa9e386d7e42d15c295c2`.

- Upstream directories: `skills/engineering/diagnosing-bugs/` and `skills/engineering/tdd/`
- License: MIT, preserved in [LICENSE.mattpocock](LICENSE.mattpocock).
- Files included: both `SKILL.md` files, `tdd/tests.md`,
  `tdd/mocking.md`, and `diagnosing-bugs/scripts/hitl-loop.template.sh`.
- Upstream `agents/openai.yaml` files are omitted: they are metadata for other
  agent harnesses, not needed for Pi Skill loading.

## Unattended benchmark caveats

This is a verbatim upstream snapshot, **not an adaptation for Harbor**.
`diagnosing-bugs` has strict reproduction-stage gates and may ask for user
input when a useful reproduction is unavailable. `tdd` asks for test-seam
confirmation and references the separate `codebase-design` Skill, which is
not installed in this variant. These expectations can slow or stall
unattended SWE-bench Verified tasks. Measure activation and blockage;
version autonomous adaptations separately if needed.
