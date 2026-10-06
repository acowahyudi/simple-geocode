import os
import re
import time
import threading
import requests
import pandas as pd
from typing import Tuple, Dict, Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

_thread_local = threading.local()

def get_session() -> requests.Session:
    """Retrieves or creates a thread-local requests.Session with realistic browser User-Agent."""
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"
        })
        _thread_local.session = session
    return _thread_local.session

# Global rate-limiting lock for OpenStreetMap / Nominatim
_nominatim_lock = threading.Lock()
_last_nominatim_time = 0.0

def rate_limit_nominatim(delay_seconds: float = 3.0):
    """Enforces a configurable delay per request to respect OpenStreetMap Nominatim usage policy and prevent IP blocks."""
    global _last_nominatim_time
    with _nominatim_lock:
        now = time.time()
        elapsed = now - _last_nominatim_time
        if elapsed < delay_seconds:
            time.sleep(delay_seconds - elapsed)
        _last_nominatim_time = time.time()


def clean_address_for_search(address: str) -> str:
    """
    Cleans and normalizes Indonesian addresses for higher geocoding match rates.
    Expands common abbreviations (Jl. -> Jalan) and strips administrative noise
    (DESA/KELURAHAN, KECAMATAN, KABUPATEN, RT/RW, No. xx, Lantai, etc.).
    """
    if not address or not isinstance(address, str):
        return ""
    
    text = address.strip()
    
    # Strip administrative noise prefixes while preserving the name
    text = re.sub(r'(?i)\bDESA/KELURAHAN\b', '', text)
    text = re.sub(r'(?i)\b(DESA|KELURAHAN|KEL|KECAMATAN|KEC|KABUPATEN|KAB|PROVINSI|PROV)\b\.?', '', text)
    
    # Standardize street abbreviations
    text = re.sub(r'(?i)\b(JL|JLN)\b\.?', 'Jalan', text)
    text = re.sub(r'(?i)\b(GD|GED)\b\.?', 'Gedung', text)
    text = re.sub(r'(?i)\bKAV\b\.?', 'Kavling', text)
    text = re.sub(r'(?i)\b(JEND|JENDRAL)\b\.?', 'Jenderal', text)
    text = re.sub(r'(?i)\bGG\b\.?', '', text)
    
    # Strip RT/RW, No., Floor, Block
    text = re.sub(r'(?i)\b(RT|RW)\b\.?\s*\d+', '', text)
    text = re.sub(r'(?i)\bNO\b\.?\s*\d+\w*', '', text)
    text = re.sub(r'(?i)\b(LT|LANTAI)\b\.?\s*\d+', '', text)
    text = re.sub(r'(?i)\bBLOK\b\s*\w+', '', text)
    
    # Clean leftover dots, commas, spaces
    text = re.sub(r'\s*\.\s*', ' ', text)
    text = re.sub(r'\s*,\s*', ', ', text)
    text = re.sub(r'\s+', ' ', text).strip(' ,.-')
    return text


def build_here_query_chain(address: str) -> list:
    """
    Builds a dynamic fallback chain of search queries from an address string.
    Dynamically respects the user's data (whether from Kalimantan Timur, Jawa, Bali, etc.)
    without hardcoding any province name.
    """
    if not address or not isinstance(address, str):
        return []
        
    queries = []
    cleaned = clean_address_for_search(address)
    
    # 1. Cleaned full address + ', Indonesia'
    if cleaned:
        q1 = f"{cleaned}, Indonesia"
        if q1 not in queries:
            queries.append(q1)
            
    # Extract segments separated by comma
    raw_segments = [s.strip() for s in address.split(',') if s.strip()]
    cleaned_segments = [clean_address_for_search(s) for s in raw_segments]
    cleaned_segments = [s for s in cleaned_segments if s]
    
    dedup_segments = []
    for seg in cleaned_segments:
        if not dedup_segments or dedup_segments[-1].lower() != seg.lower():
            dedup_segments.append(seg)
            
    # Step 2: Last 3 segments (Village, District, Regency) + ', Indonesia'
    if len(dedup_segments) >= 3:
        q2 = f"{', '.join(dedup_segments[-3:])}, Indonesia"
        if q2 not in queries:
            queries.append(q2)
            
    # Step 3: Last 2 segments (District, Regency) + ', Indonesia'
    if len(dedup_segments) >= 2:
        q3 = f"{', '.join(dedup_segments[-2:])}, Indonesia"
        if q3 not in queries:
            queries.append(q3)
            
    # Step 4: Last segment (Regency/City) + ', Indonesia'
    if len(dedup_segments) >= 1:
        q4 = f"{dedup_segments[-1]}, Indonesia"
        if q4 not in queries:
            queries.append(q4)
            
    # Step 5: Raw address + ', Indonesia'
    q_raw = f"{address.strip()}, Indonesia"
    if q_raw not in queries:
        queries.append(q_raw)
        
    # Step 6: Raw address as last resort
    if address.strip() not in queries:
        queries.append(address.strip())
        
    return queries


