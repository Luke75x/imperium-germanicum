// Erzeugt amt_icons.py aus lucide-react (ISC-Lizenz): node werkzeuge/lucide_icons.js <icons-Verzeichnis> > amt_icons.py
const fs = require("fs"), dir = process.argv[2];
const namen = ["landmark","layout-dashboard","folder-open","users","file-text","search","log-out","house","stamp","clock","user","pencil",
  "check","x","notebook-pen","arrow-left","external-link","hourglass","scroll-text","folder","file-check","file-x","file-clock","archive","inbox","book-user","user-check","shield-check","circle-alert","chevron-right","download","trash-2","chart-column","lock","lock-open","triangle-alert","file-down"];
const out = {};
for (const n of namen) {
  const t = fs.readFileSync(`${dir}/${n}.js`, "utf8");
  const m = t.match(/createLucideIcon\("[^"]+",\s*(\[[\s\S]*?\])\);/);
  const arr = eval(m[1]);
  out[n] = arr.map(([tag, a]) => { delete a.key; return `<${tag} ` + Object.entries(a).map(([k, v]) => `${k}="${v}"`).join(" ") + "/>"; }).join("");
}
console.log('"""Lucide-Icons (ISC-Lizenz, lucide.dev), erzeugt von werkzeuge/lucide_icons.js. Innenleben der SVGs, 24×24, Strich."""');
console.log("ICONS = " + JSON.stringify(out, null, 1) + "\n");
