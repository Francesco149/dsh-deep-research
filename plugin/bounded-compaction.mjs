/**
 * Bounded-checkpoint compaction engine for the local Qwen route.
 *
 * Part of dsh-deep-research (MIT). Installed to $DSH_INSTALL/plugins/bounded-compaction.mjs
 * by wizard/setup.py; mounted by the generated profile patch as every preset's
 * `compaction-basic` entry `name`. It must live inside the dsh install prefix so its bare
 * `@deepseek-ai/dsh-*` imports resolve against the harness's own node_modules.
 *
 * WHY THIS EXISTS
 * ---------------
 * `@deepseek-ai/dsh-compaction-basic` makes the checkpoint an accumulator: the
 * selected span always STARTS at the previous checkpoint message (region.ts
 * `selectCompactableRange` -> `surfaceNodes[firstIdx]`), so every compaction
 * replays the prior checkpoint plus the new history and asks the model to
 * "merge ... into a single consolidated summary". A model that obeys that
 * instruction by preserving every still-true fact instead of dropping stale
 * ones grows the checkpoint without bound, and two hard ceilings then lock the
 * session permanently:
 *
 *   1. `maxTokens` — the summarizer's output cap. Once the prior checkpoint
 *      plus the merge no longer fits, every call ends with finish=MAX_TOKENS
 *      and the engine throws "summarization truncated at the token cap
 *      (incomplete checkpoint)".
 *   2. the shrink check — `framedSummaryTokenCount >= shadowedRouteTokenCount`
 *      rejects a checkpoint that is no smaller than the span it replaces.
 *
 * The failure is self-locking: a failed compaction leaves the old checkpoint in
 * place, so the next attempt faces the same or a larger requirement. Measured
 * on a long Qwen3.8-Flash-Next coding session: the
 * checkpoint grew monotonically 9.6k -> 94.8k characters over 62 successful
 * compactions, output tokens tracked it 4.4k -> 32.7k, and once output reached
 * the 32768 cap every compaction failed after burning the full cap (~8.5 min
 * per step, once per step) while the conversation never shrank. Raising
 * `maxTokens` only moves the ceiling; it does not remove it.
 *
 * WHAT THIS CHANGES
 * -----------------
 * Three things, all on the sanctioned `summarize()` subclass hook:
 *
 *   - The compaction instruction gains a hard output budget. The stock text
 *     says only "preserve still-true facts, drop stale ones", which this model
 *     reads as "copy it forward"; the budget is what it actually obeys.
 *   - A `max-tokens` finish is ACCEPTED instead of thrown. A checkpoint cut at
 *     the cap still resumes the work; throwing is what makes the lock
 *     permanent.
 *   - The returned summary — and, on the way in, any over-budget prior
 *     checkpoint left by an older engine — is deterministically trimmed to
 *     `CHECKPOINT_BUDGET_CHARS` by dropping the least load-bearing sections
 *     first. This is the actual bound: it holds regardless of what the model
 *     does.
 *
 * The checkpoint is therefore bounded by construction, which is what makes the
 * summarizer's output bounded, which is what stops the ratchet.
 *
 * The section vocabulary, the `<compacted-summary>` framing, and every pricing
 * decision (pressure, retention, shrink validation) stay with the base engine;
 * only the summarization call is replaced.
 */
import { BasicCompactionEngine } from '@deepseek-ai/dsh-compaction-basic';
import { BlockAssembler, LlmError, contentHasImage } from '@deepseek-ai/dsh-llm';
import { deepFreeze } from '@deepseek-ai/dsh-util-values';

/** Hard ceiling for one checkpoint body, in characters (~8k tokens at 3 chars/token). */
const CHECKPOINT_BUDGET_CHARS = 24000;

/** Per-section ceiling, applied before the global budget. */
const SECTION_CAP_CHARS = {
  'Files and Code': 8000,
  'Key Technical Concepts': 3000,
  'Errors and Fixes': 3000,
};

/**
 * Sections by how much the NEXT step needs them, most load-bearing first. A
 * section absent from this list sorts after every listed one and takes only
 * what is left of the budget.
 */
const SECTION_PRIORITY = [
  'Current Work',
  'Next Step',
  'Critical Context',
  'Pending Jobs',
  'Primary Request and Intent',
  'Files and Code',
  'Key Technical Concepts',
  'Errors and Fixes',
];

const SUMMARY_OPEN_TAG = '<compacted-summary>';
const SUMMARY_CLOSE_TAG = '</compacted-summary>';

/**
 * The stock instruction with a budget rule appended. Kept byte-identical to
 * upstream otherwise: the replayed conversation prefix, the section list, and
 * the framing are all part of the cache-reuse contract.
 */
