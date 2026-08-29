from pathlib import Path
import csv
from datetime import datetime


# Find the project folder
project_folder = Path(__file__).resolve().parent.parent.parent

# Find the source files
source_folder = project_folder / "data" / "seed"

# Expected date format in the source files
DATE_FORMAT = "%d/%m/%Y %H:%M"


def parse_date(value):
    """
    Convert a source date into a Python datetime.

    '-' and empty values are treated as missing.
    """
    value = value.strip()

    if value == "" or value == "-":
        return None

    try:
        return datetime.strptime(value, DATE_FORMAT)
    except ValueError:
        return None


files = sorted(source_folder.glob("*.txt"))

for file in files:

    print("\n" + "=" * 60)
    print(f"FILE: {file.name}")
    print("=" * 60)

    with open(file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    open_before_send = []
    click_before_send = []
    click_before_open = []

    invalid_dates = []

    for row_number, row in enumerate(rows, start=2):

        fecha_envio = parse_date(row["Fecha envio"])
        fecha_open = parse_date(row["Fecha open"])
        fecha_click = parse_date(row["Fecha click"])

        # Check whether a date value exists but cannot be parsed
        for column_name in ["Fecha envio", "Fecha open", "Fecha click"]:
            value = row[column_name].strip()

            if value not in ("", "-"):
                parsed_value = parse_date(value)

                if parsed_value is None:
                    invalid_dates.append(
                        (row_number, column_name, value)
                    )

        # Open happened before send
        if fecha_envio and fecha_open:
            if fecha_open < fecha_envio:
                open_before_send.append(
                    (row_number, row["email"], row["Fecha envio"], row["Fecha open"])
                )

        # Click happened before send
        if fecha_envio and fecha_click:
            if fecha_click < fecha_envio:
                click_before_send.append(
                    (row_number, row["email"], row["Fecha envio"], row["Fecha click"])
                )

        # Click happened before open
        if fecha_open and fecha_click:
            if fecha_click < fecha_open:
                click_before_open.append(
                    (row_number, row["email"], row["Fecha open"], row["Fecha click"])
                )

    # Print results
    print(f"Total rows: {len(rows)}")

    print(f"\nInvalid date values: {len(invalid_dates)}")

    if invalid_dates:
        print("Examples:")

        for item in invalid_dates[:10]:
            print(
                f"  Row {item[0]} | "
                f"{item[1]} = {item[2]}"
            )

    print(f"\nOpen before send: {len(open_before_send)}")

    if open_before_send:
        print("Examples:")

        for item in open_before_send[:10]:
            print(
                f"  Row {item[0]} | {item[1]} | "
                f"Send: {item[2]} | Open: {item[3]}"
            )

    print(f"\nClick before send: {len(click_before_send)}")

    if click_before_send:
        print("Examples:")

        for item in click_before_send[:10]:
            print(
                f"  Row {item[0]} | {item[1]} | "
                f"Send: {item[2]} | Click: {item[3]}"
            )

    print(f"\nClick before open: {len(click_before_open)}")

    if click_before_open:
        print("Examples:")

        for item in click_before_open[:10]:
            print(
                f"  Row {item[0]} | {item[1]} | "
                f"Open: {item[2]} | Click: {item[3]}"
            )