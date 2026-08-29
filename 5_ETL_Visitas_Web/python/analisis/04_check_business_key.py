from pathlib import Path
import csv
from collections import Counter

project_folder = Path(__file__).resolve().parent.parent.parent
source_folder = project_folder / "data" / "seed"

files = list(source_folder.glob("*.txt"))

for file in files:
    print("\n" + "=" * 60)
    print(f"FILE: {file.name}")
    print("=" * 60)

    with open(file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    business_keys = []

    for row in rows:
        email = row["email"].strip().lower()
        fecha_envio = row["Fecha envio"].strip()

        key = (email, fecha_envio)
        business_keys.append(key)

    counts = Counter(business_keys)

    duplicate_keys = {
        key: count
        for key, count in counts.items()
        if count > 1
    }

    print(f"Total rows: {len(rows)}")
    print(f"Unique email + Fecha envio combinations: {len(counts)}")
    print(f"Repeated combinations: {len(duplicate_keys)}")

    if duplicate_keys:
        print("\nExamples:")

        for key, count in list(duplicate_keys.items())[:10]:
            print(f"  {key}: {count} records")