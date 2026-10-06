import os
import sys
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from geocoder import geocode_single_address

API_KEY = "YWOnk7C0lBIs37QEM8NhdiF2XPW7SW4Usu2M50y4HwA"
INPUT_EXCEL = "hasil_geocoding (1).xlsx"
OUTPUT_EXCEL = "hasil_geocoding_fixed.xlsx"
OUTPUT_CSV = "checkpoint_geocoded.csv"

def is_misplaced_kaltim(row):
    """
    Checks if a row that claimed success has coordinates far outside Kalimantan Timur
    despite being a Kalimantan Timur address.
    """
    if row.get("Geocode_Status") != "success":
        return False
    lat = row.get("Latitude")
    lng = row.get("Longitude")
    if pd.isna(lat) or pd.isna(lng):
        return True
    
    # Check if address belongs to Kaltim (default dataset context)
    addr_upper = str(row.get("address", "")).upper()
    kaltim_keywords = [
        "KALIMANTAN TIMUR", "KALTIM", "BALIKPAPAN", "SAMARINDA", "BONTANG",
        "PASER", "BERAU", "KUTAI", "PENAJAM", "NUNUKAN", "MALINAU", "BULUNGAN", "LONG IKIS", "SEBOLE", "SANGA-SANGA"
    ]
    
    is_kaltim_addr = any(kw in addr_upper for kw in kaltim_keywords)
    if is_kaltim_addr:
        # Kaltim bounding box: Lat -3.5 to 3.5, Lng 113.0 to 120.0
        if not (-3.5 <= float(lat) <= 3.5 and 113.0 <= float(lng) <= 120.0):
            return True
            
    return False

def main():
    if not os.path.exists(INPUT_EXCEL):
        print(f"File {INPUT_EXCEL} not found!")
        sys.exit(1)
        
    print(f"Loading dataset from {INPUT_EXCEL}...")
    df = pd.read_excel(INPUT_EXCEL)
    print(f"Total rows in dataset: {len(df)}")
    
    # Identify target rows to re-geocode
    status_failed = df["Geocode_Status"].isin(["not_found", "rate_limited", "pending"]) | df["Geocode_Status"].str.startswith("http") | df["Geocode_Status"].str.startswith("error")
    misplaced_mask = df.apply(is_misplaced_kaltim, axis=1)
    
    target_mask = status_failed | misplaced_mask
    target_indices = df[target_mask].index.tolist()
    
    print(f"Found {len(df[status_failed])} failed/unresolved rows.")
    print(f"Found {len(df[misplaced_mask])} misplaced coordinate rows.")
    print(f"Total target rows to re-geocode: {len(target_indices)}")
    
    if not target_indices:
        print("No target rows to re-geocode. All data is valid!")
        return
        
    success_count = 0
    failed_count = 0
    
    def _worker(idx):
        addr = str(df.at[idx, "address"]) if pd.notna(df.at[idx, "address"]) else ""
        lat, lng, status = geocode_single_address(
            address=addr,
            provider="HERE Geocoding API",
            api_key=API_KEY,
            timeout=8.0
        )
        return idx, lat, lng, status

    print("\nStarting batch re-geocoding using updated HERE API engine...")
    max_workers = 8
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, idx): idx for idx in target_indices}
        
        for count, future in enumerate(as_completed(futures), 1):
            try:
                idx, lat, lng, status = future.result()
                df.at[idx, "Latitude"] = lat
                df.at[idx, "Longitude"] = lng
                df.at[idx, "Geocode_Status"] = status
                
                if status == "success":
                    success_count += 1
                else:
                    failed_count += 1
                    
                if count % 50 == 0 or count == len(target_indices):
                    print(f"Progress: {count}/{len(target_indices)} | Fixed Success: {success_count} | Failed: {failed_count}")
            except Exception as e:
                print(f"Worker error on index {idx}: {e}")
                
    print(f"\nRe-geocoding finished!")
    print(f"Successfully re-geocoded: {success_count} / {len(target_indices)} rows")
    print(f"Remaining failed: {failed_count} rows")
    
    print(f"Saving updated CSV checkpoint to {OUTPUT_CSV}...")
    df.to_csv(OUTPUT_CSV, index=False)
    
    print(f"Saving updated Excel file to {OUTPUT_EXCEL}...")
    df.to_excel(OUTPUT_EXCEL, index=False)
    
    # Save back to original file as well if desired
    df.to_excel(INPUT_EXCEL, index=False)
    print("Updated original Excel file successfully!")

if __name__ == "__main__":
    main()
