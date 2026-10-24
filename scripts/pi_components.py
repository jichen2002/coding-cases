"""Local component definitions and installation; no dependency on pi-builds."""
from dataclasses import dataclass
from pathlib import Path
import shlex


AGENT_DIR = "/tmp/harbor-pi-agent"
RESOURCES = Path(__file__).parent / "resources"


@dataclass(frozen=True)
class Component:
    packages: tuple[str, ...] = ()
    global_packages: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    resource_tree: str | None = None
    target_tree: str | None = None
    skills: tuple[str, ...] = ()
    testable: bool = True
    enabled: bool = True


COMPONENTS = {
    "lsp": Component(
        packages=("pi-diet-lsp@0.1.9",), global_packages=("pyright@1.1.413",),
        tools=("lsp_definition", "lsp_references", "lsp_symbols", "lsp_hover", "lsp_diagnostics")),
    "ast-search": Component(
        packages=("@juvio15/pi-ast-grep@0.4.2",), global_packages=("@ast-grep/cli@0.45.3",),
        tools=("ast_grep_run", "ast_grep_scan", "ast_grep_rewrite", "ast_grep_outline",
               "ast_grep_debug_query", "ast_grep_languages")),
    "todo": Component(tools=("todo",), resource_tree="todo", target_tree="extensions"),
    "skills": Component(resource_tree="skills", target_tree="skills", skills=("diagnosing-bugs", "tdd")),
    "web-search": Component(packages=("pi-web-access@0.44.0",), tools=("web_search",), testable=False),
    "subagent": Component(tools=("subagent",), resource_tree="subagent", target_tree="extensions/subagent", testable=False),
    "plan": Component(testable=False, enabled=False),
}


def resolve(components: list[str], *, for_probe: bool = False) -> list[str]:
    if len(components) != len(set(components)):
        raise ValueError("components must not contain duplicates")
    for name in components:
        if name not in COMPONENTS:
            raise ValueError(f"Unknown component: {name}")
        spec = COMPONENTS[name]
        if not spec.enabled:
            raise ValueError(f"Component {name} is disabled pending a headless execution policy")
        if for_probe and not spec.testable:
            raise ValueError(f"Component {name} is excluded from testing by project policy; use the installer-only entry point")
    return [name for name in COMPONENTS if name in components]


def manifest(components: list[str]) -> dict:
    selected = resolve(components)
    return {
        "variant": "+".join(selected) or "baseline", "components": selected,
        "expectedTools": sorted({t for n in selected for t in COMPONENTS[n].tools}),
        "expectedSkills": sorted({s for n in selected for s in COMPONENTS[n].skills}),
        "expectedExtensions": sum(bool(COMPONENTS[n].packages) or
                                  bool(COMPONENTS[n].target_tree and COMPONENTS[n].target_tree.startswith("extensions"))
                                  for n in selected),
        "expectedPackages": [p for n in selected for p in COMPONENTS[n].packages],
        "expectedGlobalPackages": [p for n in selected for p in COMPONENTS[n].global_packages],
        "verification": "not_tested",
        "limitations": (["Skills are unchanged upstream text; human interaction and autonomous use remain unverified"]
                        if "skills" in selected else []),
    }


async def upload_tree(agent, environment, source: Path, target: str) -> None:
    for file in sorted(source.rglob("*")):
        if not file.is_file():
            continue
        remote = f"{target}/{file.relative_to(source).as_posix()}"
        await agent.exec_as_agent(environment, command=f"mkdir -p {shlex.quote(str(Path(remote).parent))}")
        await environment.upload_file(file, remote)


async def install_components(agent, environment, selected: list[str]) -> None:
    await agent.exec_as_agent(environment, command=f"mkdir -p {AGENT_DIR}")
    for name in resolve(selected):
        spec = COMPONENTS[name]
        commands = []
        if spec.global_packages:
            commands.append("npm install -g " + " ".join(shlex.quote(p) for p in spec.global_packages))
        for package in spec.packages:
            commands.append("pi install " + shlex.quote("npm:" + package))
        if commands:
            await agent.exec_as_agent(environment, command='. "$HOME/.nvm/nvm.sh"; ' + " && ".join(commands), timeout_sec=600)
        if spec.resource_tree:
            source = RESOURCES / spec.resource_tree
            if name == "subagent":
                # Keep agent definitions outside extensions; avoid loading agents.ts as an extension.
                for filename in ("index.ts", "agents.ts"):
                    remote = f"{AGENT_DIR}/extensions/subagent/{filename}"
                    await agent.exec_as_agent(environment, command=f"mkdir -p {AGENT_DIR}/extensions/subagent")
                    await environment.upload_file(source / filename, remote)
                await upload_tree(agent, environment, source / "agents", f"{AGENT_DIR}/agents")
            else:
                await upload_tree(agent, environment, source, f"{AGENT_DIR}/{spec.target_tree}")
        if name == "ast-search":
            script = (
                "const fs=require('node:fs');const p=process.env.PI_CODING_AGENT_DIR+'/settings.json';"
                "const c=JSON.parse(fs.readFileSync(p,'utf8'));"
                "c.packages=c.packages.map(x=>{const s=typeof x==='string'?x:x.source;"
                "return s.startsWith('npm:@juvio15/pi-ast-grep@')?"
                "{...(typeof x==='object'?x:{}),source:s,skills:[]}:x});"
                "fs.writeFileSync(p,JSON.stringify(c,null,2)+'\\n');"
            )
            await agent.exec_as_agent(environment, command='. "$HOME/.nvm/nvm.sh"; node -e ' + shlex.quote(script))
        if name == "web-search":
            await environment.upload_file(RESOURCES / "web-search.json", f"{AGENT_DIR}/web-search.json")
