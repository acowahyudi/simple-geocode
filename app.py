import os
import io
import time
import pandas as pd
import streamlit as st
from geocoder import (
    BatchGeocoderEngine,
    GeocodeTaskManager,
    test_api_provider
)

# Page Configuration
st.set_page_config(
    page_title="High-Speed Batch Geocoder Studio",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Global Persistent Task Manager (persists across browser reloads & tabs)
@st.cache_resource
def get_global_task_manager() -> GeocodeTaskManager:
    return GeocodeTaskManager()

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

    .badge-running {
        display: inline-block;
        background: rgba(34, 197, 94, 0.18);
        border: 1px solid #22C55E;
        color: #4ADE80;
        font-size: 0.82rem;
        font-weight: 600;
        padding: 3px 12px;
        border-radius: 20px;
        margin-left: 10px;
        vertical-align: middle;
        animation: pulse 2s infinite;
    }

    .badge-stopping {
        display: inline-block;
        background: rgba(234, 179, 8, 0.18);
        border: 1px solid #EAB308;
        color: #FBBF24;
        font-size: 0.82rem;
        font-weight: 600;
        padding: 3px 12px;
        border-radius: 20px;
        margin-left: 10px;
        vertical-align: middle;
    }

    .activity-box {
        background: #0F172A;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 12px 16px;
        margin-top: 14px;
        margin-bottom: 20px;
    }
    
    .activity-item {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.84rem;
        color: #94A3B8;
        padding: 5px 0;
        border-bottom: 1px solid #1E293B;
    }
    .activity-item:last-child {
        border-bottom: none;
    }

    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.55; }
        100% { opacity: 1; }
    }
    </style>
""", unsafe_allow_html=True)


def convert_df_to_csv(df: pd.DataFrame) -> bytes:
    """Exports DataFrame to CSV bytes."""
    return df.to_csv(index=False).encode('utf-8')


def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    """Exports DataFrame to Excel (.xlsx) bytes."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Hasil Geocoding')
    return output.getvalue()


@st.fragment(run_every="1s")
def render_running_dashboard(task_mgr: GeocodeTaskManager):
    """
    Real-time progress dashboard rendered every 1 second without full page reload.
    Survives browser refresh and updates smoothly.
    """
    info = task_mgr.get_info()
    status = info["status"]

    # When background task completes or stops, trigger parent app rerun to show results
    if status in ("completed", "stopped", "error"):
        st.rerun(scope="app")
        return

    metrics = info["metrics"]
    pct = metrics.get("percentage", 0.0)
    processed = metrics.get("processed", 0)
    total = metrics.get("total", 0)
    success = metrics.get("success", 0)
    failed = metrics.get("failed", 0)
    speed = metrics.get("speed", 0.0)
    eta = metrics.get("eta", "--:--")

    # Progress bar
    st.progress(pct / 100.0, text=f"Kemajuan: {pct:.1f}% ({processed:,} / {total:,} baris)")

    # 5 Metric Cards
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
    st.markdown(metrics_html, unsafe_allow_html=True)

    # Real-Time Activity Feed (Last 6 processed rows)
    recent_logs = info.get("recent_logs", [])
    if recent_logs:
        st.markdown("##### 📡 Aktivitas Geocoding Real-Time (Data Terakhir Diproses)")
        log_rows_html = ""
        for item in reversed(recent_logs):
            badge_color = "#4ADE80" if item["status"] == "success" else "#F87171"
            log_rows_html += f"""
            <div class="activity-item">
                <span style="color: #64748B;">[{item["time"]}]</span> 
                <b style="color: #38BDF8;">Baris #{item["row"]}:</b> 
                <span>{item["address"]}</span> 
                <span style="color: {badge_color}; float: right;">[{item["status"]}] {item["coords"]}</span>
            </div>
            """
        st.markdown(f'<div class="activity-box">{log_rows_html}</div>', unsafe_allow_html=True)

    # Stop Button / Status Note
    col_s1, col_s2 = st.columns([2, 5])
    with col_s1:
        if status == "stopping":
            st.button("⏳ Menyimpan Checkpoint...", disabled=True, use_container_width=True)
            st.caption("Sedang menghentikan thread & menyimpan progres ke checkpoint...")
        else:
            if st.button("🛑 Hentikan Proses", type="secondary", use_container_width=True, key="btn_stop_bg_proc"):
                task_mgr.stop_task()
                st.rerun(scope="app")
    with col_s2:
        if status == "running":
            st.caption("💡 *Proses berjalan di background. Anda bebas me-refresh browser atau berpindah tab tanpa kehilangan data!*")


