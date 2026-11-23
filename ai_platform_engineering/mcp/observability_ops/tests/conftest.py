# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

import os
import sys

# Flat module layout (server.py / tools/ at the project root, no installed
# package) - add the project root to sys.path so `tools.*` imports resolve
# the same way they do when the server itself runs.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
