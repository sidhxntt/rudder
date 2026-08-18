# Rudder CLI

`rudder` is the terminal client for the Rudder deployment control plane. It
uses the same authenticated API as the Rudder web console; it does not access
Docker, Kubernetes, Terraform, or the database directly.

## Install from GitHub Packages

GitHub Packages is a scoped npm registry. Authenticate with a GitHub personal
access token that can read packages, then map the `@sidhxntt` scope to GitHub:

```bash
npm login --scope=@sidhxntt --auth-type=legacy --registry=https://npm.pkg.github.com
npm install --global @sidhxntt/rudder
```

Run `rudder --help` after installation. The CLI requires Node.js 20 or newer.

## Local development

```bash
npm ci
npm test
npm run typecheck
npm run build
npm link
rudder
```

See the repository [CLI guide](https://github.com/sidhxntt/rudder/tree/main/cli)
and [Rudder Wiki](https://github.com/sidhxntt/rudder/wiki) for product and
operator documentation.
