import csv
import os
from collections import Counter

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "seed"
)

FILES = [
    "report_7.txt",
    "report_8.txt",
    "report_9.txt"
]


def profile_file(filename):
    path = os.path.join(DATA_DIR, filename)

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print("\n" + "=" * 60)
    print(f"FILE: {filename}")
    print("=" * 60)

    print(f"Rows: {len(rows)}")
    print()

    for column in reader.fieldnames:

        empty = 0
        dash = 0
        populated = 0

        values = Counter()

        for row in rows:
            value = row[column].strip()

            if value == "":
                empty += 1
            elif value == "-":
                dash += 1
            else:
                populated += 1
                values[value] += 1

        print(f"{column}")
        print(f"  Empty values: {empty}")
        print(f"  Dash '-' values: {dash}")
        print(f"  Populated values: {populated}")

        if values:
            print(f"  Distinct populated values: {len(values)}")

        print()


for filename in FILES:
    profile_file(filename)