import type { Admin, CurrentUser, Policy, Reservation, Resource } from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : "请求未完成");
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Requested-With", "meeting-pool");
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin"
  });
  if (!response.ok) {
    let detail: unknown = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // Keep the generic HTTP message.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  me: () => request<CurrentUser>("/api/v1/me"),
  reservations: () => request<Reservation[]>("/api/v1/reservations"),
  createReservation: (
    payload: {
      title: string;
      start_at: string;
      duration_minutes: number;
      description: string;
      allow_external_user: boolean;
      password: string | null;
      enable_waiting_room: boolean;
    },
    idempotencyKey: string
  ) =>
    request<Reservation>("/api/v1/reservations", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload)
    }),
  updateReservation: (
    id: string,
    payload: {
      title: string;
      start_at: string;
      duration_minutes: number;
      description: string;
      allow_external_user: boolean;
      password: string | null;
      enable_waiting_room: boolean;
    }
  ) =>
    request<Reservation>(`/api/v1/reservations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  cancel: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/reservations/${id}/cancel`, {
      method: "POST"
    }),
  resources: () => request<Resource[]>("/api/v1/admin/resources"),
  createResource: (payload: {
    wecom_userid: string;
    display_name: string;
    priority: number;
  }) =>
    request<Resource>("/api/v1/admin/resources", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateResource: (
    id: string,
    payload: Partial<
      Pick<Resource, "wecom_userid" | "display_name" | "priority" | "enabled">
    >
  ) =>
    request<Resource>(`/api/v1/admin/resources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  admins: () => request<Admin[]>("/api/v1/admin/admins"),
  createAdmin: (userid: string) =>
    request<Admin>("/api/v1/admin/admins", {
      method: "POST",
      body: JSON.stringify({ userid })
    }),
  deleteAdmin: (userid: string) =>
    request<{ ok: boolean }>(`/api/v1/admin/admins/${encodeURIComponent(userid)}`, {
      method: "DELETE"
    }),
  policy: () => request<Policy>("/api/v1/admin/policies"),
  updatePolicy: (payload: Partial<Policy>) =>
    request<Policy>("/api/v1/admin/policies", {
      method: "PATCH",
      body: JSON.stringify(payload)
    })
};
