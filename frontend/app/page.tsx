"use client";

import { useEffect, useRef, useState } from "react";
import {
  login,
  ocrGoods,
  ocrReceipt,
  receiveStock,
  streamChat,
  submitReimbursement,
  tokenStore,
  type GoodsOcr,
  type OcrResult,
  type StreamEvent,
} from "@/lib/api";

type Msg = { role: "user" | "assistant"; text: string };
type Item = Msg | { role: "tool"; text: string };

export default function Page() {
  const [authed, setAuthed] = useState(false);
  useEffect(() => {
    setAuthed(!!tokenStore.get());
    const onExpire = () => setAuthed(false);
    window.addEventListener("auth:expired", onExpire);
    return () => window.removeEventListener("auth:expired", onExpire);
  }, []);
  return authed ? (
    <Chat onLogout={() => { tokenStore.clear(); setAuthed(false); }} />
  ) : (
    <Login onDone={() => setAuthed(true)} />
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("admin@demo.test");
  const [password, setPassword] = useState("rahasia123");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await login(email, password);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <form className="login" onSubmit={submit}>
        <h1>AI Assistant</h1>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="email"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
        />
        {err && <div className="error">{err}</div>}
        <button disabled={busy}>{busy ? "Masuk…" : "Masuk"}</button>
      </form>
    </div>
  );
}

const COMMANDS = [
  { cmd: "reimburse", label: "/reimburse", desc: "Ajukan reimbursement dari foto struk" },
  { cmd: "stok", label: "/stok", desc: "Tambah stok gudang dari foto barang" },
  { cmd: "help", label: "/help", desc: "Daftar perintah" },
];

