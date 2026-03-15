"use client";

const AUTH_STORAGE_KEY = "revbot_control_token";

function normalizeToken(raw: string | null | undefined): string {
  return String(raw ?? "").trim();
}

export function resolveControlToken(): string {
  const envToken = normalizeToken(process.env.NEXT_PUBLIC_REVBOT_CONTROL_TOKEN);
  if (typeof window === "undefined") {
    return envToken;
  }

  const stored = normalizeToken(window.localStorage.getItem(AUTH_STORAGE_KEY));
  if (stored) {
    return stored;
  }
  return envToken;
}

export function buildMutatingAuthHeaders(
  extraHeaders?: Record<string, string>,
): Record<string, string> {
  const token = resolveControlToken();
  const headers: Record<string, string> = {
    ...(extraHeaders ?? {}),
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
    headers["X-Revbot-Token"] = token;
  }
  headers["X-Revbot-Actor"] = "web-ui";
  return headers;
}
