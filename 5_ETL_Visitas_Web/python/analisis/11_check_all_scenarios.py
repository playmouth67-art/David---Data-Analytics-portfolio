import csv
import os
from datetime import datetime
from collections import Counter


# ============================================================
# STEP 11
# CONTEXT-AWARE BEHAVIORAL SCENARIO ANALYSIS
# ============================================================
#
# PURPOSE:
#
# This script inventories the combinations of observed traits
# in each record.
#
# IMPORTANT:
#
# This is an exploratory analysis.
#
# It does NOT:
#   - modify records
#   - delete records
#   - deduplicate records
#   - declare records valid or invalid
#   - apply final business rules
#
# The purpose is to understand what combinations actually occur
# in the source data before deciding which combinations should
# be considered normal, suspicious, or inconsistent.
#
# ============================================================


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data", "seed")

FILES = [
    "report_7.txt",
    "report_8.txt",
    "report_9.txt",
]

DATE_FORMAT = "%d/%m/%Y %H:%M"


# ============================================================
# HELPERS
# ============================================================

def parse_date(value):
    """
    Convert a source date into a datetime.

    Returns None for:
        - empty values
        - '-'
        - invalid dates
    """

    if value is None:
        return None

    value = value.strip()

    if value == "" or value == "-":
        return None

    try:
        return datetime.strptime(value, DATE_FORMAT)

    except ValueError:
        return None


def parse_int(value):
    """
    Convert numeric source fields to integers.

    For scenario analysis:
        empty = 0
        '-'   = 0

    This is an analytical representation only.
    The original source values are never modified.
    """

    if value is None:
        return 0

    value = value.strip()

    if value == "" or value == "-":
        return 0

    try:
        return int(value)

    except ValueError:
        return 0


def is_populated(value):
    """
    Determine whether a source field contains meaningful data.

    Empty strings and '-' are treated as not populated.
    """

    if value is None:
        return False

    value = value.strip()

    return value != "" and value != "-"


def engagement_exists(row):
    """
    Determine whether measurable engagement exists.

    Engagement is defined here as:

        Opens > 0
        OR
        Clicks > 0

    This is an analytical definition, not a final business rule.
    """

    opens = parse_int(row["Opens"])
    clicks = parse_int(row["Clicks"])

    return opens > 0 or clicks > 0


def metadata_exists(row):
    """
    Determine whether technical interaction metadata exists.

    Metadata considered:

        IPs
        Navegadores
        Plataformas
    """

    return any(
        is_populated(row[field])
        for field in [
            "IPs",
            "Navegadores",
            "Plataformas",
        ]
    )


# ============================================================
# SCENARIO CLASSIFICATION
# ============================================================

