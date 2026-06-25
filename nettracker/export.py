"""CSV / JSON writers for usage data."""

import csv
import json


def write_csv(path, headers, rows):
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)


def write_json(path, records):
    with open(path, "w") as fh:
        json.dump(records, fh, indent=2)
