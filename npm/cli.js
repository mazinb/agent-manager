#!/usr/bin/env node
/* agent-manager-brain — connect any coding agent to a shared brain.
 *
 *   npx agent-manager-brain connect --url https://host --token TOK --agent <platform>
 *   npx agent-manager-brain init [--dir ~/agent-manager]
 *   npx agent-manager-brain serve [--dir DIR] [--port 8075]
 *   npx agent-manager-brain ask|search|pack|note|stats …
 *
 * Platforms: cursor, claude, vscode, copilot, windsurf, cline, continue,
 *            zed, codex, gemini, generic
 *
 * Env: AGENT_MANAGER_URL, AGENT_MANAGER_TOKEN, AGENT_MANAGER_HOME
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const REPO = "https://github.com/mazinb/agent-manager.git";
const DEFAULT_HOME = process.env.AGENT_MANAGER_HOME
  || path.join(os.homedir(), ".agent-manager", "app");

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

function ensureRepo(dir) {
  const server = path.join(dir, "server.py");
  if (fs.existsSync(server)) return dir;
  fs.mkdirSync(path.dirname(dir), { recursive: true });
  if (fs.existsSync(path.join(dir, ".git"))) {
    console.log(`updating ${dir}`);
    const r = spawnSync("git", ["-C", dir, "pull", "--ff-only"], { stdio: "inherit" });
    if (r.status !== 0) process.exit(r.status || 1);
  } else {
    console.log(`cloning ${REPO} → ${dir}`);
    const r = spawnSync("git", ["clone", "--depth", "1", REPO, dir], { stdio: "inherit" });
    if (r.status !== 0) process.exit(r.status || 1);
  }
  if (!fs.existsSync(server)) {
    console.error(`clone succeeded but ${server} is missing`);
    process.exit(1);
  }
  return dir;
}

function ensureEnv(dir, token) {
  const envPath = path.join(dir, ".env");
  if (fs.existsSync(envPath)) return envPath;
  const tok = token || TOKEN || require("crypto").randomBytes(16).toString("hex");
  fs.writeFileSync(envPath,
    `AGENT_MANAGER_TOKEN=${tok}\nAGENT_MANAGER_PORT=8075\n`);
  console.log(`wrote ${envPath}`);
  console.log(`token: ${tok}`);
  return envPath;
}

function ensureConfig() {
  const cfgDir = path.join(os.homedir(), ".config", "agent-manager");
  const cfg = path.join(cfgDir, "config.json");
  if (fs.existsSync(cfg)) return cfg;
  fs.mkdirSync(cfgDir, { recursive: true });
  const example = {
    _comment: "agent-manager brain config (token lives in .env)",
    db_path: path.join(os.homedir(), ".local", "share", "agent-manager", "brain.db"),
    rebuild_fts: true,
    llm: {},
    sources: [
      {
        type: "files",
        tag: "project_readme",
        roots: [path.join(os.homedir(), "projects", "*")],
        include: ["README.md"],
        max_depth: 2,
      },
      { type: "services" },
    ],
  };
  fs.writeFileSync(cfg, JSON.stringify(example, null, 2) + "\n");
  console.log(`wrote ${cfg}`);
  return cfg;
}

function initCmd(args) {
  const dir = path.resolve(args.dir || DEFAULT_HOME);
  ensureRepo(dir);
  const envPath = ensureEnv(dir, args.token);
  const cfg = ensureConfig();
  const tok = fs.readFileSync(envPath, "utf8").match(/AGENT_MANAGER_TOKEN=(.+)/)?.[1]?.trim();
  console.log(`\nSelf-host ready in ${dir}`);
  console.log(`\nNext:`);
  console.log(`  npx agent-manager-brain serve --dir ${dir}`);
  console.log(`  npx agent-manager-brain connect --url http://127.0.0.1:8075 --token ${tok || "YOUR_TOKEN"} --agent cursor`);
  console.log(`\nConfig: ${cfg}`);
  console.log(`UI:     http://127.0.0.1:8075/connect/`);
}

function serveCmd(args) {
  const dir = ensureRepo(path.resolve(args.dir || DEFAULT_HOME));
  ensureEnv(dir, args.token);
  ensureConfig();
  const port = String(args.port || process.env.AGENT_MANAGER_PORT || "8075");
  const py = process.env.PYTHON || "python3";
  const check = spawnSync(py, ["--version"], { encoding: "utf8" });
  if (check.status !== 0) {
    console.error("python3 is required to self-host the brain server.");
    console.error("Install Python 3.9+, then re-run: npx agent-manager-brain serve");
    process.exit(1);
  }
  console.log(`starting agent-manager on :${port} from ${dir}`);
  console.log(`connect UI: http://127.0.0.1:${port}/connect/`);
  console.log(`MCP:        http://127.0.0.1:${port}/mcp`);
  const child = spawn(py, ["server.py"], {
    cwd: dir,
    stdio: "inherit",
    env: {
      ...process.env,
      AGENT_MANAGER_PORT: port,
      AGENT_MANAGER_CONFIG:
        process.env.AGENT_MANAGER_CONFIG
        || path.join(os.homedir(), ".config", "agent-manager", "config.json"),
    },
  });
  child.on("exit", code => process.exit(code || 0));
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function waitFor(url, token, timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(url, { headers: token ? { "X-Token": token } : {} });
      if (res.ok) return true;
    } catch {}
    await sleep(500);
  }
  return false;
}

async function setupCmd(args) {
  const dir = path.resolve(args.dir || DEFAULT_HOME);
  const port = String(args.port || 8075);
  const base = `http://127.0.0.1:${port}`;
  ensureRepo(dir);
  const envPath = ensureEnv(dir, args.token);
  ensureConfig();
  const tok = fs.readFileSync(envPath, "utf8")
    .match(/AGENT_MANAGER_TOKEN=(.+)/)?.[1]?.trim() || "";
  const py = process.env.PYTHON || "python3";
  if (spawnSync(py, ["--version"], { encoding: "utf8" }).status !== 0) {
    console.error("python3 is required (3.9+). Install it and re-run setup.");
    process.exit(1);
  }

  let running = await waitFor(base + "/api/setup/status", tok, 1500);
  if (!running) {
    const homeDir = path.dirname(dir);
    const logPath = path.join(homeDir, "agent-manager.log");
    const pidPath = path.join(homeDir, "agent-manager.pid");
    const logFd = fs.openSync(logPath, "a");
    const child = spawn(py, ["server.py"], {
      cwd: dir, detached: true, stdio: ["ignore", logFd, logFd],
      env: { ...process.env, AGENT_MANAGER_PORT: port },
    });
    child.unref();
    fs.writeFileSync(pidPath, String(child.pid));
    console.log(`server starting (pid ${child.pid}, log ${logPath})`);
    running = await waitFor(base + "/api/setup/status", tok, 20000);
    if (!running) {
      console.error(`server did not come up on :${port} — check ${logPath}`);
      process.exit(1);
    }
  } else {
    console.log(`server already running on :${port}`);
  }

  process.stdout.write("ingesting sources… ");
  try {
    const r = await api(base, tok, "POST", "/api/refresh");
    console.log(`done (${r.sources ?? "?"} sources)`);
  } catch (e) { console.log(`skipped (${e.message})`); }

  if (args.agent) {
    await connect({ ...args, url: base, token: tok });
  } else {
    console.log(`\nConnect your agent:\n  npx agent-manager-brain connect --url ${base} --token ${tok} --agent cursor\n`);
  }
  console.log(`UI:  ${base}/`);
  console.log(`MCP: ${base}/mcp   (X-Token: value in ${envPath})`);
  console.log(`Stop: npx agent-manager-brain stop`);
}

function stopCmd(args) {
  const dir = path.resolve(args.dir || DEFAULT_HOME);
  const pidPath = path.join(path.dirname(dir), "agent-manager.pid");
  if (!fs.existsSync(pidPath)) { console.log("no pidfile — not running via setup"); return; }
  const pid = parseInt(fs.readFileSync(pidPath, "utf8").trim(), 10);
  try { process.kill(pid); console.log(`stopped pid ${pid}`); }
  catch (e) { console.log(`could not stop ${pid}: ${e.message}`); }
  fs.unlinkSync(pidPath);
}

function statePath() {
  return path.join(os.homedir(), ".agent-manager", "bootstrap-state.json");
}

function injectPath() {
  return path.join(os.homedir(), ".cursor", "rules", "agent-manager-bootstrap.mdc");
}

function loadBootstrapState() {
  return readJson(statePath());
}

function saveBootstrapState(state) {
  writeJson(statePath(), state);
}

/** Persist hashes client-side; rewrite inject rule only when packs changed. */
async function runBootstrap(base, token, args) {
  const prev = loadBootstrapState();
  const since = (prev.hashes && prev.hashes.session) || {};
  const contextHash = (prev.hashes && prev.hashes.context) || undefined;
  const project = args.project || prev.project || undefined;
  const chat = args.chat || prev.chat || "peers";
  const body = {
    project: project || null,
    chat,
    since_hashes: since,
    context_hash: contextHash || null,
    include_session: args["no-session"] ? false : true,
    include_context: args["no-context"] ? false : true,
  };
  let result;
  try {
    result = await api(base, token, "POST", "/api/session/bootstrap", body);
  } catch (e) {
    // Older brains may lack the endpoint — fall back to session-pack + context.
    const session = await api(base, token, "GET",
      "/api/roster/session-pack?chat=" + encodeURIComponent(chat)).catch(() => null);
    let context = null;
    if (project) {
      try {
        const pack = await api(base, token, "GET",
          "/api/context?project=" + encodeURIComponent(project));
        const crypto = require("crypto");
        const digest = crypto.createHash("sha256")
          .update(pack.pack || "", "utf8").digest("hex");
        context = { project, pack: pack.pack, content_hash: digest };
      } catch {}
    }
    const parts = [];
    if (session && session.pack) parts.push(session.pack);
    if (context && context.pack) parts.push("# Context pack — " + project + "\n\n" + context.pack);
    const ctxDigest = (context && context.content_hash) || null;
    const ctxUnchanged = !!(contextHash && ctxDigest && contextHash === ctxDigest);
    result = {
      ok: true,
      chat,
      project: project || null,
      instructions: "# Agent-manager session bootstrap\n\n" + (parts.join("\n") || "_(no packs)_") + "\n",
      session,
      context,
      hashes: {
        session: (session && session.hashes) || {},
        context: ctxDigest,
        chat,
        project: project || null,
      },
      changed: !(ctxUnchanged && session && Object.keys(since).length),
      skipped: { fallback: e.message, ...(ctxUnchanged ? { context: "unchanged" } : {}) },
      chars: 0,
    };
    result.chars = result.instructions.length;
  }

  const next = {
    url: base,
    agent: args.agent || prev.agent || "",
    chat: result.chat || chat,
    project: result.project || project || null,
    hashes: {
      session: Object.assign({}, since, (result.hashes && result.hashes.session) || {}),
      context: (result.hashes && result.hashes.context) || contextHash || null,
    },
    last_chars: result.chars,
    last_changed: !!result.changed,
  };
  saveBootstrapState(next);

  if (result.changed || !fs.existsSync(injectPath())) {
    const bodyMd = [
      "---",
      "description: Auto-injected agent-manager session/context packs (connect bootstrap).",
      "alwaysApply: true",
      "---",
      "",
      result.instructions || "",
      "",
    ].join("\n");
    fs.mkdirSync(path.dirname(injectPath()), { recursive: true });
    fs.writeFileSync(injectPath(), bodyMd);
    console.log(`wrote ${injectPath()} (${result.chars || bodyMd.length} chars)`);
  } else {
    console.log("bootstrap packs unchanged — skipped re-inject (hashes match)");
  }
  return result;
}

