/**
 * Auth endpoints this issue needs. Mirrors apps/api's `UserRead`
 * (src/domain/user.py) — id/email/created_at only, password_hash is never
 * exposed.
 */

import { apiGet, apiPost } from "./api-client";

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export function login(email: string, password: string): Promise<User> {
  return apiPost<User>("/api/v1/auth/login", { email, password });
}

export function logout(): Promise<void> {
  return apiPost<void>("/api/v1/auth/logout");
}

export function fetchMe(): Promise<User> {
  return apiGet<User>("/api/v1/auth/me");
}
