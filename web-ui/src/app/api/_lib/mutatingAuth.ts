import { NextResponse } from "next/server";

const DEFAULT_MAX_MUTATING_BODY_BYTES = 64 * 1024;
const DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60;
const DEFAULT_RATE_LIMIT_MAX_REQUESTS = 120;
const rateBuckets = new Map<string, number[]>();

function parseIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }
  const numeric = Number.parseInt(raw, 10);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.max(1024, numeric);
}

function resolveExpectedToken(): string {
  return String(
    process.env.REVBOT_CONTROL_AUTH_TOKEN
    ?? process.env.NEXT_PUBLIC_REVBOT_CONTROL_TOKEN
    ?? "",
  ).trim();
}

function extractClientIp(req: Request): string {
  const xff = String(req.headers.get("x-forwarded-for") ?? "").trim();
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) {
      return first;
    }
  }
  const realIp = String(req.headers.get("x-real-ip") ?? "").trim();
  if (realIp) {
    return realIp;
  }
  return "unknown";
}

function extractToken(req: Request): string {
  const authHeader = String(req.headers.get("authorization") ?? "").trim();
  if (authHeader.toLowerCase().startsWith("bearer ")) {
    return authHeader.slice(7).trim();
  }
  return String(req.headers.get("x-revbot-token") ?? "").trim();
}

function resolveActor(req: Request): string {
  const actor = String(req.headers.get("x-revbot-actor") ?? "").trim();
  if (actor) {
    return actor;
  }
  return "web-ui-client";
}

export type MutatingAuthResult =
  | { ok: true; token: string; actor: string }
  | { ok: false; response: NextResponse };

export async function requireMutatingAuth(req: Request): Promise<MutatingAuthResult> {
  const expected = resolveExpectedToken();
  if (!expected) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "Mutating auth token is not configured", code: "auth_not_configured" },
        { status: 503 },
      ),
    };
  }

  const provided = extractToken(req);
  if (!provided || provided !== expected) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "Unauthorized", code: "unauthorized" },
        { status: 401 },
      ),
    };
  }

  const contentLengthRaw = req.headers.get("content-length");
  const maxBytes = parseIntEnv(
    "REVBOT_MUTATING_PAYLOAD_MAX_BYTES",
    DEFAULT_MAX_MUTATING_BODY_BYTES,
  );
  if (contentLengthRaw) {
    const contentLength = Number.parseInt(contentLengthRaw, 10);
    if (Number.isFinite(contentLength) && contentLength > maxBytes) {
      return {
        ok: false,
        response: NextResponse.json(
          {
            error: "Payload too large",
            code: "payload_too_large",
            details: { max_bytes: maxBytes },
          },
          { status: 413 },
        ),
      };
    }
  }

  const windowSeconds = parseIntEnv(
    "REVBOT_UI_RATE_LIMIT_WINDOW_SECONDS",
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
  );
  const maxRequests = parseIntEnv(
    "REVBOT_UI_RATE_LIMIT_MAX_REQUESTS",
    DEFAULT_RATE_LIMIT_MAX_REQUESTS,
  );
  const clientIp = extractClientIp(req);
  const bucketKey = `${clientIp}:${new URL(req.url).pathname}`;
  const now = Date.now() / 1000;
  const cutoff = now - windowSeconds;
  const bucket = rateBuckets.get(bucketKey) ?? [];
  const filtered = bucket.filter((timestamp) => timestamp >= cutoff);
  if (filtered.length >= maxRequests) {
    rateBuckets.set(bucketKey, filtered);
    return {
      ok: false,
      response: NextResponse.json(
        {
          error: "Too many requests",
          code: "rate_limited",
          details: { limit: maxRequests, window_seconds: windowSeconds },
        },
        { status: 429 },
      ),
    };
  }
  filtered.push(now);
  rateBuckets.set(bucketKey, filtered);

  return {
    ok: true,
    token: provided,
    actor: resolveActor(req),
  };
}

export function buildMutatingHeaders(
  auth: { token: string; actor: string },
  extraHeaders?: Record<string, string>,
) {
  return {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${auth.token}`,
    "X-Revbot-Token": auth.token,
    "X-Revbot-Actor": auth.actor,
    ...(extraHeaders ?? {}),
  };
}
