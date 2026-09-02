"use client";

import { useEffect, useRef, useState } from "react";
import { login, streamChat, tokenStore, type StreamEvent } from "@/lib/api";

type Msg = { role: "user" | "assistant"; text: string };
type Item = Msg | { role: "tool"; text: string };

export default function Page() {
  const [authed, setAuthed] = useState(false);
  useEffect(() => setAuthed(!!tokenStore.get()), []);
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

function Chat({ onLogout }: { onLogout: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const convId = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo(0, scroller.current.scrollHeight);
  }, [items]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
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

      <div className="composer">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Tulis pertanyaan…"
        />
        <button onClick={send} disabled={busy || !input.trim()}>
          Kirim
        </button>
      </div>
    </div>
  );
}
