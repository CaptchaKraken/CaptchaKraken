import fs from 'node:fs';
import path from 'node:path';

import { PromptFamily } from './kinds';

export function getBundledCliRoot(): string {
  const bundled = path.resolve(__dirname, '..', 'python');
  if (fs.existsSync(bundled)) return bundled;
  return path.resolve(__dirname, '..', '..', 'python');
}

function readJson(cliRoot: string, name: string): any {
  return JSON.parse(
    fs.readFileSync(path.join(cliRoot, 'src', 'captchakraken', name), 'utf-8'));
}

// An exact host list, not "is it remote": a self-hoster's vLLM across the network is remote too, and the hosted-only model 404s there.
const HOSTED_HOSTS = ['api.captchakraken.com'];

export function isHostedEndpoint(baseUrl: string | undefined,
                                 env: NodeJS.ProcessEnv = process.env): boolean {
  if (!baseUrl) return false;
  const extra = (env.CAPTCHA_HOSTED_HOSTS ?? '')
    .split(',').map((h) => h.trim().toLowerCase()).filter(Boolean);
  try {
    return [...HOSTED_HOSTS, ...extra].includes(new URL(baseUrl).hostname.toLowerCase());
  } catch {
    return false;
  }
}

/** Printed once when a hosted request names a model the endpoint no longer routes; the same text as the Python port's `prompts.LEGACY_MODEL_WARNING`. */
export const LEGACY_MODEL_WARNING = "The hosted API answers the model name '{model}' with an older model. Remove the model "
  + 'pin (CAPTCHA_LORA_NAME or the model option) to use the current one.';

/** Every name a current client puts on the wire to the hosted API: each routing alias and its expert arms. */
export function routedNames(cliRoot: string = getBundledCliRoot()): Set<string> {
  const out = new Set<string>();
  const reg = readJson(cliRoot, 'models.json');
  for (const [alias, id] of Object.entries(reg?.served_aliases ?? {})) {
    if (alias.startsWith('_') || typeof id !== 'string') continue;
    const declared: Record<string, unknown> = reg?.models?.[id]?.experts ?? {};
    const arms = Object.values(PromptFamily).map((family) => declared[family])
      .filter((n): n is string => typeof n === 'string' && n !== '');
    if (arms.length === 0) continue;
    out.add(alias);
    arms.forEach((arm) => out.add(arm));
  }
  return out;
}

/** A name the hosted API serves with an older model: neither a routing alias nor one of its arms. */
export function isLegacyHostedName(model: string | undefined, cliRoot: string = getBundledCliRoot()): boolean {
  return !!model && !routedNames(cliRoot).has(model);
}

/** Hosted: the routing alias, not an arm's `lora_name`, because a routed mixture is several names and only the alias routes. A missing or broken registry falls through to the pin, never throws. */
export function resolveLoraName(
  { cliRoot = getBundledCliRoot(), env = process.env, baseUrl }:
    { cliRoot?: string; env?: NodeJS.ProcessEnv; baseUrl?: string } = {},
): string {
  if (env.CAPTCHA_LORA_NAME) return env.CAPTCHA_LORA_NAME;
  try {
    const reg = readJson(cliRoot, 'models.json');
    if (isHostedEndpoint(baseUrl, env)) {
      const repo = reg?.hosted_default;
      if (typeof repo === 'string' && repo) {
        const aliases = Object.entries(reg?.served_aliases ?? {})
          .filter(([a, target]) => target === repo && !a.startsWith('_'))
          .map(([a]) => a);
        const routed = aliases.find((a) => {
          const id = (reg?.served_aliases ?? {})[a];
          return Object.keys(reg?.models?.[id]?.experts ?? {}).length > 0;
        });
        const picked = routed ?? aliases[0] ?? reg?.models?.[repo]?.lora_name;
        if (typeof picked === 'string' && picked) return picked;
      }
    }
    const name = reg?.models?.[reg?.latest]?.lora_name;
    if (typeof name === 'string' && name) return name;
  } catch {
  }
  return readJson(cliRoot, 'pinned_model.json').lora_name;
}
