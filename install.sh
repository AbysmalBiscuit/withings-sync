#!/bin/bash

python3 setup.py bdist_wheel
sudo pip3 uninstall -y withings-sync
sudo pip3 install -U 'dist/withings_sync-3.3.1-py3-none-any.whl'
