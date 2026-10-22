// Cloudflare Worker: redirecionador /go/<nicho>/<canal>/<content_id> com registro de clique.
import { handle, RateLimiter, type Env } from "./lib";

const limiter = new RateLimiter(60, 60_000);

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    try {
      return await handle(request, env, limiter, (p) => ctx.waitUntil(p));
    } catch {
      // Nunca expõe detalhes internos.
      return new Response("error", { status: 500, headers: { "Content-Type": "text/plain" } });
    }
  },
};
