#!/usr/bin/env node
/* agent-manager-brain — connect any coding agent to a shared brain.
 *
 *   agent-manager-brain connect --url https://host --token TOK --agent <platform>
 *   agent-manager-brain ask|search|pack|note|stats …
 *
 * Platforms: cursor, claude, vscode, copilot, windsurf, cline, continue,
 *            zed, codex, gemini, generic
 *
 * Env: AGENT_MANAGER_URL, AGENT_MANAGER_TOKEN
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
      ...(token ? { "X-Token": token, Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(`${res.status}: ${text.slice(0, 300)}`);
  return data;
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return {}; }
}

function writeJson(file, obj) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(obj, null, 2) + "\n");
  console.log(`wrote ${file}`);
}

function mcpEntry(url, token) {
  return token ? { url, headers: { "X-Token": token } } : { url };
}

function printGeneric(url, token, name) {
  console.log(`\nMCP config:\n`);
  console.log(JSON.stringify({ mcpServers: { [name]: mcpEntry(url, token) } }, null, 2));
}

function connect(args) {
  const base = requireBase(args);
  const url = base + "/mcp";
  const token = args.token || TOKEN || "";
  const name = args.name || "agent-manager";
  let agent = (args.agent || "generic").toLowerCase();
  if (agent === "copilot") agent = "vscode";

  if (agent === "claude") {
    const { spawnSync } = require("child_process");
    const hdr = token ? ["--header", `X-Token: ${token}`] : [];
    const r = spawnSync("claude",
      ["mcp", "add", "--transport", "http", name, url, ...hdr],
      { stdio: "inherit" });
    if (r.status === 0) {
      console.log(`\nAdded ${name} to Claude Code.`);
      return;
    }
    console.error("claude CLI not available — printing generic config.\n");
    return printGeneric(url, token, name);
  }

  if (agent === "cursor") {
    const file = path.join(os.homedir(), ".cursor", "mcp.json");
    const cur = readJson(file);
    cur.mcpServers = { ...(cur.mcpServers || {}), [name]: mcpEntry(url, token) };
    writeJson(file, cur);
    console.log("Restart Cursor to load it.");
    return;
  }

  if (agent === "vscode") {
    const file = path.join(process.cwd(), ".vscode", "mcp.json");
    const cur = readJson(file);
    cur.servers = {
      ...(cur.servers || {}),
      [name]: {
        type: "http",
        url,
        ...(token ? { headers: { "X-Token": token } } : {}),
      },
    };
    writeJson(file, cur);
    console.log("Reload VS Code / Copilot to load it.");
    return;
  }

  if (agent === "windsurf") {
    const file = path.join(os.homedir(), ".codeium", "windsurf", "mcp_config.json");
    const cur = readJson(file);
    cur.mcpServers = { ...(cur.mcpServers || {}), [name]: mcpEntry(url, token) };
    writeJson(file, cur);
    console.log("Reload Windsurf to load it.");
    return;
  }

  if (agent === "cline") {
    const candidates = [
      path.join(os.homedir(), "Library", "Application Support", "Code", "User", "globalStorage", "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json"),
      path.join(os.homedir(), ".config", "Code", "User", "globalStorage", "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json"),
      path.join(os.homedir(), "AppData", "Roaming", "Code", "User", "globalStorage", "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json"),
    ];
    const file = candidates.find(f => fs.existsSync(path.dirname(f))) || candidates[1];
    const cur = readJson(file);
    cur.mcpServers = { ...(cur.mcpServers || {}), [name]: mcpEntry(url, token) };
    writeJson(file, cur);
    console.log("Enable agent-manager inside Cline if it is not already on.");
    return;
  }

  if (agent === "continue") {
    const file = path.join(os.homedir(), ".continue", "config.yaml");
    fs.mkdirSync(path.dirname(file), { recursive: true });
    let text = "";
    try { text = fs.readFileSync(file, "utf8"); } catch {}
    const block = [
      "",
      "mcpServers:",
      `  - name: ${name}`,
      `    url: ${url}`,
      ...(token ? ["    headers:", `      X-Token: ${token}`] : []),
      "",
    ].join("\n");
    if (/mcpServers:\s*\n/.test(text)) {
      console.log(`\nAdd this under mcpServers in ${file}:\n`);
      console.log(block);
    } else {
      fs.writeFileSync(file, text.replace(/\s*$/, "") + block);
      console.log(`wrote ${file}`);
    }
    console.log("Reload the Continue extension.");
    return;
  }

  if (agent === "zed") {
    console.log("\nMerge this into Zed settings.json:\n");
    console.log(JSON.stringify({
      context_servers: {
        [name]: token ? { url, headers: { "X-Token": token } } : { url },
      },
    }, null, 2));
    return;
  }

  // codex, gemini, generic
  printGeneric(url, token, name);
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

const __doc = `agent-manager-brain — shared brain for any coding agent

  connect  --url https://host --token TOK --agent <platform>
           platforms: cursor claude vscode copilot windsurf cline
                      continue zed codex gemini generic
  ask      "question" --url U [--token T] [--no-llm]
  search   "query"
  pack     <project>
  note     --project my-agent --title "setup" --body "..."
  stats

Env: AGENT_MANAGER_URL, AGENT_MANAGER_TOKEN
UI:  {url}/connect/`;

main();
