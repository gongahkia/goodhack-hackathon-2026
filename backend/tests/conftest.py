import os

# disable the daily scheduler loop during tests to avoid mid-test fires near 22:00 patient-tz
os.environ.setdefault("SCHEDULER_ENABLED", "false")
