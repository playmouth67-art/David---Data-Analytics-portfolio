from pathlib import Path
import csv

# Localiza data/seed: source se purga en cada corrida
project_folder = Path(__file__).resolve().parent.parent.parent
source_folder = project_folder / "data" / "seed"

# Look for all TXT files
files = list(source_folder.glob("*.txt"))

print(f"Files found: {len(files)}")

for file in files:
    print("\n" + "=" * 50)
    print(f"FILE: {file.name}")
    print("=" * 50)

    with open(file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)

        rows = list(reader)

    header = rows[0]
    data = rows[1:]

    print(f"Number of columns: {len(header)}")
    print(f"Number of data rows: {len(data)}")
    print(f"Headers: {header}")

    print("\nColumn summary:")

    for column_index, column_name in enumerate(header):

        values = []

        for row in data:
            if column_index < len(row):
                values.append(row[column_index].strip())

        non_empty = [value for value in values if value != ""]

        print(
            f"{column_name}: "
            f"{len(non_empty)} non-empty / "
            f"{len(values)} total"
        )