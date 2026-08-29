/**
 * Thin fetch wrapper shared by every API call.
 *
 * `credentials: "include"` is fixed on every request — the httpOnly auth
 * cookies (`at`/`rt`, see apps/api's src/api/cookies.py) never touch
 * JavaScript, so there is no token to attach manually; the browser sends
 * them automatically as long as credentials are included.
 *
 * Error responses are RFC 7807 `application/problem+json` (SoT B4.4,
 * apps/api's src/errors.py) — parsed into `ApiError` so callers can branch
 * on `status`/`code` or just show `detail` to the user.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, detail: string, code?: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
}

function isJsonResponse(response: Response): boolean {
  return (response.headers.get("content-type") ?? "").includes("json");
}

async function parseProblemDetails(response: Response): Promise<ProblemDetails | null> {
  if (!isJsonResponse(response)) return null;
  try {
    return (await response.json()) as ProblemDetails;
  } catch {
    return null;
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    const problem = await parseProblemDetails(response);
    throw new ApiError(
      response.status,
      problem?.detail || response.statusText || "Unexpected error",
      problem?.code,
    );
  }

  if (response.status === 204 || !isJsonResponse(response)) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "GET" });
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "PATCH",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE" });
}
