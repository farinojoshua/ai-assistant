export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "ai_assistant_token";

export const tokenStore = {
  get: () =>
    typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export async function login(email: string, password: string): Promise<string> {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error("Email atau password salah");
  const data = await res.json();
  tokenStore.set(data.access);
  return data.access;
}

function authHeaders(): Record<string, string> {
  return { authorization: `Bearer ${tokenStore.get()}` };
}

export type OcrResult = {
  file_ref: string;
  struk_hash: string;
  merchant: string | null;
  tanggal: string | null;
  nominal: number | null;
  kategori: string | null;
  mata_uang: string;
};

export async function ocrReceipt(file: File): Promise<OcrResult> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_URL}/api/reimbursement/ocr`, {
    method: "POST",
    headers: authHeaders(),
    body: fd,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Gagal membaca struk (${res.status})`);
  }
  return res.json();
}

export type SubmitResult =
  | { status: "disetujui"; id: string }
  | {
      status: "ditolak";
      alasan: string;
      klaim_lama: {
        merchant: string;
        tanggal_struk: string | null;
        nominal: number;
        diajukan_pada: string;
      };
    };

export async function submitReimbursement(payload: {
  file_ref: string;
  struk_hash?: string;
  merchant: string;
  tanggal: string | null;
  nominal: number;
  kategori: string | null;
  catatan?: string | null;
}): Promise<SubmitResult> {
  const res = await fetch(`${API_URL}/api/reimbursement/submit`, {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Gagal mengajukan (${res.status})`);
  }
  return res.json();
}

export type StreamEvent =
  | { type: "tool"; name: string; arguments: Record<string, unknown> }
  | { type: "token"; text: string }
  | { type: "error"; message: string }
  | { type: "done"; conversation_id: string };

export async function* streamChat(
  message: string,
  conversationId: string | null,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${tokenStore.get()}`,
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
    }),
  });
  if (res.status === 401) {
    tokenStore.clear();
    throw new Error("Sesi berakhir, silakan login lagi");
  }
  if (!res.ok || !res.body) throw new Error(`Gagal: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const blocks = buf.split("\n\n");
    buf = blocks.pop() ?? "";
    for (const block of blocks) {
      let event = "";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (!event || !data) continue;
      const parsed = JSON.parse(data);
      yield { type: event, ...parsed } as StreamEvent;
    }
  }
}
