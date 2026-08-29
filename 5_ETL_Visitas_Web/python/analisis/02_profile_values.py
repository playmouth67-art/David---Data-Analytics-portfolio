from pathlib import Path
import csv

# Localiza data/seed: source se purga en cada corrida
project_folder = Path(__file__).resolve().parent.parent.parent
source_folder = project_folder / "data" / "seed"

# Find all source files
files = list(source_folder.glob("*.txt"))

print(f"Files found: {len(files)}")

for file in files:
    print("\n" + "=" * 60)
    print(f"FILE: {file.name}")
    print("=" * 60)

    with open(file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header = rows[0]
    data = rows[1:]

    print(f"Rows: {len(data)}")
    print(f"Columns: {len(header)}")

    print("\nColumn details:")

    for column_index, column_name in enumerate(header):

        values = []

        for row in data:
            if column_index < len(row):
                values.append(row[column_index].strip())

        non_empty = [value for value in values if value != ""]

        unique_values = list(dict.fromkeys(non_empty))

        print(f"\n{column_name}")
        print(f"  Non-empty: {len(non_empty)} / {len(values)}")
        print(f"  Sample values: {unique_values[:5]}")