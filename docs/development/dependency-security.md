# Dependency security checks

The repository audits production dependencies without adding audit tooling to
the OpsFlow runtime or development dependency groups.

Run the Python production audit with:

```bash
make dependency-audit
```

This executes the equivalent of:

```bash
set -o pipefail
uv export --frozen --no-dev --no-emit-project --format requirements.txt \
  | uvx --from 'pip-audit==2.10.1' pip-audit \
      --requirement /dev/stdin --no-deps --disable-pip --strict
```

The export is derived from the committed `uv.lock`, excludes development-only
dependencies, and does not mutate the lockfile. A known vulnerability in a
Python production dependency fails the audit by default. An exception, if one
is ever required, must name the vulnerability ID, explain the technical
rationale, state the affected/not-affected analysis, and record human approval
in repository-visible policy before the audit is allowed to pass.

Run the frontend production-only audit with:

```bash
make frontend-audit
```

This uses `npm audit --omit=dev --audit-level=high`. The known transitive
`brace-expansion@5.0.9` advisory remains classified as development-only tooling
unless evidence shows production exposure; it is not resolved through an
unrelated dependency upgrade.

`make security-audit` runs both checks, and CI exposes the same checks in a
dedicated production dependency-security job.

## M10C boundary verification

The runtime SQL review found no user-controlled values interpolated into SQL
syntax. SQLAlchemy expressions bind client-derived values, while raw SQL uses
fixed statements or fixed internal interval fragments. No ORM or query-builder
rewrite is required.

The existing extraction and validation tests preserve the authority boundary:
AI output is interpreted as untrusted data, and deterministic software owns
validation, approval, retry, notification, and ERP/CRM side effects. No new
prompt filter or LLM safety component is introduced.

No M10C change is required for CORS, host, or security-header policy under the
current localhost/demo deployment contract.
