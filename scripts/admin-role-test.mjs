import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const appSource = await readFile(new URL("../public/app.js", import.meta.url), "utf8");

assert.match(appSource, /mineSub:'watch',session:null,isAdmin:false,adminRoleChecked:false/,
  "administrator state must fail closed before verification");
assert.match(appSource, /async function refreshCoreAdminRole\(\)[\s\S]*?\/rest\/v1\/rpc\/twss_is_admin[\s\S]*?===true/,
  "the CORE role must come from the protected administrator RPC");
assert.match(appSource, /await refreshCoreAdminRole\(\);await cloudPull\(\)/,
  "login must verify the role before rendering the signed-in account");
assert.match(appSource, /await refreshCoreAdminRole\(\);cloudPull\(\)/,
  "restored sessions must re-check administrator membership");
assert.match(appSource, /S\.isAdmin\?'<button id="openAdminConsole"[\s\S]*?location\.assign\('\/admin'\)/,
  "only a verified administrator may receive the standalone console link");
assert.doesNotMatch(appSource, /function refreshCoreAdminRole\(\)[\s\S]*?admin\.twss\.local[\s\S]*?const predictionKey/,
  "an email domain must never grant administrator access");

console.log("admin role regression checks passed");
