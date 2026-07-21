export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, init);
  if (res.status === 401 || res.status === 403) {
    window.location.assign("/login");
    return new Promise<never>(() => {});   // navigation in flight; never settle (SPEC §6)
  }
  if (!res.ok) {
    let detail = `${init.method ?? "GET"} ${path} -> ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch { /* keep fallback */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiSend<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
