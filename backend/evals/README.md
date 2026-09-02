# Eval

20 pertanyaan Bahasa Indonesia untuk mengukur seberapa baik asisten memilih
tool dan menjawab. Hits provider LLM yang sedang aktif + DB perusahaan.

```bash
python evals/run_eval.py                      # semua
python evals/run_eval.py transaksi            # satu kategori
python evals/run_eval.py --json evals/last_run.json
```

Butuh: container `app_db` + `company_db` jalan & ter-seed, dan kredensial
provider di `.env`.

## Skoring

Per pertanyaan (di `questions.json`):
- `expect_tools` — semua tool ini harus dipanggil
- `expect_contains` — semua string ini harus muncul di jawaban (Unicode
  punctuation dinormalisasi dulu)
- `expect_no_tool` — (off-topic) tidak boleh ada tool call sama sekali

## Baseline (2026-09-02, gpt-oss:120b via Ollama Cloud)

**20/20 lulus.** Rata-rata ~2.7 dtk/pertanyaan. Off-topic ("ibukota Perancis",
"buatkan puisi") ditolak model dengan sopan tanpa perlu guard tambahan.

Dijalankan dengan tool generik (`daftar_data` + `ambil_data`). Yang bikin
akurasi stabil:
- Skema (view + kolom + nilai kategori) di-inject ke system prompt →
  model tidak perlu `daftar_data` untuk kasus umum.
- `ambil_data` menerima variasi bentuk argumen dari model (`col/op/value`,
  list `[kolom, op, nilai]`, `{"sum": "qty"}`).
- Prompt: pakai nilai kategori persis (status "cuti" bukan "Cuti"); kalau
  ditanya "siapa/mana", sebutkan nama bukan cuma jumlah.
- `AGENT_MAX_ITERATIONS` dinaikkan 5 → 8 (tool generik butuh lebih banyak
  langkah).
- Checker menormalisasi nbsp / non-breaking hyphen.
