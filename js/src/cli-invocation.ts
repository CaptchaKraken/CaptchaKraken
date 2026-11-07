import type { PromptFamily, RetryMode, Vendor } from './kinds.js';
import type { CliResponse } from './types.js';

// The key travels in env, never argv: argv is world-readable on Linux via /proc/<pid>/cmdline and `ps`. See TRIBAL_KNOWLEDGE.md.
export const API_KEY_ENV = 'CAPTCHA_KRAKEN_API_KEY';


export const API_PROVIDER = 'captchaKrakenApi';

export interface SolveInvocation {
  imagePath: string;

  model?: string;
  puzzleSource: Vendor;
  retryMode?: RetryMode | null;
  textMode?: boolean;

  expert?: PromptFamily | null;
  /** Earlier screens of the same paged puzzle, oldest first. */
  history?: string[];
}

/** An argv array for execFile, never a shell string. */
export function buildSolveArgs(invocation: SolveInvocation): string[] {
  const { imagePath, model, puzzleSource, retryMode, textMode, expert, history } =
    invocation;

  const args = ['-m', 'captchakraken.cli', imagePath];
  // Both positionals or neither: the provider passed alone would bind to `model`.
  if (model) args.push(model, API_PROVIDER);
  args.push(`--puzzle-source=${puzzleSource}`);
  if (retryMode) args.push(`--retry-mode=${retryMode}`);
  if (textMode) args.push('--text-mode');
  for (const screen of history ?? []) args.push(`--history=${screen}`);

  if (expert) args.push(`--expert=${expert}`);
  return args;
}

export function solveEnv(base: NodeJS.ProcessEnv, apiKey?: string): NodeJS.ProcessEnv {
  return apiKey ? { ...base, [API_KEY_ENV]: apiKey } : { ...base };
}

export function redactCommand(command: string, apiKey?: string): string {
  if (!apiKey) return command;
  return command.split(apiKey).join('***');
}

/** What the CLI printed, as one response: the answer, the server's other plans for it, and the usage. */
export function parseSolveOutput(stdout: string): CliResponse {
  let actions: CliResponse['actions'] = [];
  for (const line of stdout.trim().split('\n')) {
    try {
      const parsed = JSON.parse(line);
      if (parsed.actions !== undefined && parsed.token_usage !== undefined) {
        return { actions: parsed.actions, token_usage: parsed.token_usage,
          ...(Array.isArray(parsed.fallbacks) ? { fallbacks: parsed.fallbacks } : {}) };
      }
      if (Array.isArray(parsed)) actions = parsed;
      else if (parsed.action && (parsed.target_bounding_box || parsed.target_coordinates || parsed.action === 'wait')) actions = [parsed];
    } catch { /* not json or not relevant */ }
  }
  return { actions, token_usage: [] };
}
