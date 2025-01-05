#!/usr/bin/env python3
from withings_sync.sync import main

if __name__ == "__main__":
    main(["--garmin-username", "velykoivanenko.lev@gmail.com", "-fl", "-v", "--no-upload"])
