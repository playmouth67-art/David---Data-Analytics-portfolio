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

    emails = [row["email"].strip().lower() for row in rows]

    counts = Counter(emails)

    duplicate_emails = {
        email: count
        for email, count in counts.items()
        if count > 1
    }

    print(f"Total rows: {len(rows)}")
    print(f"Unique emails: {len(counts)}")
    print(f"Emails appearing more than once: {len(duplicate_emails)}")

    if duplicate_emails:
        print("\nExample duplicate emails:")

        for email, count in list(duplicate_emails.items())[:10]:
            print(f"  {email}: {count} records")
        print("\nDuplicate record details:")

        for email in duplicate_emails:
            print(f"\nEmail: {email}")

            for row in rows:
                if row["email"].strip().lower() == email:
                    print(row)
