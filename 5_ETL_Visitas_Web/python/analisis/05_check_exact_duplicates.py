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

    records = []

    for row in rows:
        record = tuple(row.values())
        records.append(record)

    counts = Counter(records)

    exact_duplicates = {
        record: count
        for record, count in counts.items()
        if count > 1
    }

    print(f"Total rows: {len(rows)}")
    print(f"Unique complete records: {len(counts)}")
    print(f"Exact duplicate records: {sum(count - 1 for count in exact_duplicates.values())}")

    if exact_duplicates:
        print("\nExact duplicate examples:")

        for record, count in list(exact_duplicates.items())[:5]:
            print(f"\nAppears {count} times:")
            print(record)