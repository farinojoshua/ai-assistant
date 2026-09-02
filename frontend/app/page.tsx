"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
import {
  AlertTriangle,
  Camera,
  Check,
  HelpCircle,
  LogOut,
  Package,
  Receipt,
  Send,
  Sparkles,
  Terminal,
  X,
} from "./icons";

type Kind = "ok" | "bad" | "info";
type Item =
  | { role: "user" | "assistant"; text: string }
  | { role: "tool"; text: string; kind: Kind };

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
    <div className="login-page">
      <form className="login" onSubmit={submit}>
        <div className="brand-mark">
          <Sparkles size={20} />
        </div>
        <h1>AI Assistant</h1>
        <p className="sub">Asisten data internal perusahaan</p>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
          />
        </div>
        <div className="field">
          <label htmlFor="pw">Password</label>
          <input
            id="pw"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        {err && (
          <div className="error">
            <AlertTriangle /> {err}
          </div>
        )}
        <button className="btn-primary" disabled={busy}>
          {busy ? "Masuk…" : "Masuk"}
        </button>
      </form>
    </div>
  );
}

const COMMANDS = [
  {
    cmd: "reimburse",
    label: "/reimburse",
    desc: "Ajukan reimbursement dari foto struk",
    icon: <Receipt size={15} />,
  },
  {
    cmd: "stok",
    label: "/stok",
    desc: "Tambah stok gudang dari foto barang",
    icon: <Package size={15} />,
  },
  {
    cmd: "help",
    label: "/help",
    desc: "Daftar perintah",
    icon: <HelpCircle size={15} />,
  },
];

const EXAMPLES = [
  "ada berapa stok kabel usb?",
  "siapa saja karyawan di departemen gudang?",
  "total pemasukan bulan agustus 2026?",
];