def classify_record(row):
    """
    Generate descriptive scenario labels for one record.

    IMPORTANT:

    These labels describe what is present in the data.

    They are NOT judgments about whether the record is correct.
    """

    labels = []

    # --------------------------------------------------------
    # BASIC VALUES
    # --------------------------------------------------------

    opens = parse_int(row["Opens"])
    clicks = parse_int(row["Clicks"])

    opens_virales = parse_int(row["Opens virales"])
    clicks_virales = parse_int(row["Clicks virales"])

    fecha_envio = parse_date(row["Fecha envio"])
    fecha_open = parse_date(row["Fecha open"])
    fecha_click = parse_date(row["Fecha click"])

    # --------------------------------------------------------
    # FIELD PRESENCE
    # --------------------------------------------------------

    has_open_date = fecha_open is not None
    has_click_date = fecha_click is not None

    has_links = is_populated(row["Links"])

    has_ip = is_populated(row["IPs"])
    has_browser = is_populated(row["Navegadores"])
    has_platform = is_populated(row["Plataformas"])

    baja = row["Baja"].strip().upper() == "SI"

    badmail = is_populated(row["Badmail"])

    # ========================================================
    # OPEN SCENARIOS
    # ========================================================

    if opens == 0 and not has_open_date:
        labels.append("OPEN_NONE")

    if opens > 0 and has_open_date:
        labels.append("OPEN_COUNT_AND_DATE")

    if opens > 0 and not has_open_date:
        labels.append("OPEN_COUNT_WITHOUT_DATE")

    if opens == 0 and has_open_date:
        labels.append("OPEN_DATE_WITH_ZERO_COUNT")

    # ========================================================
    # CLICK SCENARIOS
    # ========================================================

    if clicks == 0 and not has_click_date:
        labels.append("CLICK_NONE")

    if clicks > 0 and has_click_date:
        labels.append("CLICK_COUNT_AND_DATE")

    if clicks > 0 and not has_click_date:
        labels.append("CLICK_COUNT_WITHOUT_DATE")

    if clicks == 0 and has_click_date:
        labels.append("CLICK_DATE_WITH_ZERO_COUNT")

    # ========================================================
    # CLICK / OPEN RELATIONSHIPS
    # ========================================================

    if clicks > 0 and opens == 0:
        labels.append("CLICK_WITHOUT_OPEN_COUNT")

    if clicks > 0 and opens > 0:
        labels.append("CLICK_WITH_OPEN_COUNT")

    if clicks == 0 and opens > 0:
        labels.append("OPEN_WITHOUT_CLICK")

    # ========================================================
    # LINK / CLICK RELATIONSHIPS
    # ========================================================

    if has_links and clicks > 0:
        labels.append("LINKS_WITH_CLICKS")

    if has_links and clicks == 0:
        labels.append("LINKS_WITHOUT_CLICKS")

    if not has_links and clicks > 0:
        labels.append("CLICK_WITHOUT_LINKS")

    # ========================================================
    # VIRAL METRIC RELATIONSHIPS
    # ========================================================

    if opens_virales > opens:
        labels.append("VIRAL_OPENS_GREATER_THAN_OPENS")

    if clicks_virales > clicks:
        labels.append("VIRAL_CLICKS_GREATER_THAN_CLICKS")

    # IMPORTANT:
    #
    # Equality is only recorded when the metric is > 0.
    #
    # Otherwise every record with 0 / 0 would be classified as
    # "equal", which would not provide useful information.
    #

    if opens_virales == opens and opens > 0:
        labels.append("VIRAL_OPENS_EQUAL_OPENS")

    if clicks_virales == clicks and clicks > 0:
        labels.append("VIRAL_CLICKS_EQUAL_CLICKS")

    if opens_virales < opens:
        labels.append("VIRAL_OPENS_LESS_THAN_OPENS")

    if clicks_virales < clicks:
        labels.append("VIRAL_CLICKS_LESS_THAN_CLICKS")

    # ========================================================
    # UNSUBSCRIBE / ENGAGEMENT
    # ========================================================

    if baja and not engagement_exists(row):
        labels.append("BAJA_WITHOUT_ENGAGEMENT")

    if baja and engagement_exists(row):
        labels.append("BAJA_WITH_ENGAGEMENT")

    if baja and clicks > 0:
        labels.append("BAJA_WITH_CLICK")

    if baja and opens > 0:
        labels.append("BAJA_WITH_OPEN")

    if not baja and engagement_exists(row):
        labels.append("NO_BAJA_WITH_ENGAGEMENT")

    # ========================================================
    # BADMAIL / ENGAGEMENT
    # ========================================================

    if badmail and not engagement_exists(row):
        labels.append("BADMAIL_WITHOUT_ENGAGEMENT")

    if badmail and engagement_exists(row):
        labels.append("BADMAIL_WITH_ENGAGEMENT")

    if not badmail and engagement_exists(row):
        labels.append("NO_BADMAIL_WITH_ENGAGEMENT")

    # ========================================================
    # TECHNICAL METADATA
    # ========================================================

    if metadata_exists(row):
        labels.append("METADATA_PRESENT")

    if not metadata_exists(row):
        labels.append("METADATA_ABSENT")

    if has_ip:
        labels.append("IP_PRESENT")

    if has_browser:
        labels.append("BROWSER_PRESENT")

    if has_platform:
        labels.append("PLATFORM_PRESENT")

    if not has_ip and not has_browser and not has_platform:
        labels.append("ALL_METADATA_ABSENT")

    # ========================================================
    # INDIVIDUAL METADATA COMBINATIONS
    # ========================================================

    if has_ip and has_browser and has_platform:
        labels.append("FULL_METADATA")

    if has_ip and not has_browser and not has_platform:
        labels.append("IP_ONLY")

    if not has_ip and has_browser and not has_platform:
        labels.append("BROWSER_ONLY")

    if not has_ip and not has_browser and has_platform:
        labels.append("PLATFORM_ONLY")

    if has_ip and has_browser and not has_platform:
        labels.append("IP_BROWSER_ONLY")

    if has_ip and not has_browser and has_platform:
        labels.append("IP_PLATFORM_ONLY")

    if not has_ip and has_browser and has_platform:
        labels.append("BROWSER_PLATFORM_ONLY")

    # ========================================================
    # TIMESTAMP RELATIONSHIPS
    # ========================================================

    # --------------------------------------------------------
    # OPEN vs SEND
    # --------------------------------------------------------

    if fecha_envio and fecha_open:

        if fecha_open < fecha_envio:
            labels.append("OPEN_BEFORE_SEND")

        elif fecha_open == fecha_envio:
            labels.append("OPEN_AT_SEND_TIME")

        else:
            labels.append("OPEN_AFTER_SEND")

    # --------------------------------------------------------
    # CLICK vs SEND
    # --------------------------------------------------------

    if fecha_envio and fecha_click:

        if fecha_click < fecha_envio:
            labels.append("CLICK_BEFORE_SEND")

        elif fecha_click == fecha_envio:
            labels.append("CLICK_AT_SEND_TIME")

        else:
            labels.append("CLICK_AFTER_SEND")

    # --------------------------------------------------------
    # CLICK vs OPEN
    # --------------------------------------------------------

    if fecha_open and fecha_click:

        if fecha_click < fecha_open:
            labels.append("CLICK_BEFORE_OPEN")

        elif fecha_click == fecha_open:
            labels.append("CLICK_AT_OPEN_TIME")

        else:
            labels.append("CLICK_AFTER_OPEN")

    # ========================================================
    # HIGH-LEVEL ENGAGEMENT STATES
    # ========================================================

    if opens == 0 and clicks > 0 and not has_open_date:
        labels.append("CLICK_WITHOUT_ANY_OPEN_SIGNAL")

    if opens > 0 and clicks > 0:
        labels.append("OPEN_AND_CLICK")

    if opens > 0 and clicks == 0:
        labels.append("OPEN_ONLY")

    if opens == 0 and clicks == 0:
        labels.append("NO_RECORDED_ENGAGEMENT")

    # ========================================================
    # HIGH-LEVEL RECORD STATES
    # ========================================================

    if opens == 0 and clicks == 0 and not has_open_date and not has_click_date:
        labels.append("COMPLETELY_INACTIVE")

    if opens > 0 and clicks > 0 and has_open_date and has_click_date:
        labels.append("COMPLETE_OPEN_CLICK_EVENT_DATA")

    if opens > 0 and clicks == 0 and has_open_date:
        labels.append("OPEN_EVENT_WITHOUT_CLICK")

    if clicks > 0 and has_click_date:
        labels.append("CLICK_EVENT_PRESENT")

    return labels


