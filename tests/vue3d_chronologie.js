// La chronologie de cerveau.html (étape 13 du plan), dans un Chromium sans écran, réseau coupé : à une date passée, un
// souvenir remplacé depuis est visible et son remplaçant absent ; curseur à droite, la page montre exactement le présent
// (les souvenirs et les liens de DATA.nodes et DATA.edges, rien du passé). Dit en JSON ce qu'il a vu.
// Lancé par tests/test_vue3d.py quand Playwright et Chromium sont là. Usage : node tests/vue3d_chronologie.js <cerveau.html>
const path = require("path");
const { pathToFileURL } = require("url");

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
    await page.goto(pathToFileURL(path.resolve(process.argv[2])).href, { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("#boot").classList.contains("done"), null, { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(800);
    Object.assign(out, await page.evaluate(() => {
      const r = {};
      const shown = () => new Set(cur.nodes.filter(n => n.kind === "mem" && !hidden(n)).map(n => n.id));
      const shownLinks = () => cur.links.filter(l => !l.inf && !l.con && linkVis(l));
      // aujourd'hui (curseur à droite) : le présent, rien de plus
      setUntil(st.dates.length - 1);
      const now = shown(), present = new Set(DATA.nodes.map(n => n.id));
      r.todayExtra = [...now].filter(id => !present.has(id));
      r.todayMissing = [...present].filter(id => !now.has(id));
      r.todayPastLinks = shownLinks().filter(l => l.past).length;
      r.todayLinks = shownLinks().length;
      r.presentLinks = DATA.edges.filter(e => present.has(e.s) && present.has(e.t)).length;
      r.past = (DATA.past || []).length;
      // une date où l'ancien est vrai et son remplaçant pas encore
      for (const o of cur.nodes.filter(n => n.old && n.sb)){
        const nu = cur.byId.get(o.sb);
        if (!nu) continue;
        const i = st.dates.findIndex(d => d >= startOf(o) && d <= endOf(o) && d < startOf(nu));
        if (i < 0) continue;
        setUntil(i);
        const s = shown();
        r.pastCase = { date: st.dates[i], old: o.id, oldShown: s.has(o.id), replacement: nu.id, replacementShown: s.has(nu.id) };
        break;
      }
      // un lien terminé : visible avant sa fin, plus après
      const e = cur.links.find(l => l.e && l.c && l.c < l.e);
      if (e){
        const before = st.dates.findIndex(d => d >= e.c && d < e.e), after = st.dates.findIndex(d => d >= e.e);
        if (before >= 0 && after >= 0){
          setUntil(before); const a = linkAlive(e);
          setUntil(after); const b = linkAlive(e);
          r.endedLink = { aliveBefore: a, aliveAfter: b };
        }
      }
      setUntil(st.dates.length - 1);
      r.layers = !!document.querySelector("#layBtn") && [...document.querySelectorAll("#color option")].map(o => o.value);
      return r;
    }));
    // couches, couleurs et lecture ▶ : ni erreur, ni nœud égaré
    await page.click("#layBtn");
    await page.waitForTimeout(300);
    out.layered = await page.evaluate(() => cur.nodes.filter(n => n.kind === "mem").every(n => n.fy === LEVEL_Y[levelOf(n)]));
    await page.click("#layBtn");
    out.unlayered = await page.evaluate(() => cur.nodes.every(n => n.fy == null));
    for (const c of ["dom", "heat", "comm"]){
      await page.selectOption("#color", c);
      await page.waitForTimeout(150);
    }
    out.legendDom = await page.evaluate(() => { const s = st.color; st.color = "dom"; const k = legendKey(cur.byId.get("ovh") || cur.nodes[0]); st.color = s; return k; });
    await page.click("#playBtn");
    await page.waitForTimeout(2600);
    // l'arrêter s'il joue encore : un second clic sur une lecture déjà finie la relancerait (machine chargée)
    if (await page.evaluate(() => $("#playBtn").textContent === "⏸")) await page.click("#playBtn");
    await page.waitForFunction(() => $("#playBtn").textContent === "▶", null, { timeout: 10000 }).catch(() => {});
    out.afterPlay = await page.evaluate(() => ({ until: st.until, dying: cur.nodes.filter(n => n.__dying).length }));
    // retour en avant juste après une extinction : les souvenirs revenus sont rallumés tout de suite (pas après un minuteur)
    out.revived = await page.evaluate(() => { setUntil(0); setUntil(st.dates.length - 1);
      return cur.nodes.filter(n => n.__dying && !late(n)).length; });
    await page.evaluate(() => setUntil(st.dates.length - 1));
    await page.waitForFunction(() => !cur.nodes.some(n => n.__dying), null, { timeout: 5000 }).catch(() => {});
    out.settled = await page.evaluate(() => cur.nodes.filter(n => n.__dying).length);
  } catch (e) {
    out.errors.push("script : " + String(e.message || e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
})();
