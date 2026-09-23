const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "../..");
const deploy = fs.readFileSync(path.join(root, "deploy/h3-backend/kaos-h3"), "utf8");

test("H3 deploy prepares a group-writable ledger backup directory", () => {
  assert.match(deploy, /install_ledger_backup_directory\(\)/);
  assert.match(
    deploy,
    /sudo install -d -m 0770 -o root -g "\$\{gid\}" "\$\{root\}\/backups\/kaosgdd\/ledger"/,
  );
  const familyUp = deploy.split("\n").find((line) => line.trim().startsWith("family-up)")) || "";
  assert.match(familyUp, /install_ledger_backup_directory/);
});