# ============================================================
# LOAD DATA
# ============================================================

def load_file(filename):

    path = os.path.join(DATA_DIR, filename)

    with open(
        path,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        return list(reader)


# ============================================================
# PRINT COUNTER
# ============================================================

def print_counter(title, counter):

    print("\n" + title)

    print("-" * len(title))

    if not counter:
        print("None")
        return

    for key, count in counter.most_common():

        print(f"{key}: {count}")


# ============================================================
# FILTER HELPERS
# ============================================================

def select_scenarios(counter, names):

    return Counter({
        key: counter.get(key, 0)
        for key in names
        if counter.get(key, 0) > 0
    })


# ============================================================
# ANALYZE ONE FILE
# ============================================================

def analyze_file(filename):

    rows = load_file(filename)

    scenario_counter = Counter()

    for row in rows:

        labels = classify_record(row)

        for label in labels:

            scenario_counter[label] += 1

    print("\n")
    print("=" * 70)
    print(f"FILE: {filename}")
    print("=" * 70)

    print(f"Rows analyzed: {len(rows)}")

    # ========================================================
    # OPEN STATES
    # ========================================================

    print_counter(
        "OPEN STATES",
        select_scenarios(
            scenario_counter,
            [
                "OPEN_NONE",
                "OPEN_COUNT_AND_DATE",
                "OPEN_COUNT_WITHOUT_DATE",
                "OPEN_DATE_WITH_ZERO_COUNT",
            ]
        )
    )

    # ========================================================
    # CLICK STATES
    # ========================================================

    print_counter(
        "CLICK STATES",
        select_scenarios(
            scenario_counter,
            [
                "CLICK_NONE",
                "CLICK_COUNT_AND_DATE",
                "CLICK_COUNT_WITHOUT_DATE",
                "CLICK_DATE_WITH_ZERO_COUNT",
            ]
        )
    )

    # ========================================================
    # CLICK / OPEN RELATIONSHIPS
    # ========================================================

    print_counter(
        "CLICK / OPEN RELATIONSHIPS",
        select_scenarios(
            scenario_counter,
            [
                "CLICK_WITHOUT_OPEN_COUNT",
                "CLICK_WITH_OPEN_COUNT",
                "OPEN_WITHOUT_CLICK",
                "CLICK_WITHOUT_ANY_OPEN_SIGNAL",
            ]
        )
    )

    # ========================================================
    # LINKS
    # ========================================================

    print_counter(
        "LINK / CLICK RELATIONSHIPS",
        select_scenarios(
            scenario_counter,
            [
                "LINKS_WITH_CLICKS",
                "LINKS_WITHOUT_CLICKS",
                "CLICK_WITHOUT_LINKS",
            ]
        )
    )

    # ========================================================
    # VIRAL METRICS
    # ========================================================

    print_counter(
        "VIRAL METRIC RELATIONSHIPS",
        select_scenarios(
            scenario_counter,
            [
                "VIRAL_OPENS_GREATER_THAN_OPENS",
                "VIRAL_OPENS_EQUAL_OPENS",
                "VIRAL_OPENS_LESS_THAN_OPENS",
                "VIRAL_CLICKS_GREATER_THAN_CLICKS",
                "VIRAL_CLICKS_EQUAL_CLICKS",
                "VIRAL_CLICKS_LESS_THAN_CLICKS",
            ]
        )
    )

    # ========================================================
    # UNSUBSCRIBE
    # ========================================================

    print_counter(
        "UNSUBSCRIBE / ENGAGEMENT",
        select_scenarios(
            scenario_counter,
            [
                "BAJA_WITHOUT_ENGAGEMENT",
                "BAJA_WITH_ENGAGEMENT",
                "BAJA_WITH_CLICK",
                "BAJA_WITH_OPEN",
                "NO_BAJA_WITH_ENGAGEMENT",
            ]
        )
    )

    # ========================================================
    # BADMAIL
    # ========================================================

    print_counter(
        "BADMAIL / ENGAGEMENT",
        select_scenarios(
            scenario_counter,
            [
                "BADMAIL_WITHOUT_ENGAGEMENT",
                "BADMAIL_WITH_ENGAGEMENT",
                "NO_BADMAIL_WITH_ENGAGEMENT",
            ]
        )
    )

    # ========================================================
    # METADATA
    # ========================================================

    print_counter(
        "METADATA PRESENCE",
        select_scenarios(
            scenario_counter,
            [
                "METADATA_PRESENT",
                "METADATA_ABSENT",
                "ALL_METADATA_ABSENT",
                "FULL_METADATA",
                "IP_ONLY",
                "BROWSER_ONLY",
                "PLATFORM_ONLY",
                "IP_BROWSER_ONLY",
                "IP_PLATFORM_ONLY",
                "BROWSER_PLATFORM_ONLY",
            ]
        )
    )

    # ========================================================
    # TIMESTAMP RELATIONSHIPS
    # ========================================================

    print_counter(
        "TIMESTAMP RELATIONSHIPS",
        select_scenarios(
            scenario_counter,
            [
                "OPEN_BEFORE_SEND",
                "OPEN_AT_SEND_TIME",
                "OPEN_AFTER_SEND",
                "CLICK_BEFORE_SEND",
                "CLICK_AT_SEND_TIME",
                "CLICK_AFTER_SEND",
                "CLICK_BEFORE_OPEN",
                "CLICK_AT_OPEN_TIME",
                "CLICK_AFTER_OPEN",
            ]
        )
    )

    # ========================================================
    # HIGH-LEVEL ENGAGEMENT
    # ========================================================

    print_counter(
        "HIGH-LEVEL ENGAGEMENT STATES",
        select_scenarios(
            scenario_counter,
            [
                "OPEN_AND_CLICK",
                "OPEN_ONLY",
                "NO_RECORDED_ENGAGEMENT",
                "CLICK_WITHOUT_ANY_OPEN_SIGNAL",
                "OPEN_EVENT_WITHOUT_CLICK",
                "CLICK_EVENT_PRESENT",
                "COMPLETELY_INACTIVE",
                "COMPLETE_OPEN_CLICK_EVENT_DATA",
            ]
        )
    )

    # ========================================================
    # ALL SCENARIOS
    # ========================================================

    print_counter(
        "ALL SCENARIOS",
        scenario_counter
    )

    return scenario_counter


# ============================================================
# CROSS-FILE COMPARISON
# ============================================================

def compare_scenarios(all_results):

    print("\n")
    print("=" * 70)
    print("CROSS-FILE SCENARIO COMPARISON")
    print("=" * 70)

    all_scenarios = set()

    for counter in all_results.values():

        all_scenarios.update(counter.keys())

    for scenario in sorted(all_scenarios):

        print("\n" + scenario)

        for filename in FILES:

            count = all_results[filename].get(
                scenario,
                0
            )

            print(
                f"  {filename}: {count}"
            )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    all_results = {}

    for filename in FILES:

        try:

            counter = analyze_file(filename)

            all_results[filename] = counter

        except FileNotFoundError:

            print(
                f"\nERROR: File not found: {filename}"
            )

        except Exception as e:

            print(
                f"\nERROR processing {filename}: {e}"
            )

    # ========================================================
    # CROSS-FILE ANALYSIS
    # ========================================================

    if all_results:

        compare_scenarios(all_results)

    # ========================================================
    # COMPLETION MESSAGE
    # ========================================================

    print("\n")
    print("=" * 70)
    print("SCENARIO ANALYSIS COMPLETE")
    print("=" * 70)

    print("No records were modified.")
    print("No records were deleted.")
    print("No records were deduplicated.")
    print("No business-rule decisions were applied.")
    print("Scenario labels are descriptive observations only.")

    print("=" * 70)