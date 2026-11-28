// La vue 3D rangée en amas par projet, dans un Chromium sans écran, réseau coupé : à l'ouverture, chaque projet a sa
// place et ses souvenirs autour (écart entre projets grand devant la taille d'un amas) ; ⊞ rend la disposition libre,
// et ce choix est gardé à la réouverture. Dit en JSON ce qu'il a vu.
// Lancé par tests/test_vue3d.py quand Playwright et Chromium sont là. Usage : node tests/vue3d_amas.js <cerveau.html>
const path = require("path");
const { pathToFileURL } = require("url");

// rapport « distance moyenne entre les centres des projets / distance moyenne d'un souvenir au centre de son projet »
const spread = () => {
  const groups = new Map();
  for (const n of cur.nodes) if (n.kind === "mem" && !late(n)){
    const k = projKey(n); if (!k) continue;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(n);
  }
  const centers = [], intra = [];
  for (const ns of groups.values()){
    if (ns.length < 2) continue;
    const c = { x: 0, y: 0, z: 0 };
    for (const n of ns){ c.x += n.x / ns.length; c.y += n.y / ns.length; c.z += (n.z || 0) / ns.length; }
    centers.push(c);
    for (const n of ns) intra.push(Math.hypot(n.x - c.x, n.y - c.y, (n.z || 0) - c.z));
  }
  const inter = [];
  for (let i = 0; i < centers.length; i++) for (let j = i + 1; j < centers.length; j++)
    inter.push(Math.hypot(centers[i].x - centers[j].x, centers[i].y - centers[j].y, centers[i].z - centers[j].z));
  const mean = a => a.reduce((s, v) => s + v, 0) / Math.max(1, a.length);
  return { projects: centers.length, ratio: Math.round(100 * mean(inter) / Math.max(1e-9, mean(intra))) / 100,
           clusters: st.clusters, pressed: document.querySelector("#grpBtn").getAttribute("aria-pressed") };
};

(async () => {
  let playwright;
  try { playwright = require("playwright"); } catch (e) { console.log(JSON.stringify({ skip: "playwright absent" })); return; }
  let browser;
  try {
    browser = await playwright.chromium.launch({ executablePath: process.env.CERVEAU_CHROMIUM || undefined,
      args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] });
  } catch (e) {
    console.log(JSON.stringify({ skip: "chromium absent : " + String(e.message || e).split("\n")[0] }));
    return;
  }
  const out = { errors: [] };
  try {
    const context = await browser.newContext({ offline: true, viewport: { width: 1200, height: 800 } });
    const page = await context.newPage();
    page.on("pageerror", e => out.errors.push("pageerror: " + (e.message || e)));
    page.on("console", m => { if (m.type() === "error") out.errors.push(m.text()); });
    const url = pathToFileURL(path.resolve(process.argv[2])).href;
    const settle = () => page.waitForTimeout(9500);  // à l'ouverture, la simulation s'arrête après 8 s (cooldownTime)
    const resettle = () => page.waitForTimeout(16500);  // après ⊞ ou G : 15 s de simulation (setClusters)
    await page.goto(url, { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("#boot").classList.contains("done"), null, { timeout: 30000 }).catch(() => {});
    await settle();
    out.opened = await page.evaluate(spread);           // à l'ouverture : amas par projet
    if (process.env.CERVEAU_CAPTURE) await page.screenshot({ path: path.join(process.env.CERVEAU_CAPTURE, "amas.png") });
    await page.click("#grpBtn");
    await resettle();
    out.free = await page.evaluate(spread);             // ⊞ : disposition libre
    if (process.env.CERVEAU_CAPTURE) await page.screenshot({ path: path.join(process.env.CERVEAU_CAPTURE, "libre.png") });
    await page.reload({ waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("#boot").classList.contains("done"), null, { timeout: 30000 }).catch(() => {});
    out.reopened = await page.evaluate(() => ({ clusters: st.clusters, pressed: document.querySelector("#grpBtn").getAttribute("aria-pressed") }));
    await page.keyboard.press("g");                     // G : les amas reviennent
    await resettle();
    out.back = await page.evaluate(spread);
  } catch (e) {
    out.errors.push("script : " + String(e.message || e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
})();
