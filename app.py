import os
import io
import time
import types
import importlib
import pandas as pd
import pydeck as pdk
import streamlit as st
import geocoder
importlib.reload(geocoder)
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

def get_active_task_manager() -> GeocodeTaskManager:
    mgr = get_global_task_manager()
    # Auto-repair cached instance if modified in geocoder.py during live reload
    for attr in dir(GeocodeTaskManager):
        if not attr.startswith("__") and callable(getattr(GeocodeTaskManager, attr)):
            if not hasattr(mgr, attr) or getattr(mgr.__class__, attr, None) is None:
                setattr(mgr, attr, types.MethodType(getattr(GeocodeTaskManager, attr), mgr))
    return mgr

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
        margin-bottom: 20px;
    }
    .metric-card {
        background: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px 18px;
        text-align: center;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .metric-card:hover {
        border-color: #38BDF8;
        transform: translateY(-2px);
    }
    .metric-title {
        font-size: 0.82rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94A3B8;
        margin-bottom: 6px;
    }
    .metric-value {
        font-size: 1.7rem;
        font-weight: 700;
        color: #F8FAFC;
    }
    .metric-subtitle {
        font-size: 0.78rem;
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
        color: #7f7215;
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
        margin-top: 10px;
        margin-bottom: 14px;
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


def render_interactive_map(points_df: pd.DataFrame, address_col: str, height: int = 480):
    """
    Renders an interactive map using PyDeck with dark styling, 
    responsive pins, and rich hover tooltips for cross-checking accuracy.
    """
    if points_df is None or points_df.empty:
        st.info("🗺️ Belum ada titik koordinat yang berhasil ditemukan untuk ditampilkan.")
        return

    plot_df = points_df.copy()
    plot_df["latitude"] = pd.to_numeric(plot_df["Latitude"], errors="coerce")
    plot_df["longitude"] = pd.to_numeric(plot_df["Longitude"], errors="coerce")
    plot_df = plot_df.dropna(subset=["latitude", "longitude"])

    if plot_df.empty:
        st.info("🗺️ Belum ada koordinat numerik valid untuk ditampilkan.")
        return

    # Prepare tooltip fields
    addr_col_name = address_col if address_col in plot_df.columns else plot_df.columns[0]
    plot_df["formatted_address"] = plot_df[addr_col_name].astype(str)
    plot_df["row"] = plot_df["row_index"].astype(int) if "row_index" in plot_df.columns else (plot_df.index + 1)
    plot_df["lat_str"] = plot_df["latitude"].apply(lambda x: f"{x:.5f}")
    plot_df["lng_str"] = plot_df["longitude"].apply(lambda x: f"{x:.5f}")

    center_lat = float(plot_df["latitude"].median())
    center_lng = float(plot_df["longitude"].median())

    try:
        layer = pdk.Layer(
            "ScatterplotLayer",
            data=plot_df,
            get_position=["longitude", "latitude"],
            get_color=[56, 189, 248, 220],  # Cyan / Light Blue
            get_radius=5000,
            radius_min_pixels=6,
            radius_max_pixels=25,
            pickable=True,
            auto_highlight=True,
        )

        view_state = pdk.ViewState(
            latitude=center_lat,
            longitude=center_lng,
            zoom=5,
            pitch=0
        )

        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            map_style=pdk.map_styles.DARK,
            tooltip={
                "html": """
                <div style="font-family: sans-serif; line-height: 1.4;">
                    <b style="color: #38BDF8;">📍 Baris #{row}</b><br/>
                    <b>Alamat:</b> {formatted_address}<br/>
                    <b>Koordinat:</b> {lat_str}, {lng_str}
                </div>
                """,
                "style": {
                    "backgroundColor": "#0F172A",
                    "color": "#F8FAFC",
                    "border": "1px solid #38BDF8",
                    "fontSize": "12px",
                    "borderRadius": "8px",
                    "padding": "10px",
                    "boxShadow": "0 4px 15px rgba(0,0,0,0.5)"
                }
            }
        )

        st.pydeck_chart(deck, use_container_width=True, height=height)
    except Exception:
        # Fallback to standard st.map
        st.map(plot_df[["latitude", "longitude"]], zoom=5, use_container_width=True)


@st.fragment(run_every="2s")
def render_running_dashboard(task_mgr: GeocodeTaskManager):
    """
    Real-time progress dashboard rendered every 2 seconds without full page reload.
    Survives browser refresh and updates metrics, map, and activity feed smoothly.
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

    # Stop Button & Background Info
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
            st.caption("💡 *Proses berjalan di background. Anda bebas me-refresh browser (F5) tanpa kehilangan progres!*")

    st.write("")

    # Map & Activity Tabs for Live Inspection
    address_col = info.get("address_col", "Alamat")
    valid_points_df = pd.DataFrame()
    if hasattr(task_mgr, "get_valid_points"):
        try:
            valid_points_df = task_mgr.get_valid_points()
        except Exception:
            pass

    if valid_points_df.empty:
        curr_df = info.get("df")
        if curr_df is not None and "Latitude" in curr_df.columns and "Longitude" in curr_df.columns:
            mask = (curr_df["Geocode_Status"] == "success") & curr_df["Latitude"].notna() & curr_df["Longitude"].notna()
            if mask.any():
                cols = [address_col, "Latitude", "Longitude"] if address_col in curr_df.columns else ["Latitude", "Longitude"]
                valid_points_df = curr_df.loc[mask, cols].copy()
                valid_points_df["row_index"] = valid_points_df.index + 1

    valid_count = len(valid_points_df)

    tab_map, tab_activity = st.tabs([
        f"🗺️ Visualisasi Peta Real-Time ({valid_count:,} Titik Sukses)",
        "📡 Log Aktivitas Real-Time"
    ])

    with tab_map:
        if valid_count > 0:
            st.caption("💡 *Arahkan kursor (*hover*) pada titik di peta untuk melihat alamat lengkap & koordinat. Peta diperbarui secara live.*")
            render_interactive_map(valid_points_df, address_col=address_col, height=450)

            with st.expander("🔍 Cek Tabel 10 Titik Terakhir (dengan Tautan Langsung ke Google Maps)", expanded=False):
                last_points = valid_points_df.tail(10).iloc[::-1].copy()
                check_rows = []
                for _, row in last_points.iterrows():
                    r_idx = int(row.get("row_index", 0))
                    r_addr = str(row.get(address_col, ""))
                    r_lat = float(row.get("Latitude", 0))
                    r_lng = float(row.get("Longitude", 0))
                    gmaps_url = f"https://www.google.com/maps?q={r_lat},{r_lng}"
                    check_rows.append({
                        "Baris": f"#{r_idx}",
                        "Alamat": r_addr,
                        "Latitude": f"{r_lat:.6f}",
                        "Longitude": f"{r_lng:.6f}",
                        "Google Maps": gmaps_url
                    })

                check_df = pd.DataFrame(check_rows)
                st.dataframe(
                    check_df,
                    column_config={
                        "Google Maps": st.column_config.LinkColumn(
                            "Verifikasi Lokasi",
                            display_text="Buka di Maps ↗"
                        )
                    },
                    use_container_width=True,
                    hide_index=True
                )
        else:
            st.info("🗺️ **Menunggu koordinat sukses pertama...** Peta akan muncul dan diperbarui secara otomatis begitu ada data yang berhasil digeocode.")

    with tab_activity:
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
        else:
            st.caption("Belum ada log aktivitas.")


def render_results_section(df: pd.DataFrame, address_col: str = "", subtitle: str = ""):
    """Renders download buttons, table tab, and interactive map tab for completed or stopped results."""
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

    tab_t, tab_m = st.tabs(["📋 Tabel Hasil Geocoding", "🗺️ Visualisasi Peta & Cross-Check"])

    with tab_t:
        st.dataframe(df, use_container_width=True)

    with tab_m:
        if "Latitude" in df.columns and "Longitude" in df.columns:
            mask = (df["Geocode_Status"] == "success") & df["Latitude"].notna() & df["Longitude"].notna()
            valid_points = df[mask].copy()
            valid_count = len(valid_points)
            if valid_count > 0:
                st.markdown(f"**Menampilkan {valid_count:,} titik lokasi sukses pada peta interaktif:**")
                st.caption("💡 *Arahkan kursor (*hover*) pada titik di peta untuk melihat alamat lengkap & koordinat.*")
                render_interactive_map(valid_points, address_col=address_col or df.columns[0], height=500)

                with st.expander("🔍 Cek Tabel Lokasi dengan Tautan Google Maps", expanded=False):
                    check_rows = []
                    for idx, row in valid_points.head(50).iterrows():
                        r_addr = str(row.get(address_col, "")) if address_col in row else str(row.iloc[0])
                        r_lat = float(row.get("Latitude", 0))
                        r_lng = float(row.get("Longitude", 0))
                        gmaps_url = f"https://www.google.com/maps?q={r_lat},{r_lng}"
                        check_rows.append({
                            "Baris": f"#{idx + 1}",
                            "Alamat": r_addr,
                            "Latitude": f"{r_lat:.6f}",
                            "Longitude": f"{r_lng:.6f}",
                            "Google Maps": gmaps_url
                        })
                    check_df = pd.DataFrame(check_rows)
                    st.dataframe(
                        check_df,
                        column_config={
                            "Google Maps": st.column_config.LinkColumn(
                                "Verifikasi Lokasi",
                                display_text="Buka di Maps ↗"
                            )
                        },
                        use_container_width=True,
                        hide_index=True
                    )
            else:
                st.info("Belum ada koordinat sukses yang valid untuk ditampilkan pada peta.")


def main():
    task_mgr = get_active_task_manager()
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
            render_results_section(task_info["df"], address_col=task_info["address_col"], subtitle="Hasil lengkap batch geocoding yang telah selesai.")
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
            render_results_section(task_info["df"], address_col=task_info["address_col"], subtitle="Hasil data yang sempat terproses sebelum dihentikan.")
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
            <div class="info-box" style="background: rgba(34, 197, 94, 0.1); border-color: rgba(34, 197, 94, 0.3); color: rgb(21 112 54);">
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
