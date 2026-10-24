/** Read-only CLI startup audit. No prompt is submitted and no model is called. */
import { writeFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  let providerRequests = 0;
  pi.on("before_provider_request", () => {
    providerRequests++;
    throw new Error("Model requests are forbidden during the load audit");
  });
  pi.on("session_start", (_event, ctx) => {
    const output = process.env.PI_PROBE_OUTPUT;
    if (!output) throw new Error("PI_PROBE_OUTPUT is required");
    writeFileSync(output, JSON.stringify({
      cwd: ctx.cwd,
      agentDir: process.env.PI_CODING_AGENT_DIR,
      activeTools: pi.getActiveTools().sort(),
      allTools: pi.getAllTools(),
      providerRequests,
    }, null, 2) + "\n");
    ctx.shutdown();
  });
}