function Chat({ onLogout }: { onLogout: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [menuIdx, setMenuIdx] = useState(0);
  const convId = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo(0, scroller.current.scrollHeight);
  }, [items]);

  const [panel, setPanel] = useState<null | "reimburse" | "stok">(null);

  const slashMenu =
    input.startsWith("/") && !input.includes(" ")
      ? COMMANDS.filter((c) => c.cmd.startsWith(input.slice(1).toLowerCase()))
      : [];

  function runCommand(cmd: string) {
    setInput("");
    if (cmd === "reimburse" || cmd === "reimburst") {
      setPanel("reimburse");
    } else if (cmd === "stok" || cmd === "stock") {
      setPanel("stok");
    } else if (cmd === "help") {
      setItems((x) => [
        ...x,
        {
          role: "tool",
          text: COMMANDS.map((c) => `${c.label} — ${c.desc}`).join("\n"),
        },
      ]);
    } else {
      setItems((x) => [
        ...x,
        { role: "tool", text: `Perintah tidak dikenal: /${cmd}` },
      ]);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;

    if (text.startsWith("/")) {
      runCommand(text.slice(1).toLowerCase().split(/\s+/)[0]);
      return;
    }

    setInput("");
    setItems((x) => [...x, { role: "user", text }]);
    setBusy(true);
    try {
      for await (const ev of streamChat(text, convId.current) as AsyncGenerator<StreamEvent>) {
        if (ev.type === "tool") {
          setItems((x) => [
            ...x,
            { role: "tool", text: `→ ${ev.name}(${JSON.stringify(ev.arguments)})` },
          ]);
        } else if (ev.type === "token") {
          setItems((x) => [...x, { role: "assistant", text: ev.text }]);
        } else if (ev.type === "error") {
          setItems((x) => [
            ...x,
            { role: "assistant", text: `⚠ ${ev.message}` },
          ]);
        } else if (ev.type === "done") {
          convId.current = ev.conversation_id;
        }
      }
    } catch (e) {
      setItems((x) => [
        ...x,
        { role: "assistant", text: `⚠ ${(e as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>AI Assistant · data internal</h1>
        <button onClick={onLogout}>Keluar</button>
      </header>

      <div className="messages" ref={scroller}>
        {items.length === 0 && (
          <div className="tool-note">
            Coba: “ada berapa stok kabel usb?”, “siapa saja karyawan di
            departemen gudang?”, “total pemasukan bulan agustus 2026?”
          </div>
        )}
        {items.map((m, i) =>
          m.role === "tool" ? (
            <div className="tool-note" key={i}>
              {m.text}
            </div>
          ) : (
            <div className={`msg ${m.role}`} key={i}>
              <div className="role">{m.role === "user" ? "Anda" : "AI"}</div>
              <div className="bubble">{m.text}</div>
            </div>
          ),
        )}
        {busy && <div className="tool-note">…</div>}
      </div>

      {panel === "reimburse" && (
        <Reimburse
          onClose={() => setPanel(null)}
          onDone={(msg) => {
            setItems((x) => [...x, { role: "tool", text: msg }]);
            setPanel(null);
          }}
        />
      )}

      {panel === "stok" && (
        <StockReceive
          onClose={() => setPanel(null)}
          onDone={(msg) => {
            setItems((x) => [...x, { role: "tool", text: msg }]);
            setPanel(null);
          }}
        />
      )}

      <div className="composer-wrap">
        {slashMenu.length > 0 && (
          <div className="slash-menu">
            {slashMenu.map((c, i) => (
              <button
                key={c.cmd}
                className={i === menuIdx ? "active" : ""}
                onMouseEnter={() => setMenuIdx(i)}
                onClick={() => runCommand(c.cmd)}
              >
                <b>{c.label}</b>
                <span>{c.desc}</span>
              </button>
            ))}
          </div>
        )}
        <div className="composer">
          <textarea
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setMenuIdx(0);
            }}
            onKeyDown={(e) => {
              if (slashMenu.length > 0) {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setMenuIdx((i) => (i + 1) % slashMenu.length);
                  return;
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setMenuIdx((i) => (i - 1 + slashMenu.length) % slashMenu.length);
                  return;
                }
                if (e.key === "Escape") {
                  setInput("");
                  return;
                }
                if (e.key === "Enter" || e.key === "Tab") {
                  e.preventDefault();
                  runCommand(slashMenu[menuIdx].cmd);
                  return;
                }
              }
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Tulis pertanyaan…  (ketik / untuk perintah)"
          />
          <button onClick={send} disabled={busy || !input.trim()}>
            Kirim
          </button>
        </div>
      </div>
    </div>
  );
}

function Reimburse({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (msg: string) => void;
}) {
  const [ocr, setOcr] = useState<OcrResult | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({
    merchant: "",
    tanggal: "",
    nominal: "",
    kategori: "",
    catatan: "",
  });

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr("");
    setBusy(true);
    setPreview(URL.createObjectURL(file));
    try {
      const r = await ocrReceipt(file);
      setOcr(r);
      setForm({
        merchant: r.merchant ?? "",
        tanggal: r.tanggal ?? "",
        nominal: r.nominal != null ? String(r.nominal) : "",
        kategori: r.kategori ?? "",
        catatan: "",
      });
    } catch (e) {
      setErr((e as Error).message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!ocr) return;
    setErr("");
    setBusy(true);
    try {
      const res = await submitReimbursement({
        file_ref: ocr.file_ref,
        struk_hash: ocr.struk_hash,
        merchant: form.merchant,
        tanggal: form.tanggal || null,
        nominal: Number(form.nominal),
        kategori: form.kategori || null,
        catatan: form.catatan || null,
      });
      if (res.status === "disetujui") {
        onDone(
          `✅ Reimbursement disetujui — ${form.merchant}, Rp ${Number(
            form.nominal,
          ).toLocaleString("id-ID")}`,
        );
      } else {
        const k = res.klaim_lama;
        onDone(
          `❌ Ditolak: ${res.alasan} (klaim sebelumnya ${k.merchant}, Rp ${k.nominal.toLocaleString(
            "id-ID",
          )}, diajukan ${new Date(k.diajukan_pada).toLocaleDateString("id-ID")})`,
        );
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const f = (k: keyof typeof form) => ({
    value: form[k],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [k]: e.target.value }),
  });

  return (
    <div className="rb-overlay" onClick={onClose}>
      <div className="rb-panel" onClick={(e) => e.stopPropagation()}>
        <div className="rb-head">
          <b>Ajukan Reimbursement</b>
          <button onClick={onClose}>✕</button>
        </div>

        {!ocr && (
          <label className="rb-upload">
            {busy ? "Membaca struk…" : "Pilih / foto struk"}
            <input
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              onChange={onFile}
              disabled={busy}
            />
          </label>
        )}

        {preview && <img className="rb-preview" src={preview} alt="struk" />}

        {ocr && (
          <div className="rb-form">
            <label>
              Merchant<input {...f("merchant")} />
            </label>
            <label>
              Tanggal<input type="date" {...f("tanggal")} />
            </label>
            <label>
              Nominal (Rp)<input type="number" {...f("nominal")} />
            </label>
            <label>
              Kategori<input {...f("kategori")} />
            </label>
            <label>
              Catatan<input {...f("catatan")} />
            </label>
          </div>
        )}

        {err && <div className="error">{err}</div>}

        {ocr && (
          <button
            className="rb-submit"
            onClick={submit}
            disabled={busy || !form.merchant || !form.nominal}
          >
            {busy ? "Mengirim…" : "Ajukan"}
          </button>
        )}
      </div>
    </div>
  );
}

function StockReceive({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (msg: string) => void;
}) {
  const [ocr, setOcr] = useState<GoodsOcr | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // "" = barang baru, otherwise the candidate id as string
  const [match, setMatch] = useState<string>("");
  const [form, setForm] = useState({
    jumlah: "",
    nama: "",
    sku: "",
    satuan: "",
    gudang: "",
    catatan: "",
  });

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr("");
    setBusy(true);
    setPreview(URL.createObjectURL(file));
    try {
      const r = await ocrGoods(file);
      setOcr(r);
      const first = r.kandidat[0];
      setMatch(first ? String(first.id) : "");
      setForm({
        jumlah: r.jumlah != null ? String(r.jumlah) : "",
        nama: [r.produk, r.merk, r.ukuran].filter(Boolean).join(" "),
        sku: "",
        satuan: r.satuan ?? "",
        gudang: "",
        catatan: "",
      });
    } catch (e) {
      setErr((e as Error).message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!ocr) return;
    setErr("");
    setBusy(true);
    try {
      const jumlah = Number(form.jumlah);
      const res =
        match === ""
          ? await receiveStock({
              mode: "new",
              foto_ref: ocr.foto_ref,
              jumlah,
              nama: form.nama,
              sku: form.sku,
              satuan: form.satuan,
              gudang: form.gudang,
              catatan: form.catatan || null,
            })
          : await receiveStock({
              mode: "existing",
              foto_ref: ocr.foto_ref,
              jumlah,
              product_id: Number(match),
              catatan: form.catatan || null,
            });
      onDone(
        `✅ ${res.nama}: ${res.qty_before} → ${res.qty_after} (${res.gudang})`,
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const f = (k: keyof typeof form) => ({
    value: form[k],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [k]: e.target.value }),
  });

  return (
    <div className="rb-overlay" onClick={onClose}>
      <div className="rb-panel" onClick={(e) => e.stopPropagation()}>
        <div className="rb-head">
          <b>Tambah Stok Gudang</b>
          <button onClick={onClose}>✕</button>
        </div>

        {!ocr && (
          <label className="rb-upload">
            {busy ? "Membaca barang…" : "Pilih / foto barang"}
            <input
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              onChange={onFile}
              disabled={busy}
            />
          </label>
        )}

        {preview && <img className="rb-preview" src={preview} alt="barang" />}

        {ocr && (
          <div className="rb-form">
            <label>
              Barang ini
              <select
                value={match}
                onChange={(e) => setMatch(e.target.value)}
              >
                {ocr.kandidat.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.nama} — {c.sku} (stok {c.qty}, {c.gudang})
                  </option>
                ))}
                <option value="">+ Barang baru</option>
              </select>
            </label>

            {match === "" && (
              <>
                <label>
                  Nama barang<input {...f("nama")} />
                </label>
                <label>
                  SKU<input {...f("sku")} />
                </label>
                <label>
                  Satuan<input {...f("satuan")} />
                </label>
                <label>
                  Gudang<input {...f("gudang")} />
                </label>
              </>
            )}

            <label>
              Jumlah masuk<input type="number" {...f("jumlah")} />
            </label>
            <label>
              Catatan<input {...f("catatan")} />
            </label>
          </div>
        )}

        {err && <div className="error">{err}</div>}

        {ocr && (
          <button
            className="rb-submit"
            onClick={submit}
            disabled={
              busy ||
              !form.jumlah ||
              (match === "" &&
                (!form.nama || !form.sku || !form.satuan || !form.gudang))
            }
          >
            {busy ? "Menyimpan…" : "Tambahkan ke stok"}
          </button>
        )}
      </div>
    </div>
  );
}
