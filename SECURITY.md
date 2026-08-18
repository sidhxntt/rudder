# Security policy

## Supported versions

Security fixes are applied to the actively maintained default branch and the
current CLI release line. Rudder is a controlled GKE beta, not a hosted
multi-tenant service.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability and do not include
credentials, private endpoints, or customer data in a report. Use GitHub's
[private security advisory form](https://github.com/sidhxntt/rudder/security/advisories/new)
for this repository.

Include a minimal reproduction, affected component and version/commit, impact,
and any mitigation you have identified. Maintainers will acknowledge the report
and coordinate remediation through the private advisory.

## Security boundaries

Rudder's control plane, GitHub integration, build path, registry, runtime
adapters, and cloud credentials are security-sensitive. Treat imported source,
Compose input, AI prompts, logs, and webhook content as untrusted data. See
the [GitHub Wiki](https://github.com/sidhxntt/rudder/wiki) for architecture and
operational boundaries.