def geocode_geoapify(
    address: str, 
    api_key: str, 
    timeout: float = 6.0
) -> Tuple[Optional[float], Optional[float], str]:
    """Geocodes an address using Geoapify API (Free 3,000 req/day)."""
    session = get_session()
    url = "https://api.geoapify.com/v1/geocode/search"
    
    queries_to_try = [address]
    cleaned = clean_address_for_search(address)
    if cleaned and cleaned != address:
        queries_to_try.append(cleaned)
        
    for q in queries_to_try:
        params = {
            "text": q,
            "apiKey": api_key,
            "limit": 1
        }
        try:
            res = session.get(url, params=params, timeout=timeout)
            if res.status_code == 200:
                features = res.json().get("features", [])
                if features:
                    coords = features[0].get("geometry", {}).get("coordinates", [])
                    if len(coords) >= 2:
                        return float(coords[1]), float(coords[0]), "success"
            elif res.status_code in (401, 403):
                return None, None, "invalid_api_key"
            elif res.status_code == 429:
                return None, None, "rate_limited"
        except Exception:
            pass

    return None, None, "not_found"


def geocode_nominatim(
    address: str, 
    delay_seconds: float = 3.0,
    timeout: float = 6.0,
    max_retries: int = 3
) -> Tuple[Optional[float], Optional[float], str]:
    """
    Geocodes an address using OpenStreetMap / Nominatim API with configurable delay,
    rate-limit backoff, realistic user-agent, and fallback address cleaning.
    """
    session = get_session()
    url = "https://nominatim.openstreetmap.org/search"
    backoff = max(delay_seconds, 3.0)
    
    queries_to_try = [address]
    cleaned = clean_address_for_search(address)
    if cleaned and cleaned != address:
        queries_to_try.append(cleaned)
        
    for q in queries_to_try:
        last_status = "not_found"
        backoff = max(delay_seconds, 3.0)
        for attempt in range(max_retries):
            rate_limit_nominatim(delay_seconds=delay_seconds)
            params = {
                "q": q,
                "format": "json",
                "limit": 1
            }
            try:
                res = session.get(url, params=params, timeout=timeout)
                
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        lat = float(data[0].get("lat"))
                        lng = float(data[0].get("lon"))
                        return lat, lng, "success"
                    # Address text not in OSM index
                    last_status = "not_found"
                    break
                elif res.status_code == 429:
                    last_status = "rate_limited"
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                elif res.status_code == 403:
                    return None, None, "access_denied_403"
                else:
                    return None, None, f"http_{res.status_code}"
            except requests.exceptions.Timeout:
                last_status = "network_timeout"
                time.sleep(backoff)
                backoff *= 1.5
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
                else:
                    return None, None, "network_dns_error"
            except Exception as e:
                return None, None, f"error_{str(e)}"
                
        if last_status == "rate_limited":
            return None, None, "rate_limited"

    return None, None, "not_found"


