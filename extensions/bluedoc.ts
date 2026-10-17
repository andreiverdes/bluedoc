/**
 * bluedoc for omp and pi: the plan gate and the /bluedoc-* commands.
 *
 * omp: a plan_review_requested handler opens the plan as a bluedoc plan page (hook.py ext open) and, in the
 *   background, waits for the reader (hook.py ext wait): Approve answers the review with "execute", Request changes
 *   with "refine" and the reply as feedback. The terminal picker stays live; the first answer wins.
 * pi: pi has no plan mode, so /bluedoc-plan-mode turns one on: the agent writes its plan to a Markdown file and calls
 *   bluedoc_submit_plan, which opens the page and returns the reader's approval or change request.
 * Both: the /bluedoc-<name> commands from commands/commands.json. omp also loads commands/*.md, but as
 *   /bluedoc:bluedoc-<name> and without running their !`…` shell lines, so the action commands only work from here.
 *
 * Only omp has ctx.resolvePlanReview; that is how the two are told apart. Python does all the bluedoc work: this file
 * only runs the two hook.py ext CLIs and the commands' scripts. No dependencies.
 */
import { type ChildProcess, spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const SCRIPTS = join(ROOT, "skills", "bluedoc", "scripts");
const HOOK = join(SCRIPTS, "hook.py");
const PLAN_MODE_ENTRY = "bluedoc.plan-mode";
const SUBMIT_TOOL = "bluedoc_submit_plan";

// The host APIs, as far as this file uses them. pi and omp share these shapes; omp adds the plan review members.
interface PlanReview {
	reviewId: string;
	/** omp's field name (the omp docs call it "plan path"); read from omp 18.11.3's plan_review_requested event. */
	planFilePath?: string;
	planContent?: string;
}
interface Ctx {
	cwd: string;
	hasUI: boolean;
	ui: { notify(message: string, level?: "info" | "warning" | "error"): void };
	sessionManager: { getSessionId(): string; getBranch(): Array<{ type: string; customType?: string; data?: unknown }> };
	isIdle(): boolean;
	agent?: { kind: "main" | "sub" };
	resolvePlanReview?(reviewId: string, choice: "execute" | "refine", input?: { feedback?: string }): boolean;
	getPendingPlanReview?(): PlanReview | undefined;
}
interface ToolResult {
	content: Array<{ type: "text"; text: string }>;
	details: Record<string, never>;
	isError?: boolean;
}
interface Api {
	on<E>(event: string, handler: (event: E, ctx: Ctx) => unknown): void;
	registerCommand(name: string, options: { description?: string; handler(args: string, ctx: Ctx): Promise<void> }): void;
	registerTool(tool: {
		name: string;
		label: string;
		description: string;
		/** pi lists a custom tool in the system prompt's tools section only when it has this. */
		promptSnippet?: string;
		promptGuidelines?: string[];
		parameters: object;
		execute(id: string, params: { path?: string }, signal: AbortSignal | undefined, onUpdate: unknown, ctx: Ctx): Promise<ToolResult>;
	}): void;
	sendUserMessage(content: string, options?: { deliverAs?: "steer" | "followUp" }): void;
	appendEntry(customType: string, data?: unknown): void;
}

/** One entry of commands/commands.json; the command is /bluedoc-<name>. */
interface CommandSpec {
	name: string;
	description: string;
	args?: string;
	kind: "prompt" | "action";
	prompt?: string;
	run?: { script: string; args: string[] };
}
type Gate =
	| { state: "skip"; why: string }
	| { state: "approved"; doc: string; rev: string; note: string }
	| { state: "opened"; doc: string; url: string; message: string };
type Reply = { kind: "approval" | "changes"; md: string; rev?: string };
interface Run {
	stdout: string;
	stderr: string;
	/** null when the process was killed. */
	code: number | null;
}
interface RunOptions {
	cwd: string;
	stdin?: string;
	signal?: AbortSignal;
	onChild?(child: ChildProcess): void;
}

/** Runs python3 with args; stdin is written and closed. Never rejects. */
function python(args: string[], options: RunOptions): Promise<Run> {
	const { promise, resolve: done } = Promise.withResolvers<Run>();
	let stdout = "";
	let stderr = "";
	const child = spawn("python3", args, { cwd: options.cwd, stdio: ["pipe", "pipe", "pipe"] });
	options.onChild?.(child);
	const abort = () => child.kill();
	options.signal?.addEventListener("abort", abort, { once: true });
	child.stdout.setEncoding("utf8").on("data", chunk => (stdout += chunk));
	child.stderr.setEncoding("utf8").on("data", chunk => (stderr += chunk));
	child.on("error", error => {
		options.signal?.removeEventListener("abort", abort);
		done({ stdout, stderr: stderr || String(error), code: -1 });
	});
	child.on("close", code => {
		options.signal?.removeEventListener("abort", abort);
		done({ stdout, stderr, code });
	});
	child.stdin.on("error", () => {});
	child.stdin.end(options.stdin ?? "");
	return promise;
}

function firstLine(text: string): string {
	return text.split("\n").find(line => line.trim())?.trim() ?? "";
}

function message(error: unknown): string {
	return firstLine(error instanceof Error ? error.message : String(error));
}

/** Runs `hook.py ext <args>` and parses its JSON; undefined when killed; throws hook.py's error line on failure. */
async function hookExt<T>(args: string[], options: RunOptions): Promise<T | undefined> {
	const run = await python([HOOK, "ext", ...args], options);
	if (run.code === null || options.signal?.aborted) return undefined;
	if (run.code !== 0) throw new Error(firstLine(run.stderr) || `hook.py ext ${args[0]} exited with ${run.code}`);
	return JSON.parse(run.stdout) as T;
}

function openGate(text: string, planPath: string | undefined, ctx: Ctx, agent: "omp" | "pi", signal?: AbortSignal) {
	// planPath may be omp's `local://…` URL: hook.py names the doc from it and imports `text`.
	const stdin = JSON.stringify({ text, planPath: planPath ?? null, cwd: ctx.cwd, sessionId: ctx.sessionManager.getSessionId(), agent });
	return hookExt<Gate>(["open"], { cwd: ctx.cwd, stdin, signal });
}

/** Splits a command line shell-style: whitespace separates words, single and double quotes group them. */
function splitArgs(line: string): string[] {
	const words: string[] = [];
	let word = "";
	let quote = "";
	let started = false;
	for (const ch of line) {
		if (quote) {
			if (ch === quote) quote = "";
			else word += ch;
		} else if (ch === "'" || ch === '"') {
			quote = ch;
			started = true;
		} else if (/\s/.test(ch)) {
			if (started) words.push(word);
			word = "";
			started = false;
		} else {
			word += ch;
			started = true;
		}
	}
	if (started) words.push(word);
	return words;
}

export default function bluedoc(pi: Api) {
	// ── Commands (pi and omp) ────────────────────────────────────────────────
	let commandsError: string | undefined;
	let specs: CommandSpec[] = [];
	try {
		specs = JSON.parse(readFileSync(join(ROOT, "commands", "commands.json"), "utf8")) as CommandSpec[];
	} catch (error) {
		commandsError = message(error);
	}
	for (const spec of specs) {
		pi.registerCommand(`bluedoc-${spec.name}`, {
			description: spec.args ? `${spec.description} ${spec.args}` : spec.description,
			handler: async (args, ctx) => {
				if (spec.kind === "prompt") {
					const prompt = (spec.prompt ?? "").replaceAll("{{args}}", args.trim());
					pi.sendUserMessage(prompt, ctx.isIdle() ? undefined : { deliverAs: "followUp" });
					return;
				}
				if (!spec.run) return;
				// "{{args}}" alone stands for the words of args (none when empty); inside a longer arg, for the raw text.
				const argv = spec.run.args.flatMap(arg => (arg === "{{args}}" ? splitArgs(args) : [arg.replaceAll("{{args}}", args.trim())]));
				const run = await python([join(SCRIPTS, spec.run.script), ...argv], { cwd: ctx.cwd });
				// The script's whole output: one line for most, a Markdown block for replies.
				if (run.code === 0) ctx.ui.notify(run.stdout.trim() || `/bluedoc-${spec.name}: done`, "info");
				else ctx.ui.notify(`/bluedoc-${spec.name}: ${firstLine(run.stderr) || `exited with ${run.code}`}`, "error");
			},
		});
	}

	// ── omp: plan_review_requested ───────────────────────────────────────────
	// One background watcher per open review: resolved marks it done, child is its running `hook.py ext wait`.
	const watchers = new Map<string, { resolved: boolean; child?: ChildProcess }>();

	function stopWatcher(reviewId: string) {
		const watcher = watchers.get(reviewId);
		if (!watcher) return;
		watcher.resolved = true;
		watcher.child?.kill();
		watchers.delete(reviewId);
	}

	async function watchReview(review: PlanReview, ctx: Ctx) {
		const watcher: { resolved: boolean; child?: ChildProcess } = { resolved: false };
		watchers.set(review.reviewId, watcher);
		try {
			const gate = await openGate(review.planContent ?? "", review.planFilePath, ctx, "omp");
			if (!gate || watcher.resolved || gate.state === "skip") return;
			if (gate.state === "approved") {
				ctx.ui.notify(gate.note, "info");
				ctx.resolvePlanReview?.(review.reviewId, "execute", {});
				return;
			}
			ctx.ui.notify(`bluedoc: the plan is open at ${gate.url}. Approve or request changes there, or answer here.`, "info");
			// A reply the review can't take (an empty change request) leaves it open: wait for the next one.
			while (!watcher.resolved) {
				const reply = await hookExt<Reply>(["wait", gate.doc], { cwd: ctx.cwd, onChild: child => (watcher.child = child) });
				watcher.child = undefined;
				if (!reply || watcher.resolved) return;
				const answered =
					reply.kind === "approval"
						? ctx.resolvePlanReview?.(review.reviewId, "execute", {})
						: ctx.resolvePlanReview?.(review.reviewId, "refine", { feedback: reply.md });
				if (answered) return;
			}
		} catch (error) {
			if (!watcher.resolved) ctx.ui.notify(`bluedoc: ${message(error)}`, "warning");
		} finally {
			if (watchers.get(review.reviewId) === watcher) watchers.delete(review.reviewId);
		}
	}

	function onReview(review: PlanReview | undefined, ctx: Ctx) {
		if (!review || !ctx.resolvePlanReview || !ctx.hasUI || ctx.agent?.kind === "sub" || watchers.has(review.reviewId)) return;
		// omp closes the review only after every plan_review_requested handler returns: hand the wait off.
		void watchReview(review, ctx);
	}

	pi.on<PlanReview>("plan_review_requested", (event, ctx) => onReview(event, ctx));
	pi.on<{ reviewId: string }>("plan_review_resolved", event => stopWatcher(event.reviewId));
	pi.on("session_shutdown", () => {
		for (const reviewId of [...watchers.keys()]) stopWatcher(reviewId);
	});

	// ── pi: plan mode ────────────────────────────────────────────────────────
	let planMode: { on: boolean; file?: string } = { on: false };
	let planModeRegistered = false;

	function setPlanMode(next: { on: boolean; file?: string }) {
		planMode = next;
		pi.appendEntry(PLAN_MODE_ENTRY, next);
	}

	function text(lines: string, isError = false): ToolResult {
		return { content: [{ type: "text", text: lines }], details: {}, isError };
	}

	function registerPlanMode() {
		pi.registerCommand("bluedoc-plan-mode", {
			description: "Toggle bluedoc plan mode: the agent's plan opens as a bluedoc page for approval [file.md]",
			handler: async (args, ctx) => {
				const file = args.trim() || undefined;
				if (planMode.on && !file) {
					setPlanMode({ on: false });
					ctx.ui.notify("bluedoc plan mode off", "info");
					return;
				}
				setPlanMode({ on: true, file });
				ctx.ui.notify(`bluedoc plan mode on: the next plan goes to ${file ?? "plans/<slug>.md"} and opens as a bluedoc page`, "info");
			},
		});

		pi.registerTool({
			name: SUBMIT_TOOL,
			label: "bluedoc: submit plan",
			description:
				"Open a Markdown plan file as a bluedoc plan page and wait for the user's review. " +
				"Returns 'Approved:' with the user's notes, or 'Changes requested:' with the changes to make; " +
				`after changes, edit the same file and call ${SUBMIT_TOOL} again.`,
			// Without a snippet pi leaves the tool out of the system prompt's tool list, and models that trust that list
			// (a local qwen in the beta19 live test) decide the tool doesn't exist and route it through `mcp` instead.
			promptSnippet: "Open a Markdown plan file as a bluedoc page for the user's review and wait for the answer",
			promptGuidelines: [`In bluedoc plan mode, call ${SUBMIT_TOOL} directly (it is a native tool, not an MCP tool).`],
			parameters: {
				type: "object",
				properties: { path: { type: "string", description: "Path of the Markdown plan file, relative to the working directory" } },
				required: ["path"],
			},
			async execute(_id, params, signal, _onUpdate, ctx) {
				const path = params.path?.trim();
				if (!path) return text(`${SUBMIT_TOOL} needs the path of the plan file`, true);
				const file = isAbsolute(path) ? path : resolve(ctx.cwd, path);
				let plan: string;
				try {
					plan = readFileSync(file, "utf8");
				} catch (error) {
					return text(`Can't read ${path}: ${message(error)}`, true);
				}
				try {
					const gate = await openGate(plan, file, ctx, "pi", signal);
					if (!gate) return text("Cancelled before the plan opened.", true);
					if (gate.state === "skip") return text(`bluedoc can't show the plan here (${gate.why}). Ask the user to approve the plan in the chat.`);
					if (gate.state === "approved") {
						if (planMode.on) setPlanMode({ on: false });
						return text(`Approved:\n${gate.note}`);
					}
					ctx.ui.notify(`bluedoc: the plan is open at ${gate.url}`, "info");
					const reply = await hookExt<Reply>(["wait", gate.doc], { cwd: ctx.cwd, signal });
					if (!reply) return text("Cancelled before the user answered.", true);
					if (reply.kind === "approval") {
						if (planMode.on) setPlanMode({ on: false });
						return text(`Approved:\n${reply.md}`);
					}
					return text(`Changes requested:\n${reply.md}`);
				} catch (error) {
					return text(`bluedoc: ${message(error)}`, true);
				}
			},
		});
	}

	pi.on("session_start", (_event, ctx) => {
		if (commandsError) ctx.ui.notify(`bluedoc: no /bluedoc-* commands (${commandsError})`, "warning");
		if (ctx.resolvePlanReview) {
			// omp: a review that opened before this extension loaded.
			onReview(ctx.getPendingPlanReview?.(), ctx);
			return;
		}
		planMode = { on: false };
		for (const entry of ctx.sessionManager.getBranch()) {
			if (entry.type === "custom" && entry.customType === PLAN_MODE_ENTRY) planMode = entry.data as typeof planMode;
		}
		// Registered here, not at load, so omp (which has its own plan mode) never gets them.
		if (!planModeRegistered) {
			planModeRegistered = true;
			registerPlanMode();
		}
	});

	pi.on<{ systemPrompt: string }>("before_agent_start", event => {
		if (!planMode.on) return;
		const file = planMode.file ?? "plans/<slug>.md (a short kebab-case name for the plan)";
		return {
			systemPrompt:
				`${event.systemPrompt}\n\n## bluedoc plan mode\n` +
				`Write the plan as Markdown to ${file}, then call ${SUBMIT_TOOL} with its path. ` +
				`Don't change other files until ${SUBMIT_TOOL} returns "Approved:". ` +
				`On "Changes requested:", revise the same file and call ${SUBMIT_TOOL} again.`,
		};
	});
}
