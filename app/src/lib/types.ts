export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SourceSpan {
  page: number;
  text: string;
  bbox?: BoundingBox | null;
}

export interface Fact {
  id: string;
  kind: "date" | "amount" | "reference" | "sender" | "other";
  label: string;
  raw_value: string;
  normalized_value?: string | null;
  confidence: number;
  verified: boolean;
  source: SourceSpan;
}

export interface Classification {
  notice_type_id: string;
  country: string;
  language: string;
  sender?: string | null;
  confidence: number;
}

export interface Deadline {
  fact_id?: string | null;
  kind: string;
  iso_date?: string | null;
  confidence: number;
}

export interface Severity {
  level: "routine" | "act_soon" | "see_professional" | "unknown";
  reason: string;
  confidence: number;
}

export interface Verdict {
  text: string;
  confidence: number;
}

export interface Explanation {
  simple: string;
  detailed: string;
}

export interface Step {
  id: string;
  text: string;
  detail?: string | null;
  fact_ids: string[];
}

export interface ChecklistItem {
  id: string;
  text: string;
}

export interface DraftReplies {
  neutral: string;
  polite?: string | null;
  firm?: string | null;
}

export interface BigPrint {
  lines: string[];
}

export interface ClarifyingQuestion {
  id: string;
  text: string;
  options: string[];
}

export interface LetterWarning {
  code: string;
  message: string;
}

export interface Meta {
  engine_version: string;
  model: string;
  offline: boolean;
  timings_ms: Record<string, number>;
}

export interface Answer {
  schema_version: string;
  id: string;
  created_at: string;
  updated_at: string;
  status: "queued" | "reading" | "ready" | "error";
  facts: Fact[];
  classification?: Classification | null;
  deadline?: Deadline | null;
  severity?: Severity | null;
  verdict?: Verdict | null;
  explanation?: Explanation | null;
  steps: Step[];
  checklist: ChecklistItem[];
  draft_replies?: DraftReplies | null;
  big_print?: BigPrint | null;
  clarifying_question?: ClarifyingQuestion | null;
  warnings: LetterWarning[];
  meta?: Meta | null;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "down";
  engine_mode: "real" | "mock" | "unknown";
  model_available: boolean;
  ollama_connected: boolean;
  offline: boolean;
  version: string;
}

export interface LetterSummary {
  id: string;
  sender: string;
  deadline: string | null;
  severity: string;
  status: string;
  created_at: string | null;
}

export interface Pack {
  id: string;
  name: string;
  country: string;
  language: string;
  severity: string;
  meaning: string;
  keywords: string[];
  path: string;
}

export interface SSEEnvelope {
  id: string;
  event: string;
  data: Record<string, unknown>;
}