def geocode_here(
    address: str, 
    api_key: str, 
    timeout: float = 6.0
) -> Tuple[Optional[float], Optional[float], str]:
    """
    Geocodes an address using HERE Geocoding API with dynamic Indonesian fallback query chain,
    countryCode filtering (IDN), rate-limit retry backoff, and robust error handling.
    """
    session = get_session()
    url = "https://geocode.search.hereapi.com/v1/geocode"
    
    queries_to_try = build_here_query_chain(address)
    if not queries_to_try:
        queries_to_try = [address]
        
    last_status = "not_found"
    
    for q in queries_to_try:
        params = {
            "q": q,
            "apiKey": api_key,
            "limit": 1,
            "in": "countryCode:IDN"
        }
        for attempt in range(3):
            try:
                res = session.get(url, params=params, timeout=timeout)
                if res.status_code == 200:
                    items = res.json().get("items", [])
                    if items:
                        pos = items[0].get("position", {})
                        return float(pos.get("lat")), float(pos.get("lng")), "success"
                    last_status = "not_found"
                    break
                elif res.status_code in (401, 403):
                    return None, None, "invalid_api_key"
                elif res.status_code == 429:
                    last_status = "rate_limited"
                    time.sleep(1.5 * (attempt + 1))
                    continue
                else:
                    last_status = f"http_{res.status_code}"
                    break
            except requests.exceptions.Timeout:
                last_status = "network_timeout"
                time.sleep(1.0)
            except requests.exceptions.ConnectionError:
                if attempt < 2:
                    time.sleep(1.0)
                    continue
                return None, None, "network_dns_error"
            except Exception as e:
                return None, None, f"error_{str(e)}"
                
    return None, None, last_status


def geocode_single_address(
    address: str,
    provider: str,
    api_key: str = "",
    delay_seconds: float = 3.0,
    timeout: float = 6.0
) -> Tuple[Optional[float], Optional[float], str]:
    """Unified wrapper function for geocoding a single address."""
    if not isinstance(address, str) or not address.strip():
        return None, None, "empty_address"
    
    clean_addr = address.strip()
    
    if provider == "Geoapify":
        return geocode_geoapify(clean_addr, api_key, timeout)
    elif provider == "OpenStreetMap (Nominatim)":
        return geocode_nominatim(clean_addr, delay_seconds=delay_seconds, timeout=timeout)
    elif provider == "HERE Geocoding API":
        return geocode_here(clean_addr, api_key, timeout)
    else:
        return None, None, "unknown_provider"


def test_api_provider(provider: str, api_key: str = "", delay_seconds: float = 3.0, **kwargs) -> Tuple[bool, str]:
    """Tests connection and sample search capability for selected provider."""
    delay = kwargs.get("delay_seconds", delay_seconds)
    test_address = "Monas, Jakarta"
    lat, lng, status = geocode_single_address(test_address, provider, api_key, delay_seconds=delay)
    
    if status == "invalid_api_key":
        return False, "API Key tidak valid atau tidak memiliki akses."
    elif status == "access_denied_403":
        return False, "Akses ditolak (HTTP 403) oleh OpenStreetMap server."
    elif status == "rate_limited":
        return False, "IP Anda terdeteksi Rate-Limited (HTTP 429) oleh provider."
    elif status == "network_dns_error":
        return False, "Gagal koneksi / DNS (NameResolutionError). Periksa koneksi internet Anda."
    elif status == "success":
        return True, f"Koneksi {provider} berhasil! Koordinat ditemukan ({lat}, {lng})."
    elif status == "not_found":
        return True, f"Koneksi ke {provider} berhasil! (Tetapi alamat sampel tidak terindeks)."
    elif status.startswith("error_"):
        return False, f"Pengujian koneksi gagal: {status.replace('error_', '')}"
    else:
        return False, f"Pengujian gagal dengan status: {status}"


