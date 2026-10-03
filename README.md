# 📍 Batch Geocoding Studio (No Credit Card Required)

Aplikasi web lokal berbasis Streamlit untuk melakukan **batch geocoding** hingga **20.000+ baris data alamat** dari file Excel (`.xlsx`) atau CSV (`.csv`) **TANPA membutuhkan provider yang meminta kartu kredit**.

---

## 🌐 Provider Geocoding Bebas Kartu Kredit

1. **Geoapify API** *(Direkomendasikan untuk Pemrosesan Cepat)*:
   - Gratis 3.000 request / hari.
   - Pendaftaran gratis di [geoapify.com](https://www.geoapify.com/) **tanpa perlu kartu kredit**.
   - Mendukung multi-threading paralel (3–5 thread) untuk kecepatan tinggi.

2. **OpenStreetMap / Nominatim** *(100% Gratis & Tanpa API Key)*:
   - Gratis 100% tanpa memerlukan API Key maupun kartu kredit.
   - Dilengkapi *custom User-Agent header* dan *rate-limiter* otomatis (tepat 1 req/detik) sesuai OSM Usage Policy agar IP aman dari blokir.

3. **HERE Geocoding API** *(Opsional)*:
   - Gratis 30.000 request / bulan.

---

## 🌟 Fitur Utama

- **Flexibility Input Data**: Upload `.xlsx` / `.csv`, pilih kolom alamat via dropdown, pilihan provider & input API key tersembunyi (*masked*).
- **Monitoring Real-Time**: Progress bar (0–100%), live stats (Baris diproses, Sukses vs Gagal, Kecepatan data/detik, ETA J:M:S).
- **Auto-Save Checkpoint & Resume**: Otomatis simpan progres ke `checkpoint_geocoded.csv` per 100 data. Dapat dilanjutkan (*resume*) kapan saja tanpa mengulang dari baris pertama.
- **Ekspor & Peta Interaktif**: Tambahan kolom `Latitude` dan `Longitude`, tombol download CSV & Excel (.xlsx), serta tampilan visual lokasi pada peta interaktif.

---

## 🛠️ Cara Menginstall & Menjalankan Aplikasi

### 1. Buka Terminal di Folder Proyek
```bash
cd /Users/mac/Documents/AllProject/web-geocode
```

### 2. Aktifkan Virtual Environment & Install Dependencies
```bash
# Aktifkan virtual environment (macOS/Linux)
source venv/bin/activate

# Install dependencies (jika belum)
pip install -r requirements.txt
```

### 3. Jalankan Aplikasi Streamlit
```bash
streamlit run app.py
```

Buka browser pada alamat: `http://localhost:8501`.
