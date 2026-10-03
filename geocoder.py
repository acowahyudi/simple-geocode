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
    Expands common abbreviations (Jl. -> Jalan) and strips noise (No. xx, RT/RW, Lantai, etc.).
    """
    if not address:
        return ""
    
    text = address.strip()
    text = re.sub(r'(?i)\bjl\.?\b', 'Jalan ', text)
    text = re.sub(r'(?i)\bgd\.?\b|\bged\.?\b', 'Gedung ', text)
    text = re.sub(r'(?i)\bkav\.?\b', 'Kavling ', text)
    text = re.sub(r'(?i)\bjend\.?\b|\bjendral\b', 'Jenderal ', text)
    text = re.sub(r'(?i)\bkec\.?\b', '', text)
    text = re.sub(r'(?i)\bkel\.?\b', '', text)
    
    text = re.sub(r'(?i)\bno\.?\s*\d+\w*', '', text)
    text = re.sub(r'(?i)\b(rt|rw)\.?\s*\d+', '', text)
    text = re.sub(r'(?i)\blt\.?\s*\d+|\blantai\s*\d+', '', text)
    text = re.sub(r'(?i)\bblok\s*\w+', '', text)
    
    text = re.sub(r'\s+', ' ', text).strip(' ,.-')
    return text


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
    """Geocodes an address using HERE Geocoding API."""
    session = get_session()
    url = "https://geocode.search.hereapi.com/v1/geocode"
    params = {
        "q": address,
        "apiKey": api_key,
        "limit": 1
    }
    try:
        res = session.get(url, params=params, timeout=timeout)
        if res.status_code == 200:
            items = res.json().get("items", [])
            if items:
                pos = items[0].get("position", {})
                return float(pos.get("lat")), float(pos.get("lng")), "success"
            return None, None, "not_found"
        elif res.status_code in (401, 403):
            return None, None, "invalid_api_key"
        elif res.status_code == 429:
            return None, None, "rate_limited"
        else:
            return None, None, f"http_{res.status_code}"
    except requests.exceptions.ConnectionError:
        return None, None, "network_dns_error"
    except Exception as e:
        return None, None, f"error_{str(e)}"


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
        self.success_count = int((self.df["Geocode_Status"] == "success").sum())
        self.failed_count = int((self.df["Geocode_Status"].isin(["not_found", "empty_address"]) | 
                                 self.df["Geocode_Status"].str.startswith("http_") |
                                 self.df["Geocode_Status"].str.startswith("error") |
                                 self.df["Geocode_Status"].str.startswith("access_denied")).sum())

        self.start_time = None
        self.last_checkpoint_save = self.processed_count

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
            futures = {executor.submit(_worker, idx): idx for idx in pending_indices}

            for count, future in enumerate(as_completed(futures), 1):
                if self.stop_requested:
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

                    if (self.processed_count - self.last_checkpoint_save) >= self.checkpoint_interval:
                        self.save_checkpoint()
                        self.last_checkpoint_save = self.processed_count

                    refresh_step = 1 if self.provider == "OpenStreetMap (Nominatim)" else 10
                    if progress_callback and (count % refresh_step == 0 or count == len(pending_indices)):
                        progress_callback(self.get_metrics())

                except Exception as e:
                    print(f"Worker exception: {e}")

        self.save_checkpoint()
        if progress_callback:
            progress_callback(self.get_metrics())

        return self.df

    def stop(self):
        """Requests process cancellation."""
        self.stop_requested = True

    def get_metrics(self) -> Dict[str, Any]:
        """Calculates current metrics for stream updating."""
        with self.lock:
            elapsed = (time.time() - self.start_time) if self.start_time else 0.001
            processed = self.processed_count
            total = self.total_rows
            remaining = total - processed

            speed = processed / elapsed if elapsed > 0 else 0.0

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
                "percentage": round(pct, 1)
            }
