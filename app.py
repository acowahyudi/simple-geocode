import os
import io
import time
import importlib
import pandas as pd
import streamlit as st
import geocoder
importlib.reload(geocoder)
from geocoder import BatchGeocoderEngine, test_api_provider

# Page Configuration
st.set_page_config(
    page_title="High-Speed Batch Geocoder Studio",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Dark/Light Responsive Modern Interface)
st.markdown("""
    <style>
    .stApp {
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border: 1.5px solid #334155;
        border-radius: 16px;
        padding: 24px 32px;
        color: #F8FAFC;
        margin-bottom: 24px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }
    .main-header h1 {
        color: #38BDF8;
        font-size: 2.2rem;
        font-weight: 700;
        margin: 0 0 8px 0;
    }
    .main-header p {
        color: #94A3B8;
        font-size: 1.05rem;
        margin: 0;
    }

    .metric-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 16px;
        margin-bottom: 24px;
    }
    .metric-card {
        background: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 18px 20px;
        text-align: center;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .metric-card:hover {
        border-color: #38BDF8;
        transform: translateY(-2px);
    }
    .metric-title {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94A3B8;
        margin-bottom: 6px;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #F8FAFC;
    }
    .metric-subtitle {
        font-size: 0.8rem;
        color: #64748B;
        margin-top: 4px;
    }
    
    .status-success { color: #4ADE80 !important; }
    .status-failed { color: #F87171 !important; }
    .status-speed { color: #38BDF8 !important; }
    .status-eta { color: #FBBF24 !important; }

    .checkpoint-card {
        background: rgba(56, 189, 248, 0.08);
        border: 1px solid rgba(56, 189, 248, 0.3);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }
    
    .info-box {
        background: rgba(234, 179, 8, 0.1);
        border: 1px solid rgba(234, 179, 8, 0.3);
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 16px;
        color: #FEF08A;
    }
    </style>
""", unsafe_allow_html=True)


def init_session_states():
    """Initializes Streamlit session state variables."""
    if "df_loaded" not in st.session_state:
        st.session_state.df_loaded = None
    if "geocoded_df" not in st.session_state:
        st.session_state.geocoded_df = None
    if "is_processing" not in st.session_state:
        st.session_state.is_processing = False
    if "geocoder_engine" not in st.session_state:
        st.session_state.geocoder_engine = None


def convert_df_to_csv(df: pd.DataFrame) -> bytes:
    """Exports DataFrame to CSV bytes."""
    return df.to_csv(index=False).encode('utf-8')


