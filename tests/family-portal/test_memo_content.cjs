const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "../..");
const app = fs.readFileSync(path.join(root, "apps/family-portal/app.js"), "utf8");
const index = fs.readFileSync(path.join(root, "apps/family-portal/index.html"), "utf8");
const memosView = fs.readFileSync(path.join(root, "apps/family-portal/memos-view.js"), "utf8");
const scribbleView = fs.readFileSync(path.join(root, "apps/family-portal/scribble-view.js"), "utf8");
const styles = fs.readFileSync(path.join(root, "apps/family-portal/styles.css"), "utf8");
const deployHelper = fs.readFileSync(path.join(root, "deploy/h3-backend/kaos-h3"), "utf8");
const { render } = require("../../apps/family-portal/memo-content.js");

test("memo content formatting remains safe without an enhanced editor", () => {
  const html = render("# 제목\n\n- **항목**\n- [안전](https://example.com)\n\n<script>alert(1)</script>\n[위험](javascript:alert(1))");
  assert.match(html, /<h1>제목<\/h1>/);
  assert.match(html, /<ul><li><strong>항목<\/strong><\/li>/);
  assert.match(html, /href="https:\/\/example\.com"/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>|href="javascript:/);
});

test("memo copy tokens remain available outside code", () => {
  const html = render("Use << account-123 >> or `<<not copied>>`.\n\n```\n<<also not copied>>\n```");
  assert.match(html, /class="memoCopyToken"/);
  assert.match(html, /data-memo-copy-token="account-123"/);
  assert.match(html, />account-123<\/button>/);
  assert.match(html, /<code>&lt;&lt;not copied&gt;&gt;<\/code>/);
  assert.match(html, /<pre><code>&lt;&lt;also not copied&gt;&gt;<\/code><\/pre>/);
  assert.equal((html.match(/class="memoCopyToken"/g) || []).length, 1);
});

test("Memos and Scribble use ordinary textareas with no enhanced editor", () => {
  assert.match(index, /src="\/memo-content\.js\?v=1"/);
  assert.ok(index.indexOf('src="/memo-content.js?v=1"') < index.indexOf('src="/app.js?v=407"'));
  assert.doesNotMatch(index, /markdown-editor\.js/);
  assert.equal(fs.existsSync(path.join(root, "apps/family-portal/markdown-editor.js")), false);
  assert.doesNotMatch(app, /KAOS_MARKDOWN_EDITOR|enhanceAll\(view\)|data-markdown-editor/);
  assert.doesNotMatch(memosView, /data-markdown-editor/);
  assert.doesNotMatch(scribbleView, /data-markdown-editor/);
  assert.match(app, /renderMemoContent: window\.KAOS_MEMO_CONTENT\.render/);
  assert.match(memosView, /class="memoContent">\$\{deps\.renderMemoContent\(selected\.content\)\}<\/article>/);
  assert.doesNotMatch(styles, /\.markdownEditor|--markdown-editor/);
  assert.match(styles, /\.memoEditForm textarea \{[\s\S]*?font: inherit;/);
  assert.match(styles, /\.scribbleCapture textarea,[\s\S]*?font-family: inherit !important;/);
  assert.match(styles, /\.scribbleCapture textarea \{[\s\S]*?min-height: 124px;/);
  assert.match(styles, /\.scribbleEditor textarea \{[\s\S]*?min-height: min\(44dvh, 360px\);/);
});

test("memo updates still use the scoped Memos PATCH endpoint", () => {
  assert.match(app, /async function updateMemoContent/);
  assert.match(app, /`\$\{detailUrl\}\?updateMask=content,attachments`/);
  assert.match(app, /method: "PATCH"/);
  assert.match(app, /JSON\.stringify\(\{ content: normalized, attachments: attachmentReferences \}\)/);
});

test("family portal deployment requires the memo content asset and no editor asset", () => {
  assert.match(deployHelper, /require_file "\$\{app_source\}\/memo-content\.js"/);
  assert.match(deployHelper, /require_file "\$\{root\}\/data\/family-portal\/memo-content\.js"/);
  assert.doesNotMatch(deployHelper, /markdown-editor\.js/);
});
