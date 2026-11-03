import { sha256 as nobleSha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

type ApiErrorShape = {
  error?: {
    code?: string;
    message?: string;
    retryable?: boolean;
    request_id?: string;
    details?: Record<string, unknown>;
  };
};

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  idempotent?: boolean;
};

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  requestId?: string;
  details?: Record<string, unknown>;

  constructor(status: number, payload: ApiErrorShape) {
    super(payload.error?.message || `请求失败 (${status})`);
    this.name = "ApiError";
    this.code = payload.error?.code || "request_failed";
    this.retryable = payload.error?.retryable || false;
    this.requestId = payload.error?.request_id;
    this.details = payload.error?.details;
  }
}

const appBase = import.meta.env.BASE_URL.replace(/\/$/, "");
export const apiBase = `${appBase}/api/v1`;

export function appUrl(path: string, base = import.meta.env.BASE_URL): string {
  const normalizedBase = base.replace(/\/$/, "");
  if (/^https?:\/\//.test(path)) return path;
  if (path.startsWith("/image-studio/")) return path;
  if (path.startsWith("/api/")) return `${normalizedBase}${path}`;
  if (path.startsWith("/")) return `${normalizedBase}${path}`;
  return `${normalizedBase}/${path}`;
}

export function setCsrfToken(token: string | null): void {
  if (token) sessionStorage.setItem("image-studio-csrf", token);
  else sessionStorage.removeItem("image-studio-csrf");
}

export function csrfToken(): string | null {
  return sessionStorage.getItem("image-studio-csrf");
}

export function createRequestId(source: Crypto | undefined = globalThis.crypto): string {
  if (typeof source?.randomUUID === "function") return source.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof source?.getRandomValues === "function") source.getRandomValues(bytes);
  else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const value = bytesToHex(bytes);
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers);
  const token = csrfToken();
  if (method !== "GET" && method !== "HEAD" && token) {
    headers.set("X-CSRF-Token", token);
  }
  if (options.idempotent) {
    headers.set("Idempotency-Key", createRequestId());
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    method,
    headers,
    credentials: "include",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    let payload: ApiErrorShape = {};
    try {
      payload = (await response.json()) as ApiErrorShape;
    } catch {
      payload = {};
    }
    throw new ApiError(response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  const payload = (await response.json()) as { data: T };
  return payload.data;
}

export async function uploadToSignedUrl(
  url: string,
  file: File,
  headers: Record<string, string>,
): Promise<void> {
  const response = await fetch(appUrl(url), {
    method: "PUT",
    headers,
    body: file,
    credentials: "include",
  });
  if (!response.ok) throw new Error(`上传失败 (${response.status})`);
}

export async function sha256(file: File): Promise<string> {
  return digestSha256(await file.arrayBuffer());
}

export async function digestSha256(
  content: ArrayBuffer,
  source: Crypto | undefined = globalThis.crypto,
): Promise<string> {
  if (source?.subtle) {
    const digest = await source.subtle.digest("SHA-256", content);
    return bytesToHex(new Uint8Array(digest));
  }
  return bytesToHex(nobleSha256(new Uint8Array(content)));
}
