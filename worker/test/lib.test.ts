import { describe, expect, it } from "vitest";
import { handle, isAllowedDestination, parseGoPath, RateLimiter, type Env } from "../src/lib";

function env(store: Record<string, string>, clicks: unknown[][] = []): Env {
  return {
    LINKS: { get: async (k: string) => store[k] ?? null },
    CLICKS: {
      prepare: () => ({
        bind: (...values: unknown[]) => ({
          run: async () => {
            clicks.push(values);
          },
        }),
      }),
    },
  };
}

const TARGET = JSON.stringify({ url: "https://s.shopee.com.br/abc", niche: "casa", channel: "tg" });

async function call(path: string, e: Env, limiter = new RateLimiter(), init?: RequestInit) {
  const pending: Promise<unknown>[] = [];
  const res = await handle(new Request(`https://go.example.com${path}`, init), e, limiter, (p) => pending.push(p));
  await Promise.all(pending);
  return res;
}

describe("parseGoPath", () => {
  it("aceita só o formato esperado", () => {
    expect(parseGoPath("/go/casa/tg/abc123def0")).toEqual({ niche: "casa", channel: "tg", contentId: "abc123def0" });
    expect(parseGoPath("/go/casa/tg")).toBeNull();
    expect(parseGoPath("/go/casa/xx/abc123def0")).toBeNull();
    expect(parseGoPath("/go/CASA/tg/abc123def0")).toBeNull();
    expect(parseGoPath("/go/casa/tg/../../etc")).toBeNull();
  });
});

describe("isAllowedDestination", () => {
  it("bloqueia open redirect", () => {
    expect(isAllowedDestination("https://s.shopee.com.br/x")).toBe(true);
    expect(isAllowedDestination("https://meli.la/x")).toBe(true);
    expect(isAllowedDestination("http://shopee.com.br/x")).toBe(false);
    expect(isAllowedDestination("https://shopee.com.br.evil.com/x")).toBe(false);
    expect(isAllowedDestination("https://evilshopee.com.br/x")).toBe(false);
    expect(isAllowedDestination("https://shopee.com.br@evil.com/x")).toBe(false);
    expect(isAllowedDestination("javascript:alert(1)")).toBe(false);
    expect(isAllowedDestination("not a url")).toBe(false);
  });
});

describe("handle", () => {
  it("redireciona e registra clique sem IP", async () => {
    const clicks: unknown[][] = [];
    const res = await call("/go/casa/tg/abc123def0", env({ "go:abc123def0": TARGET }, clicks), new RateLimiter(), {
      headers: { "CF-Connecting-IP": "1.2.3.4", "CF-IPCountry": "BR" },
    });
    expect(res.status).toBe(302);
    expect(res.headers.get("Location")).toBe("https://s.shopee.com.br/abc");
    expect(clicks).toHaveLength(1);
    expect(clicks[0].slice(1)).toEqual(["casa", "tg", "abc123def0", "BR"]);
    expect(JSON.stringify(clicks)).not.toContain("1.2.3.4");
  });

  it("ignora parâmetros de query (não existe ?url=)", async () => {
    const res = await call("/go/casa/tg/abc123def0?url=https://evil.com", env({ "go:abc123def0": TARGET }));
    expect(res.headers.get("Location")).toBe("https://s.shopee.com.br/abc");
  });

  it("404 para id desconhecido, nicho trocado ou destino fora da allowlist", async () => {
    const evil = JSON.stringify({ url: "https://evil.com/phish", niche: "casa", channel: "tg" });
    const e = env({ "go:abc123def0": TARGET, "go:evil000000": evil });
    expect((await call("/go/casa/tg/zzzzzzzzzz", e)).status).toBe(404);
    expect((await call("/go/pet/tg/abc123def0", e)).status).toBe(404);
    expect((await call("/go/casa/tg/evil000000", e)).status).toBe(404);
    expect((await call("/admin", e)).status).toBe(404);
  });

  it("só aceita GET/HEAD e responde health", async () => {
    const e = env({});
    expect((await call("/health", e)).status).toBe(200);
    expect((await call("/go/casa/tg/abc123def0", e, new RateLimiter(), { method: "POST" })).status).toBe(405);
  });

  it("aplica rate limit por IP", async () => {
    const limiter = new RateLimiter(2, 60_000);
    const e = env({ "go:abc123def0": TARGET });
    const init = { headers: { "CF-Connecting-IP": "9.9.9.9" } };
    expect((await call("/go/casa/tg/abc123def0", e, limiter, init)).status).toBe(302);
    expect((await call("/go/casa/tg/abc123def0", e, limiter, init)).status).toBe(302);
    expect((await call("/go/casa/tg/abc123def0", e, limiter, init)).status).toBe(429);
  });
});
