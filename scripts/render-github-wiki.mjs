#!/usr/bin/env node

/**
 * Render the repository documentation as GitHub Wiki pages.
 *
 * Source files remain in docs/. GitHub Wiki page titles come from filenames,
 * so phase pages are flattened here instead of asking authors to maintain a
 * second, hand-edited copy of every document.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, dirname, posix } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = resolve(repositoryRoot, "docs");
const outputRoot = process.argv[2] ? resolve(process.argv[2]) : undefined;
const repositoryUrl = "https://github.com/sidhxntt/rudder";

if (!outputRoot) {
  console.error("Usage: node scripts/render-github-wiki.mjs <wiki-directory>");
  process.exit(2);
}

const pages = [
  ["index.md", "Home.md"],
  ["overview.md", "Overview.md"],
  ["architecture.md", "Architecture.md"],
  ["features.md", "Features.md"],
  ["tech-stack.md", "Technology-Stack.md"],
  ["configuration.md", "Configuration.md"],
  ["gke-operations.md", "GKE-Operations.md"],
  ["evidence/phase-4-controlled-beta.md", "Phase-4-Evidence.md"],
  ["multi-cloud.md", "Multi-Cloud.md"],
  ["conclusion.md", "Conclusion.md"],
  ["wiki-publishing.md", "Wiki-Publishing.md"],
  ...Array.from({ length: 10 }, (_, phase) => [
    `phases/phase-${phase}.md`,
    `Phase-${phase}.md`,
  ]),
  ["_Sidebar.md", "_Sidebar.md"],
  ["_Footer.md", "_Footer.md"],
];

const pageNames = new Map(
  pages.map(([source, destination]) => [source.replaceAll("\\", "/"), destination.replace(/\.md$/, "")]),
);

function rewriteLinks(markdown, source) {
  return markdown.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (full, text, href) => {
    if (/^(?:https?:|mailto:|#)/i.test(href)) return full;

    const [path, anchor = ""] = href.split("#", 2);
    const sourceRelativePath = posix.normalize(posix.join(posix.dirname(source), path));
    const target = pageNames.get(sourceRelativePath);
    if (!target) {
      const repositoryRelativePath = posix.normalize(
        posix.join("docs", posix.dirname(source), path),
      );
      if (repositoryRelativePath.startsWith("../")) return full;
      const suffix = anchor ? `#${anchor}` : "";
      return `[${text}](${repositoryUrl}/blob/main/${repositoryRelativePath}${suffix})`;
    }

    // GitHub Wiki supports MediaWiki page links. Keep anchor links as normal
    // Markdown, because they address a heading within the rendered page.
    return anchor ? `[${text}](${target}#${anchor})` : `[[${target}|${text}]]`;
  });
}

await mkdir(outputRoot, { recursive: true });
for (const [source, destination] of pages) {
  const contents = await readFile(resolve(sourceRoot, source), "utf8");
  const rendered = source === "index.md"
    ? rewriteLinks(contents.replace(/^# Rudder documentation$/m, "# Rudder"), source)
    : rewriteLinks(contents, source);
  await writeFile(resolve(outputRoot, destination), rendered);
}

console.log(`Rendered ${pages.length} GitHub Wiki pages into ${outputRoot}`);
