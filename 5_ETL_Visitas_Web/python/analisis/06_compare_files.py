from pathlib import Path
import csv

project_folder = Path(__file__).resolve().parent.parent.parent
source_folder = project_folder / "data" / "seed"

files = sorted(source_folder.glob("*.txt"))

data = {}

for file in files:
    with open(file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    data[file.name] = rows


print("\n" + "=" * 60)
print("EMAIL OVERLAP BETWEEN FILES")
print("=" * 60)

email_sets = {}

for filename, rows in data.items():
    email_sets[filename] = {
        row["email"].strip().lower()
        for row in rows
    }

for i in range(len(files)):
    for j in range(i + 1, len(files)):

        file_a = files[i].name
        file_b = files[j].name

        overlap = email_sets[file_a] & email_sets[file_b]

        print(f"\n{file_a} vs {file_b}")
        print(f"Emails in both files: {len(overlap)}")

        if overlap:
            print("Examples:")

            for email in list(overlap)[:10]:
                print(f"  {email}")
                print("\n" + "=" * 60)
print("DETAILS OF SHARED EMAILS")
print("=" * 60)

file_a = "report_7.txt"
file_b = "report_8.txt"

emails_a = {
    row["email"].strip().lower(): row
    for row in data[file_a]
}

emails_b = {
    row["email"].strip().lower(): row
    for row in data[file_b]
}

shared_emails = set(emails_a) & set(emails_b)

for email in shared_emails:
    print("\n" + "-" * 60)
    print(f"EMAIL: {email}")

    print("\nreport_7:")
    print(emails_a[email])

    print("\nreport_8:")
    print(emails_b[email])