// Lógica pura do redirecionador: sem dependência do runtime, testável com vitest.
import allowed from "../../config/allowed_domains.json";

export const ALLOWED_DOMAINS: string[] = allowed.domains;

const SEGMENT = /^[a-z0-9-]{2,20}$/;
const CONTENT_ID = /^[a-z0-9]{6,16}$/;
const CHANNELS = new Set(["tg", "ig", "tt", "bio", "site"]);

export interface GoTarget {
  url: string;
  niche: string;
  channel: string;
}

export interface GoRequest {
  niche: string;
  channel: string;
  contentId: string;
}

export function parseGoPath(pathname: string): GoRequest | null {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length !== 4 || parts[0] !== "go") return null;
  const [, niche, channel, contentId] = parts;
  if (!SEGMENT.test(niche) || !CHANNELS.has(channel) || !CONTENT_ID.test(contentId)) return null;
  return { niche, channel, contentId };
}

export function isAllowedDestination(raw: string, domains: string[] = ALLOWED_DOMAINS): boolean {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (url.protocol !== "https:" || url.username || url.password) return false;
  const host = url.hostname.toLowerCase();
  return domains.some((d) => host === d || host.endsWith(`.${d}`));
}

export function parseTarget(value: string | null): GoTarget | null {
  if (!value) return null;
  try {
    const data = JSON.parse(value) as Partial<GoTarget>;
    if (typeof data.url !== "string" || typeof data.niche !== "string") return null;
    return { url: data.url, niche: data.niche, channel: String(data.channel ?? "") };
  } catch {
    return null;
  }
}

// Rate limit em memória por isolate. A chave é o IP só enquanto o isolate vive; nunca é gravado.
export class RateLimiter {
  private hits = new Map<string, { count: number; reset: number }>();
  constructor(private limit = 60, private windowMs = 60_000) {}

  allow(key: string, now = Date.now()): boolean {
    const entry = this.hits.get(key);
    if (!entry || entry.reset <= now) {
      if (this.hits.size > 10_000) this.hits.clear();
      this.hits.set(key, { count: 1, reset: now + this.windowMs });
      return true;
    }
    entry.count += 1;
    return entry.count <= this.limit;
  }
}

export interface KVLike {
  get(key: string): Promise<string | null>;
}

export interface D1Like {
  prepare(sql: string): { bind(...values: unknown[]): { run(): Promise<unknown> } };
}

export interface Env {
  LINKS: KVLike;
  CLICKS: D1Like;
}

export const BOT_UA =
  /bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|discord|slack|curl|wget|python-requests|httpx|headless/i;

const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Cache-Control": "no-store",
};

function text(status: number, body: string): Response {
  return new Response(body, { status, headers: { "Content-Type": "text/plain; charset=utf-8", ...SECURITY_HEADERS } });
}

export async function handle(
  request: Request,
  env: Env,
  limiter: RateLimiter,
  waitUntil: (p: Promise<unknown>) => void,
): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") return text(405, "method not allowed");
  const url = new URL(request.url);
  if (url.pathname === "/health") return text(200, "ok");

  const go = parseGoPath(url.pathname);
  if (!go) return text(404, "not found");

  const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
  if (!limiter.allow(ip)) return text(429, "too many requests");

  const target = parseTarget(await env.LINKS.get(`go:${go.contentId}`));
  // O destino precisa existir no KV, bater com o nicho da URL e estar na allowlist.
  if (!target || target.niche !== go.niche || !isAllowedDestination(target.url)) return text(404, "not found");

  // Só conta clique de pessoa: HEAD, robôs e geradores de prévia inflariam o EPC e distorceriam o score.
  // O user-agent é lido só aqui, em memória; nunca é gravado.
  if (request.method !== "GET" || BOT_UA.test(request.headers.get("User-Agent") ?? "")) {
    return redirect(target.url);
  }
  const country = request.headers.get("CF-IPCountry");
  waitUntil(
    env.CLICKS.prepare("INSERT INTO clicks (ts, niche, channel, content_id, country) VALUES (?, ?, ?, ?, ?)")
      .bind(new Date().toISOString(), go.niche, go.channel, go.contentId, country && country.length === 2 ? country : null)
      .run()
      .catch(() => undefined),
  );
  return redirect(target.url);
}

function redirect(location: string): Response {
  return new Response(null, { status: 302, headers: { Location: location, ...SECURITY_HEADERS } });
}
