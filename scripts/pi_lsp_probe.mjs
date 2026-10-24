/** Exercise Pi's real resource loader and tool implementations without prompting. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: {
  variant: { type: "string" }, output: { type: "string" },
  "case-root": { type: "string", default: "/testbed" },
  manifest: { type: "string" },
} });
assert(values.manifest, "--manifest is required");
const selection = JSON.parse(await readFile(values.manifest, "utf8"));
const components = selection.components;
assert(components.every(c => ["lsp", "ast-search", "todo", "skills"].includes(c)),
  "This component is excluded from testing");
assert.equal(values.variant, selection.variant);
assert(values.output, "--output is required");
assert(process.env.PI_CODING_AGENT_DIR, "PI_CODING_AGENT_DIR is required");
const agentDir = process.env.PI_CODING_AGENT_DIR;
const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const packageRoot = path.join(npmRoot, "@earendil-works/pi-coding-agent");
const metadata = JSON.parse(await readFile(path.join(packageRoot, "package.json"), "utf8"));
assert.equal(metadata.version, "1.4.0", "This probe is verified against Pi 1.4.0");
const globalPackages = JSON.parse(execFileSync("npm", ["ls", "-g", "--depth=0", "--json"],
  { encoding: "utf8" })).dependencies;
const { createAgentSession, DefaultResourceLoader, SessionManager } =
  await import(pathToFileURL(path.join(packageRoot, "dist/index.js")));
const expectedActive = ["bash", "edit", "read", "write",
  ...selection.expectedTools].sort();
const report = {
  schemaVersion: 1, variant: values.variant, piVersion: metadata.version,
  components, globalPackages, limitations: selection.limitations,
  nodeVersion: process.version, uid: process.getuid(), agentDir,
  pythonEnvironment: JSON.parse(execFileSync("python", ["-c",
    "import sys,json; print(json.dumps(dict(executable=sys.executable, version=sys.version)))"],
    { encoding: "utf8" })),
  caseRoot: values["case-root"], status: "running", providerRequests: 0,
  sessions: [], checks: [],
};
const sessions = [];
function trackedDiffHash() {
  return createHash("sha256").update(execFileSync("git", ["diff", "HEAD", "--binary"],
    { cwd: values["case-root"] })).digest("hex");
}
const initialDiff = trackedDiffHash();
let fixture;
let exitCode = 0;

async function openSession(cwd) {
  const errors = [];
  const loader = new DefaultResourceLoader({ cwd, agentDir, extensionFactories: [pi => {
    pi.on("before_provider_request", () => {
      report.providerRequests++;
      throw new Error("Model requests are forbidden during the capability probe");
    });
  }] });
  await loader.reload();
  const extensions = loader.getExtensions();
  assert.deepEqual(extensions.errors, [], "Extension loading failed");
  const { session } = await createAgentSession({ cwd, agentDir, resourceLoader: loader,
    sessionManager: SessionManager.inMemory(cwd) });
  sessions.push(session);
  await session.bindExtensions({ mode: "json", onError: error => errors.push(error) });
  assert.deepEqual(errors, [], "Extension startup failed");
  const activeTools = session.getActiveToolNames().sort();
  assert.deepEqual(activeTools, expectedActive, "Unexpected active tools");
  assert.equal(extensions.extensions.length, selection.expectedExtensions + 1,
    "Unexpected extension loaded (the extra extension is the model-request guard)");
  const skills = loader.getSkills();
  assert.deepEqual(skills.skills.map(s => s.name).sort(), selection.expectedSkills,
    "Unexpected Skills contaminate the variant");
  const extensionPackages = [];
  for (const extension of extensions.extensions) {
    if (!path.isAbsolute(extension.resolvedPath)) continue;
    let dir = path.dirname(extension.resolvedPath);
    while (dir !== path.dirname(dir)) {
      try {
        const pkg = JSON.parse(await readFile(path.join(dir, "package.json"), "utf8"));
        extensionPackages.push({ name: pkg.name, version: pkg.version });
        break;
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
        dir = path.dirname(dir);
      }
    }
  }
  for (const expected of selection.expectedPackages) {
    const i = expected.lastIndexOf("@");
    assert(extensionPackages.some(p => p.name === expected.slice(0, i) && p.version === expected.slice(i + 1)),
      `Wrong or missing extension package: ${expected}`);
  }
  report.sessions.push({ cwd, activeTools, allTools: session.getAllTools(),
    extensionPackages,
    extensions: extensions.extensions.map(e => e.resolvedPath),
    skills: skills.skills, skillDiagnostics: skills.diagnostics });
  return session;
}

async function call(session, name, args) {
  const tool = session.agent.state.tools.find(t => t.name === name);
  assert(tool, `Tool ${name} is not active`);
  const started = performance.now();
  const result = await tool.execute(`probe-${report.checks.length}`, args, AbortSignal.timeout(30000));
  assert(!result.isError, `Tool ${name} returned an error`);
  const text = result.content.filter(c => c.type === "text").map(c => c.text).join("\n");
  report.checks.push({ tool: name, args, durationMs: performance.now() - started, result });
  return text;
}

try {
  const cli = JSON.parse(await readFile(path.join(path.dirname(values.output),
    `${values.variant}-cli.json`), "utf8"));
  assert.equal(cli.agentDir, agentDir, "CLI and SDK use different config directories");
  assert.equal(cli.providerRequests, 0);
  assert.deepEqual(cli.activeTools, expectedActive, "CLI has unexpected active tools");
  report.cliAudit = cli;
  const project = await openSession(values["case-root"]);
  if (values.variant === "baseline") {
    assert(!globalPackages.pyright, "Baseline unexpectedly contains Pyright");
    assert(!globalPackages["pi-diet-lsp"], "Baseline unexpectedly contains the LSP package");
    assert(!project.getAllTools().some(t => t.name.startsWith("lsp_")));
    assert.equal(report.sessions[0].extensions.length, 1, "Unexpected baseline extension");
  }
  for (const [component, packageName] of [["lsp", "pyright"], ["ast-search", "@ast-grep/cli"]]) {
    if (!components.includes(component)) assert(!globalPackages[packageName], `Unexpected package ${packageName}`);
  }
  for (const expected of selection.expectedGlobalPackages) {
    const i = expected.lastIndexOf("@");
    assert.equal(globalPackages[expected.slice(0, i)]?.version, expected.slice(i + 1));
  }
  if (components.includes("lsp")) {
    const pluginPaths = report.sessions[0].extensions.filter(p => p.includes("pi-diet-lsp"));
    assert.equal(pluginPaths.length, 1, "Expected exactly one LSP extension");
    const plugin = JSON.parse(await readFile(path.join(path.dirname(pluginPaths[0]), "package.json"), "utf8"));
    assert.equal(plugin.version, "0.1.9");
    report.lspVersion = plugin.version;
    report.pyrightVersion = execFileSync("pyright", ["--version"], { encoding: "utf8" }).trim();
    assert.match(report.pyrightVersion, /\b1\.1\.413\b/);
    fixture = await mkdtemp(path.join(tmpdir(), "pi-lsp-probe-"));
    await writeFile(path.join(fixture, "defs.py"), "def add_one(value: int) -> int:\n    return value + 1\n");
    await writeFile(path.join(fixture, "main.py"), "from defs import add_one\nanswer = add_one(41)\n");
    const test = await openSession(fixture);
    const definition = JSON.parse(await call(test, "lsp_definition", {
      filePath: "main.py", line: 2, character: 10,
    }));
    const locations = Array.isArray(definition) ? definition : [definition];
    assert(locations.some(loc => (loc?.uri ?? loc?.targetUri ?? "").endsWith("/defs.py")
      && (loc.range ?? loc.targetSelectionRange ?? loc.targetRange)?.start.line === 0),
    "Definition did not resolve to the known fixture definition");
    const references = await call(test, "lsp_references", {
      filePath: "defs.py", line: 1, character: 5, includeDeclaration: true,
    });
    assert.match(references, /main\.py:2:/, "Expected call-site reference is missing");
    assert.match(await call(test, "lsp_hover", {
      filePath: "main.py", line: 2, character: 10,
    }), /add_one/, "Hover did not identify the fixture function");
    assert.match(await call(test, "lsp_symbols", { filePath: "defs.py" }), /add_one/);
    const source = await readFile(path.join(values["case-root"], "astropy/utils/misc.py"), "utf8");
    const lines = source.split("\n");
    const line = lines.findIndex(l => /^class InheritDocstrings\b/.test(l));
    assert(line >= 0, "Expected Case symbol is missing");
    assert.match(await call(project, "lsp_symbols", {
      filePath: "astropy/utils/misc.py", query: "InheritDocstrings",
    }), /InheritDocstrings/, "LSP cannot read the actual Case source");
    const hover = await call(project, "lsp_hover", {
      filePath: "astropy/utils/misc.py", line: line + 1,
      character: lines[line].indexOf("InheritDocstrings") + 1,
    });
    assert.match(hover, /InheritDocstrings/, "Actual Case hover failed");
  }
  if (components.includes("ast-search")) {
    report.astGrepVersion = execFileSync("ast-grep", ["--version"], { encoding: "utf8" }).trim();
    assert.match(report.astGrepVersion, /\b0\.45\.3\b/);
    const result = await call(project, "ast_grep_run", {
      pattern: "add_one($VALUE)", lang: "python",
      code: "answer = add_one(41)\nother = unrelated(42)\n",
    });
    assert.match(result, /add_one\(41\)/);
    assert(!result.includes("unrelated(42)"), "AST search included an unrelated call");
    const source = await call(project, "ast_grep_run", {
      kind: "class_definition", lang: "python", path: "astropy/utils/misc.py", max_results: 20,
    });
    assert.match(source, /InheritDocstrings/);
    const outline = await call(project, "ast_grep_outline", { path: "astropy/utils/misc.py" });
    assert.match(outline, /InheritDocstrings/);
  }
  if (components.includes("todo")) {
    assert.match(await call(project, "todo", { action: "list" }), /No todos/);
    assert.match(await call(project, "todo", { action: "add", text: "Verify component installation" }), /Added todo #1/);
    assert.match(await call(project, "todo", { action: "list" }), /Verify component installation/);
    assert.match(await call(project, "todo", { action: "toggle", id: 1 }), /completed/);
    assert.match(await call(project, "todo", { action: "list" }), /\[x\]/);
    assert.match(await call(project, "todo", { action: "clear" }), /Cleared 1 todos/);
    assert.match(await call(project, "todo", { action: "list" }), /No todos/);
  }
  if (components.includes("skills")) {
    const companions = ["diagnosing-bugs/SKILL.md", "diagnosing-bugs/scripts/hitl-loop.template.sh",
      "tdd/SKILL.md", "tdd/tests.md", "tdd/mocking.md"];
    report.skillFiles = [];
    for (const file of companions) {
      const target = path.join(agentDir, "skills", file);
      assert((await readFile(target, "utf8")).trim(), `Missing Skill resource: ${file}`);
      report.skillFiles.push(target);
    }
    report.skillsDiscovered = selection.expectedSkills;
  }
  assert.equal(report.providerRequests, 0);
  for (const session of sessions) assert.deepEqual(session.messages, [], "Unexpected model conversation");
  assert.equal(trackedDiffHash(), initialDiff, "Probe changed tracked Case files");
  report.caseTrackedFilesUnchanged = true;
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = { message: error.message, stack: error.stack };
  exitCode = 1;
} finally {
  for (const session of sessions) session.dispose();
  if (fixture) await rm(fixture, { recursive: true, force: true });
  await mkdir(path.dirname(values.output), { recursive: true });
  await writeFile(values.output, JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify({ variant: report.variant, status: report.status,
    providerRequests: report.providerRequests, checks: report.checks.length, output: values.output }));
  // pi-diet-lsp 0.1.9 leaves its server handles alive after session.dispose().
  // The container process group must be cleaned up by the caller after this exits.
  process.exit(exitCode);
}
