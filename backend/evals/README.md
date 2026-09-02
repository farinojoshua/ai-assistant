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

**20/20 lulus.** Rata-rata ~2.6 dtk/pertanyaan. Off-topic ("ibukota Perancis",
"buatkan puisi") ditolak model dengan sopan tanpa perlu guard tambahan.

Temuan yang sudah diperbaiki di run ini:
- `cek_stok` sekarang boleh `query=""` untuk ambil semua barang → pertanyaan
  "barang yang stoknya di bawah 10" jalan.
- Checker menormalisasi non-breaking hyphen / nbsp (model suka pakai
  "TRX‑0006" dan spasi tak-putus).
