#!/usr/bin/env bash
set -euo pipefail

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not found." >&2
  exit 1
fi

if ! command -v bash >/dev/null 2>&1; then
  echo "bash is required but not found." >&2
  exit 1
fi

echo "Installing Grok CLI..."
curl -fsSL https://x.ai/cli/install.sh | bash

echo "Verifying Grok CLI..."
"$HOME/.grok/bin/grok" --version
"$HOME/.grok/bin/agent" --version

echo "Done."
