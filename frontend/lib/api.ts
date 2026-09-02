// dev: set NEXT_PUBLIC_API_URL=http://localhost:8000 in .env.local
// prod: leave unset — the browser calls /api/... on the same origin (nginx routes it)
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

const ACCESS_KEY = "ai_assistant_token";
const REFRESH_KEY = "ai_assistant_refresh";

const ls = {
  get: (k: string) =>
    typeof window === "undefined" ? null : localStorage.getItem(k),
  set: (k: string, v: string) => localStorage.setItem(k, v),
  del: (k: string) => localStorage.removeItem(k),
};

export const tokenStore = {
  get: () => ls.get(ACCESS_KEY),
  set: (access: string, refresh?: string) => {
    ls.set(ACCESS_KEY, access);
    if (refresh) ls.set(REFRESH_KEY, refresh);
  },
  clear: () => {
    ls.del(ACCESS_KEY);
    ls.del(REFRESH_KEY);
  },
};

function expire(): never {
  tokenStore.clear();
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event("auth:expired"));
  throw new Error("Sesi berakhir — silakan login lagi");
}

async function refreshAccess(): Promise<string> {
  const refresh = ls.get(REFRESH_KEY);
  if (!refresh) expire();
  const res = await fetch(`${API_URL}/api/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) expire();
  const data = await res.json();
  ls.set(ACCESS_KEY, data.access);
  return data.access;
}

/** fetch with bearer auth; on 401 refreshes once and retries. */
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const call = (token: string | null) =>
    fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...init.headers, authorization: `Bearer ${token}` },
    });

  let res = await call(tokenStore.get());
  if (res.status === 401) {
    res = await call(await refreshAccess());
    if (res.status === 401) expire();
  }
  return res;
}

async function jsonOrThrow<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? fallback);
  }
  return res.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error("Email atau password salah");
  const data = await res.json();
  tokenStore.set(data.access, data.refresh);
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
  return jsonOrThrow(
    await apiFetch("/api/reimbursement/ocr", { method: "POST", body: fd }),
    "Gagal membaca struk",
  );
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
  return jsonOrThrow(
    await apiFetch("/api/reimbursement/submit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "Gagal mengajukan",
  );
}

export type StockCandidate = {
  id: number;
  nama: string;
  sku: string;
  qty: number;
  satuan: string;
  gudang: string;
};

export type GoodsOcr = {
  foto_ref: string;
  produk: string | null;
  merk: string | null;
  ukuran: string | null;
  jumlah: number | null;
  satuan: string | null;
  kandidat: StockCandidate[];
};

export async function ocrGoods(file: File): Promise<GoodsOcr> {
  const fd = new FormData();
  fd.append("file", file);
  return jsonOrThrow(
    await apiFetch("/api/stock/ocr", { method: "POST", body: fd }),
    "Gagal membaca foto barang",
  );
}

export type ReceiveResult = {
  status: "ok";
  nama: string;
  sku: string;
  gudang: string;
  qty_before: number;
  qty_after: number;
};

export async function receiveStock(payload: {
  mode: "existing" | "new";
  foto_ref: string;
  jumlah: number;
  catatan?: string | null;
  product_id?: number;
  nama?: string;
  sku?: string;
  satuan?: string;
  gudang?: string;
}): Promise<ReceiveResult> {
  return jsonOrThrow(
    await apiFetch("/api/stock/receive", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "Gagal memperbarui stok",
  );
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
  const res = await apiFetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
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
      yield { type: event, ...JSON.parse(data) } as StreamEvent;
    }
  }
}
