#!/usr/bin/env node
/* agent-manager-brain — connect any agent to the agent-manager shared brain.
 *
 *   agent-manager-brain connect --url https://bot.getzoro.com [--token TOK] [--agent claude|cursor|generic]
 *   agent-manager-brain ask "question" [--url U] [--token T] [--no-llm]
 *   agent-manager-brain search "query"
 *   agent-manager-brain pack <project>
 *   agent-manager-brain note --project p --title t --body b
 *   agent-manager-brain stats
 *
 * Env: AGENT_MANAGER_URL, AGENT_MANAGER_TOKEN
 *      (also accepts legacy AGENT_CONTEXT_URL / AGENT_CONTEXT_TOKEN)
 */
const fs = require("fs");
const os = require("os");
const path = require("path");

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) args[key] = true;
      else { args[key] = next; i++; }
    } else args._.push(a);
  }
  return args;
}

const URL_BASE = process.env.AGENT_MANAGER_URL || process.env.AGENT_CONTEXT_URL || "";
const TOKEN = process.env.AGENT_MANAGER_TOKEN || process.env.AGENT_CONTEXT_TOKEN || "";

function requireBase(args) {
  const base = (args.url || URL_BASE).replace(/\/+$/, "").replace(/\/mcp$/, "");
  if (!base) {
    console.error("No --url given and AGENT_MANAGER_URL is not set.");
    process.exit(1);
  }
  return base;
}

async function api(base, token, method, apiPath, body) {
  const res = await fetch(base + apiPath, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Token": token, "Authorization": `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(`${res.status}: ${text.slice(0, 300)}`);
  return data;
}

function mergeJson(file, update) {
  let cur = {};
  try { cur = JSON.parse(fs.readFileSync(file, "utf8")); } catch {}
  if (update.mcpServers) {
    cur.mcpServers = { ...(cur.mcpServers || {}), ...update.mcpServers };
    delete update.mcpServers;
  }
  Object.assign(cur, update);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(cur, null, 2) + "\n");
  console.log(`wrote ${file}`);
}

function connect(args) {
  const base = requireBase(args).replace(/\/+$/, "");
  const url = base.endsWith("/mcp") ? base : base + "/mcp";
  const token = args.token || TOKEN || "";
  const name = args.name || "agent-manager";
  const headers = token ? { "X-Token": token } : {};
  const agent = args.agent || "generic";

  if (agent === "claude") {
    const { spawnSync } = require("child_process");
    const hdr = token ? ["--header", `X-Token: ${token}`] : [];
    const r = spawnSync("claude",
      ["mcp", "add", "--transport", "http", name, url, ...hdr],
      { stdio: "inherit" });
    if (r.status === 0) { console.log(`\nAdded ${name} to Claude Code.`); return; }
    console.error("claude CLI not available — generic config below.");
  }
  if (agent === "cursor") {
    mergeJson(path.join(os.homedir(), ".cursor", "mcp.json"),
      { mcpServers: { [name]: { url, headers } } });
    console.log(`\nAdded ${name} to Cursor. Restart Cursor to load it.`);
    return;
  }
  console.log(`\nMCP config for ${agent}:\n`);
  console.log(JSON.stringify({ mcpServers: { [name]: { url, headers } } }, null, 2));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0] || "help";
  try {
    if (cmd === "connect") return connect(args);
    if (cmd === "help") { console.log(__doc); return; }
    const base = requireBase(args);
    const token = args.token || TOKEN;
    let out;
    if (cmd === "ask") {
      out = await api(base, token, "POST", "/api/ask",
        { q: args._.slice(1).join(" "), use_llm: !args["no-llm"] });
      if (out.answer) console.log(out.answer + "\n\n--- sources ---");
      for (const c of out.results || [])
        console.log(`[${c.project}/${c.kind}] ${c.path} :: ${(c.heading || "").slice(0, 60)}`);
      return;
    } else if (cmd === "search") {
      out = await api(base, token, "GET",
        "/api/search?q=" + encodeURIComponent(args._.slice(1).join(" ")));
    } else if (cmd === "pack") {
      out = await api(base, token, "GET",
        "/api/context?project=" + encodeURIComponent(args._[1] || ""));
      console.log(out.pack); return;
    } else if (cmd === "note") {
      out = await api(base, token, "POST", "/api/note",
        { project: args.project, title: args.title || "untitled", body: args.body });
    } else if (cmd === "stats") {
      out = await api(base, token, "GET", "/api/stats");
    } else {
      console.log(__doc); return;
    }
    if (out) console.log(JSON.stringify(out, null, 2));
  } catch (e) {
    console.error("error: " + e.message);
    process.exit(1);
  }
}

const __doc = `agent-manager-brain — connect any agent to the agent-manager brain

  connect   --url https://bot.getzoro.com [--token TOK] [--agent claude|cursor|generic]
  ask       "question" --url U [--token T] [--no-llm]
  search    "query"
  pack      <project>
  note      --project my-agent --title "setup notes" --body "..."
  stats

Env: AGENT_MANAGER_URL, AGENT_MANAGER_TOKEN`;

main();
