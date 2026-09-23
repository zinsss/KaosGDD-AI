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
const { editText, highlightMarkdown, renderMarkdown } = require("../../apps/family-portal/markdown-editor.js");

test("Markdown source highlighting distinguishes headings and escapes HTML", () => {
  const html = highlightMarkdown("# Heading\n## Subheading\n- **item**\n<script>");
  assert.match(html, /class="mdHeading mdH1"/);
  assert.match(html, /class="mdHeading mdH2"/);
  assert.match(html, /class="mdListMarker"/);
  assert.match(html, /class="mdStrong"/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("Markdown editing indents and outdents selected lines", () => {
  const indented = editText("alpha\nbeta", 0, 10, "indent");
  assert.equal(indented.value, "  alpha\n  beta");
  assert.deepEqual(
    editText(indented.value, indented.start, indented.end, "outdent"),
    { value: "alpha\nbeta", start: 0, end: 10 },
  );
});

test("Markdown editing moves the current line without changing its selection", () => {
  assert.deepEqual(
    editText("one\ntwo\nthree", 4, 7, "up"),
    { value: "two\none\nthree", start: 0, end: 3 },
  );
  assert.deepEqual(
    editText("one\ntwo\nthree", 4, 7, "down"),
    { value: "one\nthree\ntwo", start: 10, end: 13 },
  );
});

test("memo Markdown renders semantic HTML without allowing raw HTML or unsafe links", () => {
  const html = renderMarkdown("# 제목\n\n- **항목**\n- [안전](https://example.com)\n\n<script>alert(1)</script>\n[위험](javascript:alert(1))");
  assert.match(html, /<h1>제목<\/h1>/);
  assert.match(html, /<ul><li><strong>항목<\/strong><\/li>/);
  assert.match(html, /href="https:\/\/example\.com"/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>|href="javascript:/);
});

test("memo Markdown renders copy tokens outside code as safe buttons", () => {
  const html = renderMarkdown("Use << account-123 >> or `<<not copied>>`.\n\n```\n<<also not copied>>\n```");
  assert.match(html, /class="memoCopyToken"/);
  assert.match(html, /data-memo-copy-token="account-123"/);
  assert.match(html, />account-123<\/button>/);
  assert.match(html, /<code>&lt;&lt;not copied&gt;&gt;<\/code>/);
  assert.match(html, /<pre><code>&lt;&lt;also not copied&gt;&gt;<\/code><\/pre>/);
  assert.equal((html.match(/class="memoCopyToken"/g) || []).length, 1);
});

test("Memos and Scribble share the lightweight editor", () => {
  assert.match(index, /src="\/markdown-editor\.js\?v=3"/);
  assert.ok(index.indexOf('src="/markdown-editor.js?v=3"') < index.indexOf('src="/app.js?v=377"'));
  assert.match(app, /KAOS_MARKDOWN_EDITOR\?\.enhanceAll\(view\)/);
  assert.match(app, /data-memo-content[\s\S]*data-markdown-editor/);
  assert.match(memosView, /data-memo-edit-start/);
  assert.match(memosView, /data-memo-edit-content data-markdown-editor/);
  assert.match(memosView, /class="memoMarkdown">\$\{deps\.renderMarkdown\(selected\.content\)\}<\/article>/);
  assert.match(scribbleView, /data-scribble-capture-text data-markdown-editor/);
  assert.match(scribbleView, /name="text" rows="10"[\s\S]*data-markdown-editor/);
  assert.match(styles, /--markdown-editor-red: var\(--nord11\);/);
  assert.match(styles, /\.markdownEditorHighlight \.mdH1 \{ color: var\(--markdown-editor-red\); \}/);
  assert.match(styles, /\.app\[data-profile="family"\] \.markdownEditor/);
  assert.match(styles, /\.markdownEditorToolbar/);
  assert.match(styles, /\.memoMarkdown \.memoCopyToken/);
  assert.match(styles, /\.archiveOcrRegion \.memoMarkdown \{[\s\S]*?font-size: 1\.12rem;/);
  assert.match(styles, /\.memoMarkdown h1 \{[\s\S]*?font-size: 1\.76rem;/);
  assert.match(app, /data-memo-copy-token/);
  assert.match(app, /writeTextToClipboard\(copyText\)/);
  assert.match(app, /navigator\.clipboard\?\.writeText[\s\S]*?catch \(_error\)[\s\S]*?document\.execCommand\("copy"\)/);
  assert.match(styles, /\.scribbleCapture \.markdownEditorInput \{[\s\S]*?min-height: 124px !important;/);
});

test("Memo edits use the scoped Memos PATCH endpoint", () => {
  assert.match(app, /async function updateMemoContent/);
  assert.match(app, /`\$\{detailUrl\}\?updateMask=content,attachments`/);
  assert.match(app, /method: "PATCH"/);
  assert.match(app, /JSON\.stringify\(\{ content: normalized, attachments: attachmentReferences \}\)/);
});

test("family portal deployment requires the shared editor asset", () => {
  assert.match(deployHelper, /require_file "\$\{app_source\}\/markdown-editor\.js"/);
  assert.match(deployHelper, /require_file "\$\{root\}\/data\/family-portal\/markdown-editor\.js"/);
});
