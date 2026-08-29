import axios from "axios";
import type { ApiResponse } from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { "X-Actor": "web-demo-user" }
});

api.interceptors.response.use(
  response => response,
  error => {
    const message =
      error.response?.data?.error?.message ||
      error.response?.data?.detail ||
      error.message ||
      "接口请求失败";
    return Promise.reject(new Error(message));
  }
);

export async function getApi<T>(path: string): Promise<ApiResponse<T>> {
  const response = await api.get<ApiResponse<T>>(path);
  return response.data;
}

export async function postApi<T>(path: string, payload: unknown): Promise<ApiResponse<T>> {
  const response = await api.post<ApiResponse<T>>(path, payload);
  return response.data;
}

export async function patchApi<T>(path: string, payload: unknown): Promise<ApiResponse<T>> {
  const response = await api.patch<ApiResponse<T>>(path, payload);
  return response.data;
}

export async function streamAssistant<T>(
  path: string,
  payload: unknown,
  onEvent: (event: { event: string; data: any }) => void
): Promise<ApiResponse<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Actor": "web-demo-user"
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.error?.message || body?.detail || "智能问数接口请求失败");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: ApiResponse<T> | undefined;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      onEvent(event);
      if (event.event === "error") throw new Error(String(event.data || "智能问数失败"));
      if (event.event === "final") finalResponse = event.data;
    }
    if (done) break;
  }
  if (!finalResponse) throw new Error("智能问数流未返回最终结果");
  return finalResponse;
}

export async function downloadReport(payload: {
  report_type: string;
  format: string;
  as_of_date: string;
}) {
  const response = await api.post("/api/v1/reports/export", payload, { responseType: "blob" });
  const disposition = response.headers["content-disposition"] || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match?.[1] || `report.${payload.format}`;
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