function Chat({ onLogout }: { onLogout: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [menuIdx, setMenuIdx] = useState(0);
  const [panel, setPanel] = useState<null | "reimburse" | "stok">(null);
  const convId = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({
      top: scroller.current.scrollHeight,
      behavior: "smooth",
    });
  }, [items, busy]);

  const slashMenu =
    input.startsWith("/") && !input.includes(" ")
      ? COMMANDS.filter((c) => c.cmd.startsWith(input.slice(1).toLowerCase()))
      : [];

  const addTool = (text: string, kind: Kind) =>
    setItems((x) => [...x, { role: "tool", text, kind }]);

  function runCommand(cmd: string) {
    setInput("");
    if (cmd === "reimburse" || cmd === "reimburst") setPanel("reimburse");
    else if (cmd === "stok" || cmd === "stock") setPanel("stok");
    else if (cmd === "help")
      addTool(COMMANDS.map((c) => `${c.label} — ${c.desc}`).join("\n"), "info");
    else addTool(`Perintah tidak dikenal: /${cmd}`, "bad");
  }

  async function send(preset?: string) {
    const text = (preset ?? input).trim();
    if (!text || busy) return;

    if (text.startsWith("/")) {
      runCommand(text.slice(1).toLowerCase().split(/\s+/)[0]);
      return;
    }

    setInput("");
    setItems((x) => [...x, { role: "user", text }]);
    setBusy(true);
    try {
      for await (const ev of streamChat(
        text,
        convId.current,
      ) as AsyncGenerator<StreamEvent>) {
        if (ev.type === "tool") {
          const a = ev.arguments as Record<string, unknown>;
          const hint = a.view ?? a.produk ?? a.query ?? "";
          addTool(hint ? `${ev.name} · ${hint}` : ev.name, "info");
        }
        else if (ev.type === "token")
          setItems((x) => [...x, { role: "assistant", text: ev.text }]);
        else if (ev.type === "error")
          setItems((x) => [
            ...x,
            { role: "assistant", text: ev.message },
          ]);
        else if (ev.type === "done") convId.current = ev.conversation_id;
      }
    } catch (e) {
      setItems((x) => [
        ...x,
        { role: "assistant", text: (e as Error).message },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header>
        <div className="brand">
          <div className="brand-mark">
            <Sparkles size={17} />
          </div>
          <div>
            <h1>AI Assistant</h1>
            <span>data internal</span>
          </div>
        </div>
        <button className="btn-ghost" onClick={onLogout}>
          <LogOut size={14} /> Keluar
        </button>
      </header>

      <div className="messages" ref={scroller}>
        {items.length === 0 && (
          <div className="empty">
            <div className="empty-icon">
              <Sparkles size={20} />
            </div>
            <h2>Tanya apa saja soal data perusahaan</h2>
            <p>Stok gudang, data karyawan, transaksi keuangan.</p>
            <div className="examples">
              {EXAMPLES.map((q) => (
                <button key={q} onClick={() => send(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {items.map((m, i) =>
          m.role === "tool" ? (
            <div
              key={i}
              className={`tool-note ${m.kind === "ok" ? "ok" : m.kind === "bad" ? "bad" : ""}`}
            >
              {m.kind === "ok" ? (
                <Check />
              ) : m.kind === "bad" ? (
                <AlertTriangle />
              ) : (
                <Terminal />
              )}
              <span>{m.text}</span>
            </div>
          ) : (
            <div className={`msg ${m.role === "user" ? "user" : "ai"}`} key={i}>
              <div className={`avatar ${m.role === "user" ? "user" : "ai"}`}>
                {m.role === "user" ? "A" : <Sparkles size={14} />}
              </div>
              <div className="bubble">
                {m.role === "assistant" ? (
                  <div className="md">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {m.text}
                    </ReactMarkdown>
                  </div>
                ) : (
                  m.text
                )}
              </div>
            </div>
          ),
        )}

        {busy && (
          <div className="msg ai">
            <div className="avatar ai">
              <Sparkles size={14} />
            </div>
            <div className="typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
      </div>

      {panel === "reimburse" && (
        <Reimburse
          onClose={() => setPanel(null)}
          onDone={(text, kind) => {
            addTool(text, kind);
            setPanel(null);
          }}
        />
      )}
      {panel === "stok" && (
        <StockReceive
          onClose={() => setPanel(null)}
          onDone={(text, kind) => {
            addTool(text, kind);
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
                <span className="s-icon">{c.icon}</span>
                <span>
                  <span className="s-label">{c.label}</span>
                  <span className="s-desc"> · {c.desc}</span>
                </span>
              </button>
            ))}
          </div>
        )}
        <div className="composer">
          <textarea
            value={input}
            rows={1}
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
                  setMenuIdx(
                    (i) => (i - 1 + slashMenu.length) % slashMenu.length,
                  );
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
            placeholder="Tulis pertanyaan…  ketik / untuk perintah"
          />
          <button
            className="btn-send"
            onClick={() => send()}
            disabled={busy || !input.trim()}
            aria-label="Kirim"
          >
            <Send />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------- shared panel primitives ---------- */

function Panel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="panel-head">
          <h3>{title}</h3>
          <button onClick={onClose} aria-label="Tutup">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Dropzone({
  label,
  busy,
  onFile,
}: {
  label: string;
  busy: boolean;
  onFile: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="dropzone">
      <Camera size={22} />
      {busy ? "Membaca…" : label}
      <input
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={onFile}
        disabled={busy}
      />
    </label>
  );
}

const rupiah = (n: number) => `Rp ${n.toLocaleString("id-ID")}`;

/* ---------- Reimbursement ---------- */

function Reimburse({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (text: string, kind: Kind) => void;
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
          `Reimbursement disetujui — ${form.merchant}, ${rupiah(Number(form.nominal))}`,
          "ok",
        );
      } else {
        const k = res.klaim_lama;
        onDone(
          `Ditolak: ${res.alasan} Klaim sebelumnya: ${k.merchant}, ${rupiah(k.nominal)}, diajukan ${new Date(k.diajukan_pada).toLocaleDateString("id-ID")}.`,
          "bad",
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
    <Panel title="Ajukan Reimbursement" onClose={onClose}>
      {!ocr && <Dropzone label="Foto struk" busy={busy} onFile={onFile} />}
      {preview && <img className="preview" src={preview} alt="struk" />}
      {ocr && (
        <div className="form-grid">
          <label>
            Merchant<input {...f("merchant")} />
          </label>
          <label>
            Tanggal<input type="date" {...f("tanggal")} />
          </label>
          <label>
            Nominal (Rp)<input type="number" inputMode="numeric" {...f("nominal")} />
          </label>
          <label>
            Kategori<input {...f("kategori")} />
          </label>
          <label>
            Catatan<input {...f("catatan")} />
          </label>
        </div>
      )}
      {err && (
        <div className="error">
          <AlertTriangle /> {err}
        </div>
      )}
      {ocr && (
        <button
          className="btn-primary"
          onClick={submit}
          disabled={busy || !form.merchant || !form.nominal}
        >
          {busy ? "Mengirim…" : "Ajukan"}
        </button>
      )}
    </Panel>
  );
}

/* ---------- Stock in ---------- */

function StockReceive({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (text: string, kind: Kind) => void;
}) {
  const [ocr, setOcr] = useState<GoodsOcr | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [match, setMatch] = useState<string>(""); // "" = barang baru
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
      setMatch(r.kandidat[0] ? String(r.kandidat[0].id) : "");
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
        `Stok diperbarui — ${res.nama}: ${res.qty_before} → ${res.qty_after} (${res.gudang})`,
        "ok",
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
    <Panel title="Tambah Stok Gudang" onClose={onClose}>
      {!ocr && <Dropzone label="Foto barang" busy={busy} onFile={onFile} />}
      {preview && <img className="preview" src={preview} alt="barang" />}
      {ocr && (
        <div className="form-grid">
          <label>
            Barang ini
            <select value={match} onChange={(e) => setMatch(e.target.value)}>
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
            Jumlah masuk
            <input type="number" inputMode="numeric" {...f("jumlah")} />
          </label>
          <label>
            Catatan<input {...f("catatan")} />
          </label>
        </div>
      )}
      {err && (
        <div className="error">
          <AlertTriangle /> {err}
        </div>
      )}
      {ocr && (
        <button
          className="btn-primary"
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
    </Panel>
  );
}
