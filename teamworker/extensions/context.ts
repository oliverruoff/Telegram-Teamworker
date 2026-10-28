import { getAgentDir, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

// Configure pi's native threshold; never implement our own summarization.
export default function (pi: ExtensionAPI) {
  pi.registerCommand("reload", {
    description: "Reload skills, MCP configuration and instructions",
    async handler(_args, ctx) { await ctx.reload(); },
  });
  pi.registerCommand("teamworker-context", {
    description: "Internal bridge context usage",
    async handler(_args, ctx) {
      ctx.ui.notify("TW_CONTEXT:" + JSON.stringify(ctx.getContextUsage() ?? {
        tokens: null, contextWindow: ctx.model?.contextWindow ?? 0,
      }));
      if (!ctx.model) return;
      const window = ctx.model.contextWindow;
      const target = Number(process.env.COMPACT_TOKENS ?? 200000);
      const safety = Number(process.env.CONTEXT_RESERVE_TOKENS ?? 16384);
      const threshold = Math.min(target, Math.max(4096, window - safety));
      const reserve = Math.max(0, window - threshold);
      const keep = Math.min(20000, Math.floor(threshold / 4));
      const path = join(getAgentDir(), "settings.json");
      let settings: Record<string, any> = {};
      try { settings = JSON.parse(await readFile(path, "utf8")); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
      const compaction = settings.compaction ??= {};
      const overrides = compaction.modelOverrides ??= {};
      const key = `${ctx.model.provider}/${ctx.model.id}`;
      if (compaction.enabled === true && overrides[key]?.reserveTokens === reserve &&
          overrides[key]?.keepRecentTokens === keep) return;
      compaction.enabled = true;
      overrides[key] = { ...overrides[key], reserveTokens: reserve, keepRecentTokens: keep };
      await writeFile(path + ".tmp", JSON.stringify(settings, null, 2) + "\n", { mode: 0o600 });
      await rename(path + ".tmp", path);
      // Reload makes the running runtime use the settings. No captured ctx may
      // be used after this call; the next command receives a fresh context.
      await ctx.reload();
    },
  });
}
