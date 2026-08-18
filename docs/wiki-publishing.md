# Publishing the Rudder documentation to GitHub Wiki

The Markdown files in this repository are the documentation **source of
truth**. Do not move day-to-day authoring into GitHub Wiki: a Wiki is a second
Git repository, so editing it directly would let documentation drift away from
the code review that changed the product.

Instead, render the source files into the Wiki repository whenever the
documentation changes. The renderer creates GitHub Wiki's required `Home.md`,
flattens page names that cannot contain path separators, rewrites internal
links to Wiki page links, and writes `_Sidebar.md` and `_Footer.md` for
persistent navigation.

## One-time setup

1. Enable **Wiki** in the GitHub repository settings.
2. Create one initial Wiki page through GitHub's UI if the Wiki has never been
   initialized. GitHub then creates its separate `REPOSITORY.wiki.git`
   repository.
3. Clone that Wiki repository beside this project:

   ```bash
   git clone https://github.com/OWNER/REPOSITORY.wiki.git ../rudder.wiki
   ```

Replace `OWNER/REPOSITORY` with the actual GitHub repository path.

## Render and publish

From this repository root:

```bash
node scripts/render-github-wiki.mjs ../rudder.wiki

cd ../rudder.wiki
git status
git add Home.md Overview.md Architecture.md Features.md Technology-Stack.md \
  Configuration.md GKE-Operations.md Phase-4-Evidence.md Multi-Cloud.md \
  Conclusion.md Phase-*.md _Sidebar.md _Footer.md
git commit -m "docs: publish Rudder Wiki"
git push
```

The renderer writes only Rudder's managed Wiki pages. It does not delete other
files in the cloned Wiki repository, so remove obsolete manually-authored Wiki
pages deliberately rather than through an unsafe bulk-delete step.

## Page map

| Repository source | GitHub Wiki page |
|---|---|
| `docs/index.md` | `Home` |
| `docs/overview.md` | `Overview` |
| `docs/architecture.md` | `Architecture` |
| `docs/features.md` | `Features` |
| `docs/tech-stack.md` | `Technology-Stack` |
| `docs/configuration.md` | `Configuration` |
| `docs/gke-operations.md` | `GKE-Operations` |
| `docs/evidence/phase-4-controlled-beta.md` | `Phase-4-Evidence` |
| `docs/multi-cloud.md` | `Multi-Cloud` |
| `docs/conclusion.md` | `Conclusion` |
| `docs/phases/phase-0.md` … `phase-9.md` | `Phase-0` … `Phase-9` |

## Maintenance rules

- Edit the source Markdown under `docs/`, then rerender the Wiki.
- Keep status language honest: distinguish implemented code, verification
  evidence, and future/planned architecture.
- Run the repository documentation-link check and render to a temporary folder
  before publishing. Inspect the generated `Home.md` and `_Sidebar.md` in the
  Wiki clone before committing.
- Keep sensitive values, live credentials, private addresses, and raw incident
  logs out of both the repository and the Wiki.