def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    """Exports DataFrame to Excel (.xlsx) bytes."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Hasil Geocoding')
    return output.getvalue()


def main():
    init_session_states()

    # Header
    st.markdown("""
        <div class="main-header">
            <h1>📍 Batch Geocoding Studio (No Credit Card Required)</h1>
            <p>Geocoding massal (hingga 20.000+ baris) cepat, aman, dan tanpa biaya kartu kredit menggunakan Geoapify API & OpenStreetMap.</p>
        </div>
    """, unsafe_allow_html=True)

    # Sidebar Options
    with st.sidebar:
        st.header("⚙️ Konfigurasi Geocoding")

        provider_choice = st.radio(
            "🌐 Pilih Provider Geocoding:",
            options=[
                "Geoapify",
                "OpenStreetMap (Nominatim)",
                "HERE Geocoding API"
            ],
            index=0,
            help=(
                "• Geoapify: Gratis 3.000 req/hari (daftar tanpa kartu kredit di geoapify.com).\n"
                "• OpenStreetMap: 100% Gratis, Tanpa API Key (Kecepatan dibatasi dengan Delay).\n"
                "• HERE API: Gratis 30k req/bulan."
            )
        )

        api_key = ""
        delay_seconds = 3.0

        if provider_choice in ["Geoapify", "HERE Geocoding API"]:
            api_key = st.text_input(
                f"🔑 {provider_choice} API Key",
                type="password",
                placeholder=f"Masukkan {provider_choice} API Key...",
                help="Dapatkan API Key gratis di website provider tanpa memasukkan kartu kredit."
            )
            
            if api_key.strip():
                if st.button("🧪 Uji Koneksi API", use_container_width=True):
                    with st.spinner("Memeriksa API Key & koneksi..."):
                        valid, msg = test_api_provider(provider_choice, api_key.strip())
                        if valid:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(f"❌ {msg}")
        else:
            st.info("💡 **OpenStreetMap (Nominatim)**: 100% Gratis & Tanpa API Key.")
            
            # Slider Delay per request untuk Nominatim
            delay_seconds = st.slider(
                "⏱️ Delay Per Request (Detik)",
                min_value=1.0,
                max_value=10.0,
                value=3.0,
                step=0.5,
                help="Jeda waktu antar request ke OpenStreetMap server untuk mencegah IP Rate-Limited (HTTP 429). Rekomendasi: 3.0 detik."
            )

            if st.button("🧪 Uji Koneksi Nominatim", use_container_width=True):
                with st.spinner("Memeriksa koneksi OpenStreetMap..."):
                    valid, msg = test_api_provider("OpenStreetMap (Nominatim)", "", delay_seconds)
                    if valid:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")

        st.divider()

        if provider_choice == "OpenStreetMap (Nominatim)":
            max_workers = 1
            st.caption(f"⚡ **Concurrent Workers**: Ditetapkan 1 Worker dengan **Jeda {delay_seconds} detik/request**.")
        else:
            max_workers = st.slider(
                "⚡ Concurrent Workers (Threads)",
                min_value=1,
                max_value=20,
                value=5,
                help="Jumlah worker thread sejajar. Rekomendasi 3 - 10 thread untuk Geoapify."
            )

        checkpoint_interval = st.selectbox(
            "💾 Auto-Save Checkpoint Setiap:",
            options=[50, 100, 250, 500, 1000],
            index=1,
            help="Simpan progres sementara ke file checkpoint_geocoded.csv setiap N data selesai."
        )

        st.divider()
        st.caption("🔒 **Keamanan**: Data dan API Key diproses secara lokal di sistem Anda.")

    # Provider Warnings / Banners
    if provider_choice == "OpenStreetMap (Nominatim)":
        st.markdown(f"""
            <div class="info-box">
                <b>💡 Tips OpenStreetMap (Nominatim):</b><br>
                Delay antar request saat ini diatur ke <b>{delay_seconds} detik</b> per data untuk menjaga IP Anda aman dari blokir (HTTP 429).<br>
                Untuk data massal skala besar (>500 baris) dengan kecepatan tinggi, Anda dapat berpindah ke <b>Geoapify API</b> (Gratis 3.000/hari tanpa kartu kredit).
            </div>
        """, unsafe_allow_html=True)

    # Checkpoint Detection & Resume Option
    checkpoint_file = BatchGeocoderEngine.CHECKPOINT_FILE
    checkpoint_exists = os.path.exists(checkpoint_file)
    resume_checkpoint = False

    if checkpoint_exists:
        with st.container():
            st.markdown(f"""
                <div class="checkpoint-card">
                    <h4 style="margin: 0 0 8px 0; color: #38BDF8;">🔄 File Checkpoint Ditemukan ({checkpoint_file})</h4>
                    <p style="margin: 0; color: #CBD5E1; font-size: 0.95rem;">
                        Terdapat data progres geocoding sebelumnya. Anda dapat melanjutkan proses tanpa mengulang dari baris pertama.
                    </p>
                </div>
            """, unsafe_allow_html=True)
            col_cp1, col_cp2 = st.columns([1, 1])
            with col_cp1:
                resume_checkpoint = st.checkbox("📍 Lanjutkan dari Checkpoint (Resume)", value=True)
            with col_cp2:
                if st.button("🗑️ Hapus Checkpoint Lama", type="secondary"):
                    try:
                        os.remove(checkpoint_file)
                        st.success("File checkpoint lama berhasil dihapus!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal menghapus checkpoint: {e}")

    # Data Upload Section
    st.subheader("1. Unggah File Data Alamat (.csv / .xlsx)")
    uploaded_file = st.file_uploader(
        "Pilih file Excel (.xlsx) atau CSV (.csv)",
        type=["csv", "xlsx"],
        help="Unggah file data yang memuat kolom alamat lengkap."
    )

    df = None
    if uploaded_file is not None:
        try:
            file_ext = os.path.splitext(uploaded_file.name)[1].lower()
            if file_ext == ".csv":
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            st.session_state.df_loaded = df
        except Exception as e:
            st.error(f"Error membaca file: {e}")
            return
    elif resume_checkpoint and checkpoint_exists:
        try:
            df = pd.read_csv(checkpoint_file)
            st.session_state.df_loaded = df
            st.info(f"Menggunakan data dari file checkpoint ({len(df):,} baris).")
        except Exception as e:
            st.error(f"Gagal membaca checkpoint: {e}")

    if df is None:
        st.info("💡 Silakan unggah file Excel/CSV atau aktifkan resume checkpoint untuk memulai.")
        return

    total_rows = len(df)
    st.success(f"📊 Berhasil memuat **{total_rows:,} baris** data dengan **{len(df.columns)} kolom**.")

    col_sel1, col_sel2 = st.columns([2, 1])
    with col_sel1:
        address_col = st.selectbox(
            "🎯 Pilih Kolom yang Memuat Alamat:",
            options=df.columns.tolist(),
            index=0
        )
    with col_sel2:
        st.write("")
        st.write("")
        show_preview = st.checkbox("Preview 5 Baris Pertama Data", value=True)

    if show_preview:
        st.dataframe(df.head(5), use_container_width=True)

    st.divider()

    # Execution Section
    st.subheader("2. Mulai Batch Geocoding")

    if provider_choice in ["Geoapify", "HERE Geocoding API"] and not api_key.strip():
        st.warning(f"⚠️ Masukkan API Key {provider_choice} pada sidebar sebelum memulai geocoding.")
        return

    col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 6])
    start_clicked = col_btn1.button("🚀 Mulai Geocoding", type="primary", use_container_width=True, disabled=st.session_state.is_processing)
    stop_clicked = col_btn2.button("🛑 Hentikan Proses", type="secondary", use_container_width=True, disabled=not st.session_state.is_processing)

    if stop_clicked and st.session_state.geocoder_engine:
        st.session_state.geocoder_engine.stop()
        st.session_state.is_processing = False
        st.warning("Proses dihentikan oleh pengguna.")

    progress_bar_placeholder = st.empty()
    metrics_placeholder = st.empty()
    status_text_placeholder = st.empty()

    def update_ui_metrics(metrics: dict):
        """Callback to dynamically update Streamlit UI components."""
        pct = metrics["percentage"]
        processed = metrics["processed"]
        total = metrics["total"]
        success = metrics["success"]
        failed = metrics["failed"]
        speed = metrics["speed"]
        eta = metrics["eta"]

        progress_bar_placeholder.progress(pct / 100.0, text=f"Kemajuan: {pct:.1f}% ({processed:,} / {total:,} baris)")

        metrics_html = f"""
        <div class="metric-container">
            <div class="metric-card">
                <div class="metric-title">Baris Diproses</div>
                <div class="metric-value">{processed:,} / {total:,}</div>
                <div class="metric-subtitle">{pct:.1f}% Selesai</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Sukses Ditemukan</div>
                <div class="metric-value status-success">{success:,}</div>
                <div class="metric-subtitle">Koordinat Valid</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Gagal / Kosong</div>
                <div class="metric-value status-failed">{failed:,}</div>
                <div class="metric-subtitle">Gagal Geocode</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Kecepatan</div>
                <div class="metric-value status-speed">{speed}</div>
                <div class="metric-subtitle">Baris / Detik</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Estimasi Sisa Waktu (ETA)</div>
                <div class="metric-value status-eta">{eta}</div>
                <div class="metric-subtitle">Format J:M:S / M:S</div>
            </div>
        </div>
        """
        metrics_placeholder.markdown(metrics_html, unsafe_allow_html=True)

    if start_clicked:
        st.session_state.is_processing = True
        engine = BatchGeocoderEngine(
            df=df,
            address_col=address_col,
            provider=provider_choice,
            api_key=api_key.strip(),
            delay_seconds=delay_seconds,
            max_workers=max_workers,
            checkpoint_interval=checkpoint_interval,
            resume_from_checkpoint=resume_checkpoint
        )
        st.session_state.geocoder_engine = engine

        status_text_placeholder.info(f"⏳ Memproses geocoding dengan provider **{provider_choice}** (Delay: {delay_seconds}s per data)...")

        result_df = engine.process_batch(progress_callback=update_ui_metrics)
        st.session_state.geocoded_df = result_df
        st.session_state.is_processing = False

        if engine.stop_requested:
            status_text_placeholder.warning("⚠️ Proses dihentikan sebelum selesai. Progres tersimpan aman di file checkpoint.")
        else:
            status_text_placeholder.success("🎉 Batch Geocoding Selesai 100%!")

    # Display Results & Downloads
    current_result_df = st.session_state.geocoded_df if st.session_state.geocoded_df is not None else (
        df if "Latitude" in df.columns and "Longitude" in df.columns else None
    )

    if current_result_df is not None:
        st.divider()
        st.subheader("3. Hasil & Unduh File Output")

        col_dl1, col_dl2 = st.columns([1, 1])
        with col_dl1:
            csv_data = convert_df_to_csv(current_result_df)
            st.download_button(
                label="📥 Unduh Hasil Format CSV (.csv)",
                data=csv_data,
                file_name="hasil_geocoding.csv",
                mime="text/csv",
                use_container_width=True
            )

        with col_dl2:
            try:
                excel_data = convert_df_to_excel(current_result_df)
                st.download_button(
                    label="📊 Unduh Hasil Format Excel (.xlsx)",
                    data=excel_data,
                    file_name="hasil_geocoding.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Gagal menyiapkan file Excel: {e}")

        tab_t, tab_m = st.tabs(["📋 Tabel Hasil Geocoding", "🗺️ Visualisasi Peta"])

        with tab_t:
            st.dataframe(current_result_df, use_container_width=True)

        with tab_m:
            valid_coords = current_result_df.dropna(subset=["Latitude", "Longitude"]).copy()
            valid_coords["latitude"] = pd.to_numeric(valid_coords["Latitude"], errors='coerce')
            valid_coords["longitude"] = pd.to_numeric(valid_coords["Longitude"], errors='coerce')
            valid_coords = valid_coords.dropna(subset=["latitude", "longitude"])

            if not valid_coords.empty:
                st.write(f"Menampilkan **{len(valid_coords):,} titik lokasi** sukses pada peta:")
                st.map(valid_coords[["latitude", "longitude"]], zoom=5)
            else:
                st.info("Belum ada koordinat valid untuk ditampilkan pada peta.")


if __name__ == "__main__":
    main()