class BatchGeocoderEngine:
    """
    Engine for batch geocoding with multi-provider support, configurable delay,
    auto-checkpointing, and real-time metrics calculation.
    """
    CHECKPOINT_FILE = "checkpoint_geocoded.csv"

    def __init__(
        self,
        df: pd.DataFrame,
        address_col: str,
        provider: str,
        api_key: str = "",
        delay_seconds: float = 3.0,
        max_workers: int = 5,
        checkpoint_interval: int = 100,
        resume_from_checkpoint: bool = False
    ):
        self.df = df.copy()
        self.address_col = address_col
        self.provider = provider
        self.api_key = api_key
        self.delay_seconds = delay_seconds
        
        if provider == "OpenStreetMap (Nominatim)":
            self.max_workers = 1
        else:
            self.max_workers = max_workers
            
        self.checkpoint_interval = checkpoint_interval
        self.stop_requested = False
        self.lock = threading.Lock()

        if "Latitude" not in self.df.columns:
            self.df["Latitude"] = None
        if "Longitude" not in self.df.columns:
            self.df["Longitude"] = None
        if "Geocode_Status" not in self.df.columns:
            self.df["Geocode_Status"] = "pending"

        if resume_from_checkpoint and os.path.exists(self.CHECKPOINT_FILE):
            self.load_checkpoint()

        self.total_rows = len(self.df)
        already_processed = self.df["Geocode_Status"].isin(["success", "not_found", "empty_address"]).sum()
        self.processed_count = int(already_processed)
        self.start_processed_count = self.processed_count
        self.success_count = int((self.df["Geocode_Status"] == "success").sum())
        self.failed_count = int((self.df["Geocode_Status"].isin(["not_found", "empty_address"]) | 
                                 self.df["Geocode_Status"].str.startswith("http_") |
                                 self.df["Geocode_Status"].str.startswith("error") |
                                 self.df["Geocode_Status"].str.startswith("access_denied")).sum())

        self.start_time = None
        self.last_checkpoint_save = self.processed_count
        self._executor = None
        self.recent_logs = []

    def get_recent_logs(self) -> list:
        """Returns the most recent geocoded address activities."""
        with self.lock:
            return list(self.recent_logs)

    def get_valid_coordinates_dataframe(self, max_points: Optional[int] = None) -> pd.DataFrame:
        """Thread-safely extracts rows that have successfully found coordinates."""
        with self.lock:
            mask = (self.df["Geocode_Status"] == "success") & self.df["Latitude"].notna() & self.df["Longitude"].notna()
            if not mask.any():
                return pd.DataFrame()
            cols = [self.address_col, "Latitude", "Longitude"]
            sub_df = self.df.loc[mask, cols].copy()
            sub_df["row_index"] = sub_df.index + 1
            if max_points and len(sub_df) > max_points:
                sub_df = sub_df.tail(max_points)
            return sub_df

    def load_checkpoint(self):
        """Loads state from existing checkpoint file."""
        try:
            cp_df = pd.read_csv(self.CHECKPOINT_FILE)
            if len(cp_df) == len(self.df):
                if "Latitude" in cp_df.columns:
                    self.df["Latitude"] = cp_df["Latitude"]
                if "Longitude" in cp_df.columns:
                    self.df["Longitude"] = cp_df["Longitude"]
                if "Geocode_Status" in cp_df.columns:
                    self.df["Geocode_Status"] = cp_df["Geocode_Status"]
        except Exception as e:
            print(f"Error loading checkpoint: {e}")

    def save_checkpoint(self):
        """Saves current dataframe state to CSV file."""
        with self.lock:
            try:
                self.df.to_csv(self.CHECKPOINT_FILE, index=False)
            except Exception as e:
                print(f"Error saving checkpoint: {e}")

    def process_batch(self, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> pd.DataFrame:
        """Executes batch geocoding process and updates UI callback periodically."""
        self.start_time = time.time()
        self.start_processed_count = self.processed_count
        
        pending_mask = self.df["Geocode_Status"] == "pending"
        pending_indices = self.df[pending_mask].index.tolist()

        if not pending_indices:
            if progress_callback:
                progress_callback(self.get_metrics())
            return self.df

        def _worker(idx: int):
            if self.stop_requested:
                return idx, None, None, "stopped"
            addr = self.df.at[idx, self.address_col]
            lat, lng, status = geocode_single_address(
                address=str(addr) if pd.notna(addr) else "",
                provider=self.provider,
                api_key=self.api_key,
                delay_seconds=self.delay_seconds,
                timeout=6.0
            )
            return idx, lat, lng, status

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            self._executor = executor
            futures = {executor.submit(_worker, idx): idx for idx in pending_indices}

            for count, future in enumerate(as_completed(futures), 1):
                if self.stop_requested:
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                    break
                try:
                    idx, lat, lng, status = future.result()
                    with self.lock:
                        self.df.at[idx, "Latitude"] = lat
                        self.df.at[idx, "Longitude"] = lng
                        self.df.at[idx, "Geocode_Status"] = status

                        self.processed_count += 1
                        if status == "success":
                            self.success_count += 1
                        else:
                            self.failed_count += 1

                        addr_str = str(self.df.at[idx, self.address_col]) if pd.notna(self.df.at[idx, self.address_col]) else ""
                        if len(addr_str) > 45:
                            addr_str = addr_str[:42] + "..."
                        
                        coords_str = f"{lat:.4f}, {lng:.4f}" if (lat is not None and lng is not None) else "-"
                        self.recent_logs.append({
                            "row": idx + 1,
                            "address": addr_str,
                            "coords": coords_str,
                            "status": status,
                            "time": time.strftime("%H:%M:%S")
                        })
                        if len(self.recent_logs) > 6:
                            self.recent_logs.pop(0)

                    if (self.processed_count - self.last_checkpoint_save) >= self.checkpoint_interval:
                        self.save_checkpoint()
                        self.last_checkpoint_save = self.processed_count

                    refresh_step = 1 if self.provider == "OpenStreetMap (Nominatim)" else 5
                    if progress_callback and (count % refresh_step == 0 or count == len(pending_indices)):
                        progress_callback(self.get_metrics())

                except Exception as e:
                    print(f"Worker exception: {e}")

        self.save_checkpoint()
        if progress_callback:
            progress_callback(self.get_metrics())

        return self.df

    def stop(self):
        """Requests process cancellation and cancels queued threads."""
        self.stop_requested = True
        if hasattr(self, "_executor") and self._executor:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def get_metrics(self) -> Dict[str, Any]:
        """Calculates current metrics for stream updating."""
        with self.lock:
            elapsed = (time.time() - self.start_time) if self.start_time else 0.001
            processed = self.processed_count
            total = self.total_rows
            remaining = total - processed

            rows_in_this_run = max(0, processed - getattr(self, "start_processed_count", 0))
            speed = rows_in_this_run / elapsed if elapsed > 0 else 0.0

            if speed > 0 and remaining > 0:
                eta_sec = remaining / speed
                hrs = int(eta_sec // 3600)
                mins = int((eta_sec % 3600) // 60)
                secs = int(eta_sec % 60)
                if hrs > 0:
                    eta_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
                else:
                    eta_str = f"{mins:02d}:{secs:02d}"
            else:
                eta_str = "00:00" if remaining == 0 else "--:--"

            pct = float((processed / total) * 100) if total > 0 else 100.0

            return {
                "processed": processed,
                "total": total,
                "success": self.success_count,
                "failed": self.failed_count,
                "speed": round(speed, 2),
                "eta": eta_str,
                "percentage": round(pct, 1),
                "elapsed": round(elapsed, 1)
            }


class GeocodeTaskManager:
    """
    Global thread-safe manager for background geocoding tasks.
    Ensures that tasks persist across browser reloads (F5) and tab closures.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.status = "idle"  # idle, running, stopping, stopped, completed, error
        self.error_message: Optional[str] = None
        self.engine: Optional[BatchGeocoderEngine] = None
        self.thread: Optional[threading.Thread] = None
        self.filename: str = ""
        self.address_col: str = ""
        self.provider: str = ""
        self.api_key: str = ""
        self.delay_seconds: float = 3.0
        self.max_workers: int = 5
        self.checkpoint_interval: int = 100
        self.df_result: Optional[pd.DataFrame] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def is_running(self) -> bool:
        with self.lock:
            return self.status in ("running", "stopping")

    def start_task(
        self,
        df: pd.DataFrame,
        address_col: str,
        provider: str,
        api_key: str = "",
        delay_seconds: float = 3.0,
        max_workers: int = 5,
        checkpoint_interval: int = 100,
        resume_from_checkpoint: bool = False,
        filename: str = ""
    ) -> bool:
        with self.lock:
            if self.status in ("running", "stopping"):
                return False

            self.status = "running"
            self.error_message = None
            self.filename = filename or "data_geocoded"
            self.address_col = address_col
            self.provider = provider
            self.api_key = api_key
            self.delay_seconds = delay_seconds
            self.max_workers = max_workers
            self.checkpoint_interval = checkpoint_interval
            self.start_time = time.time()
            self.end_time = None
            self.df_result = None

            self.engine = BatchGeocoderEngine(
                df=df,
                address_col=address_col,
                provider=provider,
                api_key=api_key,
                delay_seconds=delay_seconds,
                max_workers=max_workers,
                checkpoint_interval=checkpoint_interval,
                resume_from_checkpoint=resume_from_checkpoint
            )

        def _run():
            try:
                res = self.engine.process_batch()
                with self.lock:
                    self.df_result = res
                    self.end_time = time.time()
                    if self.engine.stop_requested:
                        self.status = "stopped"
                    else:
                        self.status = "completed"
            except Exception as e:
                with self.lock:
                    self.status = "error"
                    self.error_message = str(e)
                    self.end_time = time.time()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()
        return True

    def stop_task(self):
        with self.lock:
            if self.engine and self.status == "running":
                self.status = "stopping"
                self.engine.stop()

    def resume_task(self) -> bool:
        with self.lock:
            if self.status != "stopped" or self.engine is None:
                return False
            df = self.engine.df
            address_col = self.address_col
            provider = self.provider
            api_key = self.api_key
            delay_seconds = self.delay_seconds
            max_workers = self.max_workers
            checkpoint_interval = self.checkpoint_interval
            filename = self.filename

        return self.start_task(
            df=df,
            address_col=address_col,
            provider=provider,
            api_key=api_key,
            delay_seconds=delay_seconds,
            max_workers=max_workers,
            checkpoint_interval=checkpoint_interval,
            resume_from_checkpoint=False,
            filename=filename
        )

    def reset_task(self):
        with self.lock:
            if self.status not in ("running", "stopping"):
                self.status = "idle"
                self.error_message = None
                self.engine = None
                self.thread = None
                self.filename = ""
                self.address_col = ""
                self.provider = ""
                self.df_result = None
                self.start_time = None
                self.end_time = None

    def get_valid_points(self, max_points: Optional[int] = None) -> pd.DataFrame:
        """Thread-safely returns currently geocoded valid points for map rendering."""
        with self.lock:
            engine = self.engine
            df_result = self.df_result
            address_col = self.address_col

        if engine is not None:
            if hasattr(engine, "get_valid_coordinates_dataframe"):
                return engine.get_valid_coordinates_dataframe(max_points=max_points)
            else:
                with engine.lock:
                    mask = (engine.df["Geocode_Status"] == "success") & engine.df["Latitude"].notna() & engine.df["Longitude"].notna()
                    if not mask.any():
                        return pd.DataFrame()
                    cols = [address_col, "Latitude", "Longitude"] if address_col in engine.df.columns else ["Latitude", "Longitude"]
                    sub_df = engine.df.loc[mask, cols].copy()
                    sub_df["row_index"] = sub_df.index + 1
                    if max_points and len(sub_df) > max_points:
                        sub_df = sub_df.tail(max_points)
                    return sub_df
        elif df_result is not None and "Latitude" in df_result.columns and "Longitude" in df_result.columns:
            mask = (df_result["Geocode_Status"] == "success") & df_result["Latitude"].notna() & df_result["Longitude"].notna()
            if not mask.any():
                return pd.DataFrame()
            cols = [address_col, "Latitude", "Longitude"] if address_col in df_result.columns else ["Latitude", "Longitude"]
            sub_df = df_result.loc[mask, cols].copy()
            sub_df["row_index"] = sub_df.index + 1
            if address_col not in sub_df.columns:
                sub_df[address_col] = "Alamat"
            if max_points and len(sub_df) > max_points:
                sub_df = sub_df.tail(max_points)
            return sub_df
        return pd.DataFrame()

    def get_info(self) -> Dict[str, Any]:
        with self.lock:
            status = self.status
            error_msg = self.error_message
            filename = self.filename
            address_col = self.address_col
            provider = self.provider
            api_key = self.api_key
            delay_seconds = self.delay_seconds
            max_workers = self.max_workers
            checkpoint_interval = self.checkpoint_interval
            engine = self.engine
            df_result = self.df_result

        metrics = engine.get_metrics() if engine else {
            "processed": 0, "total": 0, "success": 0, "failed": 0,
            "speed": 0.0, "eta": "--:--", "percentage": 0.0, "elapsed": 0.0
        }
        recent_logs = engine.get_recent_logs() if engine else []
        current_df = df_result if df_result is not None else (engine.df if engine else None)

        return {
            "status": status,
            "error_message": error_msg,
            "filename": filename,
            "address_col": address_col,
            "provider": provider,
            "api_key": api_key,
            "delay_seconds": delay_seconds,
            "max_workers": max_workers,
            "checkpoint_interval": checkpoint_interval,
            "metrics": metrics,
            "recent_logs": recent_logs,
            "df": current_df
        }

