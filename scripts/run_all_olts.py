from olt_loader import get_active_olts
from scraper_hioso import run_hioso
from scraper_vsol import run_vsol

SCRAPER_MAP = {
    "hioso": run_hioso,
    "vsol": run_vsol
}

def main():
    olts = get_active_olts()

    if not olts:
        print("⚠️ Tidak ada OLT aktif")
        return

    for olt in olts:
        brand = olt["brand"].lower()

        if brand not in SCRAPER_MAP:
            print(f"❌ Brand tidak dikenali: {brand}")
            continue

        print(f"\n🚀 Proses {olt['name']} ({brand})")
        SCRAPER_MAP[brand](olt)

if __name__ == "__main__":
    main()
