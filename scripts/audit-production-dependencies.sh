#!/usr/bin/env bash

set -euo pipefail

# Audit only the frozen production dependency set. pip-audit is an ephemeral
# developer/CI tool and is never installed into the OpsFlow runtime.
uv export --frozen --no-dev --no-emit-project --format requirements.txt \
  | uvx --from 'pip-audit==2.10.1' pip-audit \
      --requirement /dev/stdin --no-deps --disable-pip --strict
