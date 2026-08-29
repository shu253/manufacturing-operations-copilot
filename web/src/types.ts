export interface Evidence {
  source_table: string;
  record_code: string;
  description?: string;
  value?: unknown;
}

export interface ApiMeta {
  calculation_id?: string | null;
  as_of_date?: string | null;
  data_as_of_date?: string | null;
  formula_version?: string | null;
  sources: Evidence[];
  warnings: string[];
  audit: {
    operation: string;
    actor: string;
    request_path: string;
    read_only: boolean;
    timestamp: string;
  };
}

export interface ApiResponse<T> {
  success: true;
  request_id: string;
  data: T;
  meta: ApiMeta;
}

export interface ApiErrorResponse {
  success: false;
  request_id: string;
  error: { code: string; message: string; details?: unknown };
}

export type Role = "admin" | "management" | "procurement" | "production" | "sales" | "finance";