const COMPACTION_INSTRUCTION = [
  'You are now acting as a compaction engine for this AI coding assistant. Condense the conversation ABOVE into a structured checkpoint that lets another model resume the work with no loss of essential context.',
  '',
  'Output EXACTLY the Markdown structure below: keep every section, in order. Use terse bullets, not prose paragraphs. Write "(none)" for an empty section — never drop a section.',
  '',
  '## Primary Request and Intent',
  "- [the user's original and evolving goals; quote verbatim where the exact wording matters]",
  '',
  '## Key Technical Concepts',
  '- [technologies, frameworks, patterns, and conventions in play]',
  '',
  '## Files and Code',
  '- [exact path: why it matters, key changes or snippets]',
  '',
  '## Errors and Fixes',
  '- [error: how it was resolved, plus any related user feedback]',
  '',
  '## Pending Jobs',
  '- [explicitly requested work not yet completed]',
  '',
  '## Current Work',
  '- [precisely what was in progress at this checkpoint]',
  '',
  '## Next Step',
  '- [the single next action, directly in line with the most recent request, or "(none)"]',
  '',
  '## Critical Context',
  '- [decisions and their rationale, constraints, user preferences, open questions, data needed to continue]',
  '',
  'Rules:',
  '- Write concise English engineering prose. Preserve exact file paths, commands, error strings, identifiers, numeric values, function signatures, and syntax fragments.',
  '- Capture user feedback and explicit instructions faithfully, especially corrections.',
  '- Do NOT mention this summarization request or that the context was compacted.',
  '- Output only the checkpoint text: do not call any tool or take any other action.',
  `- If the conversation already contains a ${SUMMARY_OPEN_TAG} block, it is a PRIOR checkpoint. Do not copy it forward verbatim: preserve still-true facts, drop stale ones, and merge newer information into a single consolidated summary under the same structure.`,
  `- HARD LIMIT: the whole checkpoint MUST stay under ${CHECKPOINT_BUDGET_CHARS} characters (roughly 3500 words). It REPLACES the previous checkpoint, so it must be shorter than the input, never longer. Cut resolved detail, superseded decisions, and repeated code: keep exact paths, signatures and commands, not whole snippets.`,
].join('\n');

/**
 * Split a checkpoint body into `## ` sections, preserving order.
 * @param body - Markdown after the opening tag, before the closing one.
 * @returns one entry per section; text before the first heading is the preamble.
 */
function splitSections(body) {
  const sections = [];
  let current;
  for (const line of body.split('\n')) {
    const heading = /^##\s+(.*)$/.exec(line);
    if (heading !== null) {
      current = { title: heading[1].trim(), lines: [line] };
      sections.push(current);
    } else if (current === undefined) {
      current = { title: '', lines: [line] };
      sections.push(current);
    } else {
      current.lines.push(line);
    }
  }
  return sections;
}

/** Render a section, truncated to `budget` characters, cutting at a line boundary when one fits. */
function renderSection(section, budget) {
  const text = section.lines.join('\n');
  if (text.length <= budget) return text;
  const kept = [];
  let used = 0;
  for (const line of section.lines) {
    const cost = line.length + 1;
    if (used + cost <= budget) {
      kept.push(line);
      used += cost;
      continue;
    }
    // Nothing more fits whole: keep what a partial line can carry and stop.
    // Dropping the section instead would silently lose its heading too, and an
    // empty body is the one output the summarizer path rejects outright.
    const room = budget - used;
    if (room > 1) kept.push(line.slice(0, room - 1));
    break;
  }
  return kept.join('\n');
}

/**
 * Trim a checkpoint body to `budget` characters by dropping the least
 * load-bearing sections first, then re-emit in the original order.
 * @param body - the model's checkpoint text, without the framing tags.
 * @param budget - maximum characters to keep.
 * @returns the trimmed body, never longer than `budget`.
 */
export function boundCheckpoint(body, budget = CHECKPOINT_BUDGET_CHARS) {
  if (body.length <= budget) return body;
  const sections = splitSections(body);
  const rank = (title) => {
    const index = SECTION_PRIORITY.indexOf(title);
    return index === -1 ? SECTION_PRIORITY.length : index;
  };
  const ordered = [...sections].sort((a, b) => rank(a.title) - rank(b.title));
  const kept = new Map();
  let remaining = budget;
  for (const section of ordered) {
    if (remaining <= 0) break;
    const cap = SECTION_CAP_CHARS[section.title] ?? budget;
    const allowance = Math.min(cap, remaining);
    const text = renderSection(section, allowance);
    if (text.length === 0) continue;
    kept.set(section, text);
    remaining -= text.length + 1;
  }
  return sections
    .filter((section) => kept.has(section))
    .map((section) => kept.get(section))
    .join('\n');
}

