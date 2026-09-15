#!/usr/bin/env bash
# ==============================================================================
# sync_data.sh — 1-Click Data Synchronization Runner for Linux / macOS
# ==============================================================================
# Usage:
#   ./scripts/sync_data.sh            # Run full synchronization
#   ./scripts/sync_data.sh --dry-run  # Dry-run validation only
#   ./scripts/sync_data.sh --doc 168_2024_ND-CP # Sync specific document
# ==============================================================================

set -e

python3 -m src.sync "$@"
