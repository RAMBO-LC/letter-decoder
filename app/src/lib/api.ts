import type { Answer, HealthResponse, LetterSummary, Pack } from "./types";

const LS_KEY = "ld-api-base";

export function getApiBase(): string {
  return localStorage.getItem(LS_KEY) || "http://127.0.0.1:8000";
}

export function setApiBase(base: string) {
  localStorage.setItem(LS_KEY, base.replace(/\/+$/, ""));
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return json(await fetch(`${getApiBase()}/api/health`));
}

export interface UploadOpts {
  file?: File | null;
  text?: string;
  country?: string;
  language?: string;
  sample?: string;
}

export async function uploadLetter(opts: UploadOpts): Promise<{ id: string }> {
  const form = new FormData();
  if (opts.file) form.append("file", opts.file);
  if (opts.text) form.append("text", opts.text);
  form.append("country", opts.country || "XX");
  form.append("language", opts.language || "en");
  if (opts.sample) form.append("sample", opts.sample);
  return json(
    await fetch(`${getApiBase()}/api/letters`, { method: "POST", body: form }),
  );
}

export function openLetterEvents(
  letterId: string,
  onEvent: (event: string, data: unknown) => void,
  onError?: (e: Event) => void,
): EventSource {
  const es = new EventSource(`${getApiBase()}/api/letters/${letterId}/events`);
  const types = [
    "stage",
    "facts",
    "classification",
    "deadline",
    "severity",
    "verdict",
    "explanation",
    "steps",
    "checklist",
    "big_print",
    "warning",
    "done",
    "error",
  ];
  for (const t of types) {
    es.addEventListener(t, (e) => {
      const me = e as MessageEvent<string>;
      try {
        onEvent(t, JSON.parse(me.data));
      } catch {
        onEvent(t, me.data);
      }
    });
  }
  es.onerror = (e) => {
    onError?.(e);
    es.close();
  };
  return es;
}

export async function fetchLetters(): Promise<{ letters: LetterSummary[] }> {
  return json(await fetch(`${getApiBase()}/api/letters`));
}

export async function fetchLetter(id: string): Promise<Answer> {
  return json(await fetch(`${getApiBase()}/api/letters/${id}`));
}

export async function fetchPacks(): Promise<{ packs: Pack[] }> {
  return json(await fetch(`${getApiBase()}/api/packs`));
}

export async function fetchDraft(
  id: string,
  tone: "neutral" | "polite" | "firm",
): Promise<{ neutral: string; polite?: string | null; firm?: string | null }> {
  return json(
    await fetch(`${getApiBase()}/api/letters/${id}/draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tone }),
    }),
  );
}

export async function deleteLetter(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/letters/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

export async function updateStep(
  id: string,
  stepId: string,
  done: boolean,
): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/letters/${id}/steps/${stepId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ done }),
  });
  if (!res.ok) throw new Error(`Step update failed: ${res.status}`);
}