def render_results_section(df: pd.DataFrame, subtitle: str = ""):
    """Renders download buttons, table tab, and map tab for completed or stopped results."""
    st.divider()
    st.subheader("📊 Hasil & Unduh File Output")
    if subtitle:
        st.caption(subtitle)

    col_dl1, col_dl2 = st.columns([1, 1])
    with col_dl1:
        csv_data = convert_df_to_csv(df)
        st.download_button(
            label="📥 Unduh Hasil Format CSV (.csv)",
            data=csv_data,
            file_name="hasil_geocoding.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col_dl2:
        try:
            excel_data = convert_df_to_excel(df)
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
        st.dataframe(df, use_container_width=True)

    with tab_m:
        if "Latitude" in df.columns and "Longitude" in df.columns:
            valid_coords = df.dropna(subset=["Latitude", "Longitude"]).copy()
            valid_coords["latitude"] = pd.to_numeric(valid_coords["Latitude"], errors='coerce')
            valid_coords["longitude"] = pd.to_numeric(valid_coords["Longitude"], errors='coerce')
            valid_coords = valid_coords.dropna(subset=["latitude", "longitude"])

            if not valid_coords.empty:
                st.write(f"Menampilkan **{len(valid_coords):,} titik lokasi** sukses pada peta:")
                st.map(valid_coords[["latitude", "longitude"]], zoom=5)
            else:
                st.info("Belum ada koordinat valid untuk ditampilkan pada peta.")


def main():
    task_mgr = get_global_task_manager()
    task_info = task_mgr.get_info()
    task_status = task_info["status"]

    # Header
    st.markdown("""
        <div class="main-header">
            <h1>📍 Batch Geocoding Studio (No Credit Card Required)</h1>
            <p>Geocoding massal cepat, aman di background, dan tanpa biaya kartu kredit menggunakan Geoapify API & OpenStreetMap.</p>
        </div>
    """, unsafe_allow_html=True)

    # -------------------------------------------------------------
    # CASE 1: TASK IS RUNNING OR STOPPING IN BACKGROUND
    # -------------------------------------------------------------
    if task_status in ("running", "stopping"):
        # Sidebar in Running Mode
        with st.sidebar:
            st.header("⚙️ Konfigurasi Geocoding")
            st.markdown("""
                <div class="info-box" style="border-color: #38BDF8; color: #38BDF8; background: rgba(56, 189, 248, 0.1);">
                    <b>⚡ Proses Sedang Berjalan</b><br>
                    Konfigurasi dikunci selama geocoding berlangsung di background.
                </div>
            """, unsafe_allow_html=True)
            st.write(f"**🌐 Provider:** {task_info['provider']}")
            st.write(f"**📄 File:** {task_info['filename']}")
            st.write(f"**🎯 Kolom Alamat:** {task_info['address_col']}")
            if task_info["provider"] == "OpenStreetMap (Nominatim)":
                st.write(f"**⏱️ Delay OSM:** {task_info['delay_seconds']} detik/request")
                st.write("**⚡ Workers:** 1 Worker")
            else:
                st.write(f"**⚡ Workers:** {task_info['max_workers']} Concurrent Threads")
                st.write("**⏱️ Delay:** Tanpa Delay (Maksimal API Speed)")
            st.divider()
            st.caption("🔒 **Keamanan**: Data diproses secara lokal pada mesin Anda.")

        badge_html = '<span class="badge-running">● RUNNING BACKGROUND</span>' if task_status == "running" else '<span class="badge-stopping">● STOPPING...</span>'
        st.subheader("⚡ Monitoring Geocoding Real-Time")
        st.markdown(f"""
            <div style="margin-bottom: 12px; color: #CBD5E1; font-size: 0.95rem;">
                <b>File:</b> <code>{task_info['filename']}</code> &nbsp;|&nbsp; 
                <b>Provider:</b> <code>{task_info['provider']}</code> &nbsp;|&nbsp; 
                <b>Kolom Alamat:</b> <code>{task_info['address_col']}</code>
                {badge_html}
            </div>
        """, unsafe_allow_html=True)

        render_running_dashboard(task_mgr)
        return

    # -------------------------------------------------------------
    # CASE 2: TASK COMPLETED
    # -------------------------------------------------------------
    if task_status == "completed":
        st.success("🎉 **Batch Geocoding Selesai 100%!** Seluruh baris telah selesai diproses.")

        metrics = task_info["metrics"]
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-card">
                <div class="metric-title">Total Baris</div>
                <div class="metric-value">{metrics['total']:,}</div>
                <div class="metric-subtitle">100% Selesai</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Sukses Ditemukan</div>
                <div class="metric-value status-success">{metrics['success']:,}</div>
                <div class="metric-subtitle">Koordinat Valid</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Gagal / Kosong</div>
                <div class="metric-value status-failed">{metrics['failed']:,}</div>
                <div class="metric-subtitle">Tidak Terindeks</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Kecepatan Rata-Rata</div>
                <div class="metric-value status-speed">{metrics['speed']}</div>
                <div class="metric-subtitle">Baris / Detik</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Total Waktu</div>
                <div class="metric-value status-eta">{metrics['elapsed']}s</div>
                <div class="metric-subtitle">Durasi Proses</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_btn1, col_btn2 = st.columns([2, 5])
        with col_btn1:
            if st.button("🔄 Mulai Batch Baru / Unggah File Lain", type="primary", use_container_width=True):
                task_mgr.reset_task()
                st.rerun(scope="app")

        if task_info["df"] is not None:
            render_results_section(task_info["df"], subtitle="Hasil lengkap batch geocoding yang telah selesai.")
        return

    # -------------------------------------------------------------
    # CASE 3: TASK STOPPED BY USER
    # -------------------------------------------------------------
    if task_status == "stopped":
        st.warning("⚠️ **Batch Geocoding Dihentikan oleh Pengguna.**")
        st.info("💡 Data progres yang telah selesai tersimpan aman di file checkpoint. Anda dapat melanjutkan proses kapan saja.")

        metrics = task_info["metrics"]
        st.markdown(f"""
        <div class="metric-container">
            <div class="metric-card">
                <div class="metric-title">Baris Selesai</div>
                <div class="metric-value">{metrics['processed']:,} / {metrics['total']:,}</div>
                <div class="metric-subtitle">{metrics['percentage']}% Selesai</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Sukses Ditemukan</div>
                <div class="metric-value status-success">{metrics['success']:,}</div>
                <div class="metric-subtitle">Koordinat Valid</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Gagal / Kosong</div>
                <div class="metric-value status-failed">{metrics['failed']:,}</div>
                <div class="metric-subtitle">Tidak Terindeks</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Kecepatan Terakhir</div>
                <div class="metric-value status-speed">{metrics['speed']}</div>
                <div class="metric-subtitle">Baris / Detik</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">Status Checkpoint</div>
                <div class="metric-value status-eta">Tersimpan</div>
                <div class="metric-subtitle">Siap Dilanjutkan</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_act1, col_act2, col_dummy = st.columns([2, 2, 3])
        with col_act1:
            if st.button("▶️ Lanjutkan Geocoding (Resume)", type="primary", use_container_width=True):
                task_mgr.resume_task()
                st.rerun(scope="app")
        with col_act2:
            if st.button("🔄 Reset / Ganti File Baru", type="secondary", use_container_width=True):
                task_mgr.reset_task()
                st.rerun(scope="app")

        if task_info["df"] is not None:
            render_results_section(task_info["df"], subtitle="Hasil data yang sempat terproses sebelum dihentikan.")
        return

    # -------------------------------------------------------------
    # CASE 4: TASK ERROR
    # -------------------------------------------------------------
    if task_status == "error":
        st.error(f"❌ Terjadi kesalahan saat memproses geocoding: {task_info['error_message']}")
        if st.button("🔄 Reset Status", type="primary"):
            task_mgr.reset_task()
            st.rerun(scope="app")
        return

    # -------------------------------------------------------------
    # CASE 5: IDLE (Standard Setup & Upload Screen)
    # -------------------------------------------------------------
    # Sidebar Configuration
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
                help="Jumlah worker thread sejajar. Rekomendasi 3 - 10 thread untuk Geoapify (Tanpa delay)."
            )

        checkpoint_interval = st.selectbox(
            "💾 Auto-Save Checkpoint Setiap:",
            options=[50, 100, 250, 500, 1000],
            index=1,
            help="Simpan progres sementara ke file checkpoint_geocoded.csv setiap N data selesai."
        )

        st.divider()
        st.caption("🔒 **Keamanan**: Data dan API Key diproses secara lokal di sistem Anda.")

    # Provider Tips Banner
    if provider_choice == "OpenStreetMap (Nominatim)":
        st.markdown(f"""
            <div class="info-box">
                <b>💡 Mode OpenStreetMap (Nominatim):</b><br>
                Delay per request diatur ke <b>{delay_seconds} detik</b> untuk mematuhi OSM Usage Policy & mencegah blokir IP (HTTP 429).<br>
                Untuk kecepatan tinggi tanpa jeda buatan, Anda dapat menggunakan <b>Geoapify API</b> (Gratis 3.000 req/hari tanpa kartu kredit).
            </div>
        """, unsafe_allow_html=True)
    elif provider_choice == "Geoapify":
        st.markdown(f"""
            <div class="info-box" style="background: rgba(34, 197, 94, 0.1); border-color: rgba(34, 197, 94, 0.3); color: #86EFAC;">
                <b>⚡ Mode Kecepatan Tinggi (Geoapify):</b><br>
                Geoapify memproses data secara paralel menggunakan <b>{max_workers} thread bersamaan tanpa delay buatan</b>.<br>
                Proses berjalan aman di background dan dapat di-refresh sewaktu-waktu.
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
                        st.rerun(scope="app")
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
    uploaded_name = ""
    if uploaded_file is not None:
        try:
            uploaded_name = uploaded_file.name
            file_ext = os.path.splitext(uploaded_name)[1].lower()
            if file_ext == ".csv":
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
        except Exception as e:
            st.error(f"Error membaca file: {e}")
            return
    elif resume_checkpoint and checkpoint_exists:
        try:
            uploaded_name = checkpoint_file
            df = pd.read_csv(checkpoint_file)
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

    # Execution Trigger Section
    st.subheader("2. Mulai Batch Geocoding")

    if provider_choice in ["Geoapify", "HERE Geocoding API"] and not api_key.strip():
        st.warning(f"⚠️ Masukkan API Key {provider_choice} pada sidebar sebelum memulai geocoding.")
        return

    col_btn1, col_btn2 = st.columns([2, 5])
    with col_btn1:
        start_clicked = st.button(
            "🚀 Mulai Geocoding (Background)",
            type="primary",
            use_container_width=True
        )

    if start_clicked:
        task_mgr.start_task(
            df=df,
            address_col=address_col,
            provider=provider_choice,
            api_key=api_key.strip(),
            delay_seconds=delay_seconds,
            max_workers=max_workers,
            checkpoint_interval=checkpoint_interval,
            resume_from_checkpoint=resume_checkpoint,
            filename=uploaded_name
        )
        st.rerun(scope="app")


if __name__ == "__main__":
    main()
