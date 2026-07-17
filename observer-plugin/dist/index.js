// @ts-nocheck
import { appendFileSync, mkdirSync, readFileSync, existsSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";
import { homedir } from "node:os";
import { spawn } from "node:child_process";
const EVENTS_DIR = join(homedir(), ".openclaw", "redteam-observer");
const EVENTS_PATH = join(EVENTS_DIR, "events.jsonl");
const RUNS_DIR = join(EVENTS_DIR, "runs");
const API_PORT = Number(process.env.OPENCLAW_OBSERVER_PORT ?? 18790);
mkdirSync(EVENTS_DIR, { recursive: true });
mkdirSync(RUNS_DIR, { recursive: true });
// Per-session run_id stored in individual files under runs/.
// File-based IPC is required because the observer plugin loads in both the
// gateway process (which handles /run/start) and each CLI subprocess
// (which fires hooks). In-memory state is not shared across these processes.
function runFile(ocSession) {
    // Sanitise so the session key is safe as a filename
    return join(RUNS_DIR, ocSession.replace(/[^a-zA-Z0-9_\-]/g, "_"));
}
function getRunId(ocSession) {
    const f = runFile(ocSession);
    try {
        if (!existsSync(f))
            return null;
        return readFileSync(f, "utf-8").trim() || null;
    }
    catch {
        return null;
    }
}
function setRunId(ocSession, runId) {
    const f = runFile(ocSession);
    try {
        writeFileSync(f, runId ?? "", "utf-8");
    }
    catch { }
}
function writeEvent(event) {
    let runId = null;
    if (event.session_id) {
        runId = getRunId(event.session_id);
    }
    const enriched = runId
        ? { ...event, attack_run_id: event.attack_run_id ?? runId }
        : event;
    appendFileSync(EVENTS_PATH, JSON.stringify(enriched) + "\n", "utf-8");
}
function readEvents(since, attackRunId) {
    if (!existsSync(EVENTS_PATH))
        return [];
    const sinceMs = since ? new Date(since).getTime() : 0;
    // Walk all events chronologically, carry attack_method forward from prompt events
    const all = readFileSync(EVENTS_PATH, "utf-8")
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line))
        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
    let currentAttackMethod = null;
    let currentSessionId = null;
    const enriched = all.map((e) => {
        if (e.phase === "prompt") {
            if (e.attack_method)
                currentAttackMethod = e.attack_method;
            if (e.session_id)
                currentSessionId = e.session_id;
        }
        const method = e.attack_method ?? currentAttackMethod;
        const sid = e.session_id ?? currentSessionId;
        return {
            ...e,
            ...(method ? { attack_method: method } : {}),
            ...(sid ? { session_id: sid } : {}),
        };
    });
    return enriched.filter((e) => {
        if (since && new Date(e.timestamp).getTime() < sinceMs)
            return false;
        if (attackRunId && e.attack_run_id !== attackRunId)
            return false;
        return true;
    });
}
function startApi(port) {
    const server = createServer((req, res) => {
        const url = new URL(req.url, `http://localhost`);
        if (req.method === "GET" && url.pathname === "/health") {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ ok: true }));
            return;
        }
        if (req.method === "GET" && url.pathname === "/events") {
            const since = url.searchParams.get("since") ?? undefined;
            const attackRunId = url.searchParams.get("attack_run_id") ?? undefined;
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ events: readEvents(since, attackRunId) }));
            return;
        }
        if (req.method === "POST" && url.pathname === "/run/start") {
            let body = "";
            req.on("data", (chunk) => { body += chunk; });
            req.on("end", () => {
                try {
                    const { run_id, oc_session } = JSON.parse(body);
                    if (run_id && oc_session) {
                        setRunId(oc_session, run_id);
                    }
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: true, run_id, oc_session }));
                }
                catch (e) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: false, error: String(e) }));
                }
            });
            return;
        }
        if (req.method === "POST" && url.pathname === "/run/end") {
            let body = "";
            req.on("data", (chunk) => { body += chunk; });
            req.on("end", () => {
                try {
                    const { oc_session } = JSON.parse(body || "{}");
                    if (oc_session) {
                        setRunId(oc_session, null);
                    }
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: true }));
                }
                catch (e) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: false, error: String(e) }));
                }
            });
            return;
        }
        if (req.method === "POST" && url.pathname === "/events") {
            let body = "";
            req.on("data", (chunk) => { body += chunk; });
            req.on("end", () => {
                try {
                    const event = JSON.parse(body);
                    writeEvent({ ...event, timestamp: event.timestamp ?? new Date().toISOString() });
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: true }));
                }
                catch (e) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: false, error: String(e) }));
                }
            });
            return;
        }
        if (req.method === "DELETE" && url.pathname === "/events") {
            writeFileSync(EVENTS_PATH, "", "utf-8");
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ ok: true }));
            return;
        }
        res.writeHead(404);
        res.end("Not Found");
    });
    server.on("error", (err) => {
        if (err.code === "EADDRINUSE")
            return;
        console.error(`[redteam-observer] server error: ${err.message}`);
    });
    server.listen(port, () => {
        console.log(`[redteam-observer] API listening on :${port}`);
    });
}
export default {
    id: "redteam-observer",
    name: "Red Team Observer",
    description: "Records tool call events for security red team validation.",
    register(api) {
        startApi(API_PORT);
        api.logger?.info?.("[redteam-observer] observer plugin loaded");
        api.registerHttpRoute({
            path: "/run",
            auth: "gateway",
            match: "exact",
            handler: async (req, res) => {
                if (req.method !== "POST") {
                    res.writeHead(405, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: false, error: "Method Not Allowed" }));
                    return;
                }
                let body = "";
                await new Promise((resolve) => {
                    req.on("data", (chunk) => { body += chunk; });
                    req.on("end", resolve);
                });
                try {
                    const { scenario_id = "redteam-default", prompt = "" } = JSON.parse(body);
                    const { stdout, stderr, code } = await new Promise((resolve) => {
                        const child = spawn("openclaw", ["agent", "--session-id", scenario_id, "--message", prompt, "--json"], { encoding: "utf-8" });
                        let out = "", err = "";
                        child.stdout.on("data", (d) => { out += d; });
                        child.stderr.on("data", (d) => { err += d; });
                        child.on("close", (code) => resolve({ stdout: out, stderr: err, code }));
                    });
                    if (code !== 0) {
                        res.writeHead(500, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ ok: false, error: stderr.trim() }));
                    }
                    else {
                        res.writeHead(200, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ ok: true, stdout: stdout.trim() }));
                    }
                }
                catch (e) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ ok: false, error: String(e) }));
                }
            },
        });
        api.on("before_tool_call", async (event) => {
            writeEvent({
                tool_name: String(event?.toolName ?? ""),
                tool_args: event?.params ?? {},
                executed: false,
                timestamp: new Date().toISOString(),
                phase: "before_tool_call",
                session_id: event?.sessionId ?? null,
                run_id: event?.runId ?? null,
            });
            return {};
        });
        api.on("after_tool_call", (event) => {
            writeEvent({
                tool_name: String(event?.toolName ?? ""),
                tool_args: event?.params ?? {},
                tool_result: event?.result ?? null,
                tool_error: event?.error ?? null,
                duration_ms: event?.durationMs ?? null,
                executed: true,
                timestamp: new Date().toISOString(),
                phase: "after_tool_call",
                session_id: event?.sessionId ?? null,
                run_id: event?.runId ?? null,
            });
        });
        api.on("llm_output", (event) => {
            const content = Array.isArray(event?.assistantTexts)
                ? event.assistantTexts.join("\n")
                : (event?.assistantTexts ?? "");
            const stopReason = event?.stopReason ?? null;
            const usage = event?.usage ?? null;
            writeEvent({
                tool_name: "llm_response",
                tool_args: {
                    content,
                    model: event?.model ?? null,
                    provider: event?.provider ?? null,
                    usage,
                    stop_reason: stopReason,
                },
                executed: true,
                timestamp: new Date().toISOString(),
                phase: "llm_response",
                session_id: event?.sessionId ?? null,
                run_id: event?.runId ?? null,
            });
            // Emit a synthetic content_filter event when the provider blocks the request.
            // Detected by: empty content + null usage (no tokens consumed), OR explicit
            // stopReason indicating a filter (varies by provider: "content_filter",
            // "content_filtered", "error", etc.).
            const isFiltered = (content === "" && usage === null) ||
                (typeof stopReason === "string" && /filter|blocked|safety/i.test(stopReason));
            if (isFiltered) {
                writeEvent({
                    tool_name: "content_filter",
                    tool_args: {
                        reason: stopReason ?? "empty response with no token usage (provider-side block)",
                        model: event?.model ?? null,
                    },
                    executed: true,
                    timestamp: new Date().toISOString(),
                    phase: "content_filter",
                    session_id: event?.sessionId ?? null,
                    run_id: event?.runId ?? null,
                });
            }
        });
    },
};