/**
 * Replace an over-budget `<compacted-summary>` body inside one replayed
 * message, leaving every other block and message untouched.
 * @param message - derived conversation message from the summarizer input.
 * @returns the same message, or a shallow copy with a trimmed checkpoint.
 */
function boundCheckpointMessage(message) {
  if (message.role !== 'user' || !Array.isArray(message.content)) return message;
  if (!message.content.some((block) => block.type === 'text' && block.text.includes(SUMMARY_OPEN_TAG))) return message;
  const joined = message.content.map((block) => (block.type === 'text' ? block.text : '')).join('');
  const open = joined.indexOf(SUMMARY_OPEN_TAG);
  const close = joined.lastIndexOf(SUMMARY_CLOSE_TAG);
  if (open === -1 || close === -1 || close < open) return message;
  const head = joined.slice(0, open + SUMMARY_OPEN_TAG.length);
  const body = joined.slice(open + SUMMARY_OPEN_TAG.length, close);
  const tail = joined.slice(close);
  const trimmed = boundCheckpoint(body);
  if (trimmed === body) return message;
  return { ...message, content: [{ type: 'text', text: `${head}\n${trimmed}\n${tail}` }] };
}

/**
 * Compaction backend that keeps the checkpoint bounded no matter how the model
 * behaves. See the module header for why the stock engine deadlocks without it.
 */
export default class BoundedCompactionEngine extends BasicCompactionEngine {
  /**
   * Resolve the summarization route: the configured pair, else the latest
   * routed request, else the agent's own route.
   * @param agent - agent owning the session being compacted.
   * @returns the provider/model pair to summarize with.
   */
  resolveTarget(agent) {
    const latest = agent.session.requestHeader()?.config;
    const configured =
      this.config.summarizationProvider.length === 0
        ? undefined
        : { provider: this.config.summarizationProvider, model: this.config.summarizationModel };
    const own =
      agent.options.provider !== undefined && agent.options.model !== undefined
        ? { provider: agent.options.provider, model: agent.options.model }
        : undefined;
    const target = configured ?? latest ?? own;
    if (target === undefined) {
      throw new Error(
        'no provider/model available for summarization: set both BasicCompactionConfig summarization fields, route one request, or set both AgentOptions fields',
      );
    }
    return target;
  }

  /**
   * Replay the shadowed region through the no-thinking route, then bound the
   * result. Overrides the base engine's sole customization hook.
   * @param input - replayed conversation prefix (system, tools, and leading messages) to condense.
   * @param agent - supplies the routed target and session id.
   * @param signal - optional cancellation forwarded to the adapter.
   * @returns safe text-only summary blocks plus the exact call envelope.
   */
  async summarize(input, agent, signal) {
    const target = this.resolveTarget(agent);
    const messages = [
      ...input.messages.map(boundCheckpointMessage),
      deepFreeze({ role: 'user', content: [{ type: 'text', text: COMPACTION_INSTRUCTION }] }),
    ];
    const options = {
      provider: target.provider,
      model: target.model,
      messages,
      toolHistory: agent.session.toolHistory(),
      ...(input.tools === undefined ? {} : { tools: [...input.tools] }),
      maxTokens: this.config.maxTokens,
      sessionId: agent.session.id,
      purpose: 'compaction',
      ...(signal === undefined ? {} : { signal }),
    };
    const assembler = new BlockAssembler();
    for await (const chunk of this.ctx.llm.stream(options)) assembler.push(chunk);
    const finish = assembler.finish;
    if (finish.kind === 'error' || finish.kind === 'aborted') {
      throw new LlmError(finish.failure.message, finish.failure.code, finish.failure);
    }
    // A `max-tokens` finish is deliberately NOT an error here: the checkpoint
    // is trimmed below, and rejecting the partial output is what makes the
    // stock engine's lock permanent.
    const rawOutput = assembler.blocks();
    if (contentHasImage(rawOutput)) {
      throw new LlmError('compaction summary cannot contain image output', 'UNSUPPORTED_CONTENT');
    }
    const text = rawOutput
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('');
    const summary = [{ type: 'text', text: boundCheckpoint(text) }];
    if (summary[0].text.trim().length === 0) {
      throw new Error('summarization produced no text summary content');
    }
    return {
      summary,
      rawOutput,
      llmStreamCall: true,
      provider: options.provider,
      model: options.model,
      maxTokens: options.maxTokens,
      ...(assembler.usage === undefined ? {} : { usage: assembler.usage }),
    };
  }
}