async function connect(args) {
  const base = requireBase(args);
  // ?project=X pins a default project for search/ask calls through this MCP URL
  const url = base + "/mcp" +
    (args.project ? "?project=" + encodeURIComponent(args.project) : "");
  const token = args.token || TOKEN || "";
  const name = args.name || "agent-manager";
  let agent = (args.agent || "generic").toLowerCase();
  if (agent === "copilot") agent = "vscode";

  if (agent === "claude") {
    const hdr = token ? ["--header", `X-Token: ${token}`] : [];
    const r = spawnSync("claude",
      ["mcp", "add", "--transport", "http", name, url, ...hdr],
      { stdio: "inherit" });
    if (r.status === 0) {
      console.log(`\nAdded ${name} to Claude Code.`);
      if (!args["no-bootstrap"] && token) {
        try { await runBootstrap(base, token, args); }
        catch (e) { console.error("bootstrap skipped: " + e.message); }
      }
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
    if (!args["no-bootstrap"] && token) {
      try { await runBootstrap(base, token, args); }
      catch (e) { console.error("bootstrap skipped: " + e.message); }
    }
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
  } else if (agent === "windsurf") {
    const file = path.join(os.homedir(), ".codeium", "windsurf", "mcp_config.json");
    const cur = readJson(file);
    cur.mcpServers = { ...(cur.mcpServers || {}), [name]: mcpEntry(url, token) };
    writeJson(file, cur);
    console.log("Reload Windsurf to load it.");
  } else if (agent === "cline") {
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
  } else if (agent === "continue") {
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
  } else if (agent === "zed") {
    console.log("\nMerge this into Zed settings.json:\n");
    console.log(JSON.stringify({
      context_servers: {
        [name]: token ? { url, headers: { "X-Token": token } } : { url },
      },
    }, null, 2));
  } else if (agent !== "cursor" && agent !== "claude") {
    printGeneric(url, token, name);
  }

  if (!args["no-bootstrap"] && token && agent !== "cursor" && agent !== "claude") {
    // cursor/claude already bootstrapped above before return
    try { await runBootstrap(base, token, args); }
    catch (e) { console.error("bootstrap skipped: " + e.message); }
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0] || "help";
  try {
    if (cmd === "connect") return await connect(args);
    if (cmd === "bootstrap") {
      const base = requireBase(args);
      const token = args.token || TOKEN;
      if (!token) {
        console.error("bootstrap needs --token or AGENT_MANAGER_TOKEN");
        process.exit(1);
      }
      const result = await runBootstrap(base, token, args);
      console.log(JSON.stringify({
        ok: result.ok, changed: result.changed, skipped: result.skipped,
        chat: result.chat, project: result.project, chars: result.chars,
        hashes: result.hashes,
      }, null, 2));
      return;
    }
    if (cmd === "init") return initCmd(args);
    if (cmd === "serve") return serveCmd(args);
    if (cmd === "setup") return await setupCmd(args);
    if (cmd === "stop") return stopCmd(args);
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
      const sp = new URLSearchParams({ q: args._.slice(1).join(" ") });
      if (args.project) sp.set("project", args.project);
      if (args["include-stale"]) sp.set("include_stale", "true");
      out = await api(base, token, "GET", "/api/search?" + sp);
    } else if (cmd === "pack") {
      out = await api(base, token, "GET",
        "/api/context?project=" + encodeURIComponent(args._[1] || ""));
      console.log(out.pack); return;
    } else if (cmd === "note") {
      out = await api(base, token, "POST", "/api/note",
        { project: args.project, title: args.title || "untitled", body: args.body,
          ...(args.confidence !== undefined ? { confidence: parseFloat(args.confidence) } : {}),
          ...(args.sources ? { sources: String(args.sources).split(",").map(s => s.trim()) } : {}) });
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
           [--project X]  pin a default project for search/ask via ?project=
           [--no-bootstrap]  skip auto session_pack/context_pack inject
           platforms: cursor claude vscode copilot windsurf cline
                      continue zed codex gemini generic
  bootstrap --url https://host --token TOK [--project X] [--chat peers]
           Fetch session_pack + context_pack; persist hashes under
           ~/.agent-manager/bootstrap-state.json; rewrite
           ~/.cursor/rules/agent-manager-bootstrap.mdc only when changed
  setup    [--agent X] [--port 8075] [--dir DIR] [--token TOK]
           ONE COMMAND self-host: clone + config + start server
           (background) + ingest + connect an agent
  stop     [--dir DIR]                    stop a setup-started server
  init     [--dir ~/.agent-manager/app]   clone + write .env/config
  serve    [--dir DIR] [--port 8075]      run local brain (needs python3)
  ask|search|pack|note|stats              query a running brain

Self-host (one command):
  npx agent-manager-brain setup --agent cursor

Self-host (manual):
  npx agent-manager-brain init
  npx agent-manager-brain serve
  npx agent-manager-brain connect --url http://127.0.0.1:8075 --token TOK --agent cursor

Env: AGENT_MANAGER_URL, AGENT_MANAGER_TOKEN, AGENT_MANAGER_HOME
UI:  {url}/connect/   npm: agent-manager-brain`;

main();
