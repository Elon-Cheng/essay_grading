// Keep test execution independent of the caller's working directory.
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
for (const name of ['test_annotations.cjs', 'test_credit_payments.cjs', 'test_review_language.cjs', 'test_frontend_contract.cjs']) {
  const result = spawnSync(process.execPath, [path.join(__dirname, name)], {cwd: root, stdio: 'inherit'});
  if (result.status !== 0) process.exit(result.status || 1);
}
