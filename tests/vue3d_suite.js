// La vue 3D, suite (étape 17 du plan), dans un Chromium sans écran, réseau coupé : flèches sur les liens typés et pas
// sur « lié à », étiquette d'un lien au survol (type et dates), nœud posé à la main qui reste où on le lâche (puis
// libéré, couches comprises), orbite de la caméra (et coupée si le système demande moins d'animations), boucle
// d'animation en pause quand l'onglet est caché. Les vérifications passent par les fonctions que la page donne à
// 3d-force-graph (G.onNodeDragEnd(), G.linkLabel()…), les mêmes que la souris déclenche. Dit en JSON ce qu'il a vu.
// Lancé par tests/test_vue3d.py quand Playwright et Chromium sont là. Usage : node tests/vue3d_suite.js <cerveau.html>
const path = require("path");
const { pathToFileURL } = require("url");

async function open(browser, file, options, out){
  const context = await browser.newContext(Object.assign({ offline: true, viewport: { width: 1200, height: 800 } }, options));
  const page = await context.newPage();
  page.on("pageerror", e => out.errors.push("pageerror: " + (e.message || e)));
  page.on("console", m => { if (m.type() === "error") out.errors.push(m.text()); });
  await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("#boot").classList.contains("done"), null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(800);
  return page;
}

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
  const file = path.resolve(process.argv[2]);
  try {
    const page = await open(browser, file, {}, out);
    // 1. flèches et étiquette des liens
    Object.assign(out, await page.evaluate(() => {
      const r = {};
      const find = (s, t, rel) => cur.links.find(l => idOf(l.source) === s && idOf(l.target) === t && l.rel === rel);
      const uses = find("scw", "serveur", "uses"), rel = find("facture", "serveur", "relates");
      const len = G.linkDirectionalArrowLength(), color = G.linkDirectionalArrowColor();
      const inf = cur.links.find(l => l.inf), con = cur.links.find(l => l.con);
      r.arrows = { typed: uses ? len(uses) : null, relates: rel ? len(rel) : null, inf: inf ? len(inf) : 0, con: con ? len(con) : 0,
                   relPos: G.linkDirectionalArrowRelPos(), color: uses ? String(color(uses)) : "",
                   typedObj: !!(uses && uses.__arrowObj), relatesObj: !!(rel && rel.__arrowObj) };
      const text = html => { const d = document.createElement("div"); d.innerHTML = html; return d.textContent; };
      const label = G.linkLabel();
      const ended = cur.links.find(l => l.e && l.c && idOf(l.source) === "scw" && idOf(l.target) === "facture");
      r.tipEnded = ended ? text(label(ended)) : null;
      r.tipTyped = uses ? text(label(uses)) : null;
      r.created = uses ? uses.c : null;
      // survol réel d'un lien : il s'allume, sa flèche grandit
      const hover = G.onLinkHover();
      hover(uses);
      r.hover = { on: st.linkHover === uses && hot(uses), bigger: len(uses) > r.arrows.typed };
      hover(null);
      r.hover.off = st.linkHover === null && !hot(uses);
      return r;
    }));
    // 2. un vrai glisser à la souris (caméra devant le nœud) : le nœud reste posé, et aucune erreur (la 1.80.0 de
    // 3d-force-graph en levait une à chaque fin de glisser, que la page arrête comme la 1.80.2)
    // disposition figée et pas de rotation au repos (elle part après 12 s sans clic) : rien ne bouge sous la souris
    await page.evaluate(() => { G.cooldownTime(0); lastInput = Infinity; FX.idleSpin = false; applySpin(); });
    await page.waitForTimeout(300);
    await page.evaluate(() => { flyTo(cur.byId.get("facture"), 0); st.userMoved = true; });
    await page.waitForTimeout(600);
    const where = () => page.evaluate(() => { const n = cur.byId.get("facture"); return G.graph2ScreenCoords(n.x, n.y, n.z); });
    let at = await where();
    const before = out.errors.length;
    await page.mouse.move(at.x, at.y, { steps: 4 });
    // machine chargée : le survol n'est vu qu'à une image suivante, et la caméra a pu finir de bouger ; on vise à nouveau
    for (let i = 0; i < 16 && !(await page.evaluate(() => !!st.hover)); i++){
      await page.waitForTimeout(500);
      at = await where();
      await page.mouse.move(at.x + (i % 2), at.y, { steps: 1 });
    }
    // le nœud sous la souris (« facture », ou un autre devant lui selon la disposition) est celui qu'on glisse
    const grabbed = await page.evaluate(() => st.hover ? st.hover.id : null);
    await page.mouse.down();
    await page.mouse.move(at.x + 50, at.y + 30, { steps: 10 });
    await page.mouse.move(at.x + 90, at.y + 60, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(500);
    out.realDrag = await page.evaluate(id => { const n = cur.byId.get(id);
      return { grabbed: id, pinned: !!n && !!n.__pin && n.fx === n.__pin.x && n.fz === n.__pin.z, controls: G.controls().enabled,
               others: cur.nodes.filter(x => x.__pin && x !== n).map(x => x.id), released: unpinAll() }; }, grabbed);
    out.realDrag.errors = out.errors.length - before;
    // un vrai survol de lien, entre deux nœuds : l'étiquette de 3d-force-graph montre son type (les halos ne le cachent pas)
    // ses deux nœuds à la longueur d'un lien typé (60, forces()) : la disposition en amas les rapproche plus ou moins
    // selon le temps qu'a eu la simulation (machine chargée), et deux halos collés couvrent alors tout le lien
    await page.evaluate(() => { const l = cur.links.find(x => x.rel === "uses"), s = l.source, t = l.target;
      const m = {x: (s.x + t.x) / 2, y: (s.y + t.y) / 2, z: (s.z + t.z) / 2};
      Object.assign(s, {fx: m.x - 30, fy: m.y, fz: m.z}); Object.assign(t, {fx: m.x + 30, fy: m.y, fz: m.z});
      G.cooldownTime(1500); G.d3ReheatSimulation();
      G.cameraPosition({x: m.x, y: m.y + 30, z: m.z + 200}, m, 0); });
    await page.waitForFunction(() => { const l = cur.links.find(x => x.rel === "uses");
      return Math.abs(l.source.x - l.target.x - (l.source.fx - l.target.fx)) < 1; }, null, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1700);  // la simulation s'arrête (cooldown) : plus rien ne bouge sous la souris
    out.realHover = [];
    for (const k of [0.35, 0.5, 0.65]){
      const q = await page.evaluate(k => { const l = cur.links.find(x => x.rel === "uses"), s = l.source, t = l.target;
        return G.graph2ScreenCoords(s.x + (t.x - s.x) * k, s.y + (t.y - s.y) * k, s.z + (t.z - s.z) * k); }, k);
      await page.mouse.move(q.x, q.y, { steps: 3 });
      await page.waitForTimeout(500);
      out.realHover.push(await page.evaluate(() => st.linkHover
        ? st.linkHover.rel + " | " + [...document.querySelectorAll(".scene-tip")].map(e => e.textContent).join(" ")
        : "rien (nœud survolé : " + (st.hover ? st.hover.id : "aucun") + ")"));
    }
    await page.mouse.move(5, 790);
    await page.evaluate(() => { const l = cur.links.find(x => x.rel === "uses");
      for (const n of [l.source, l.target]) { delete n.fx; delete n.fy; delete n.fz; }
      G.cooldownTime(8000); lastInput = performance.now(); });
    // 3. un nœud lâché reste où on le pose ; libéré par le bouton, puis par un double-clic sur le fond
    out.drag = await page.evaluate(() => {
      const n = cur.byId.get("serveur");
      n.x = 123; n.y = 45; n.z = -67;
      G.onNodeDragEnd()(n, { x: 0, y: 0, z: 0 });
      return { fx: n.fx, fy: n.fy, fz: n.fz, button: !$("#pinBtn").disabled };
    });
    await page.waitForTimeout(700);
    out.drag.stayed = await page.evaluate(() => { const n = cur.byId.get("serveur"); return [n.x, n.y, n.z].map(Math.round).join(","); });
    await page.click("#layBtn");
    out.drag.layered = await page.evaluate(() => { const n = cur.byId.get("serveur"); return { fy: n.fy, level: LEVEL_Y[levelOf(n)], fx: n.fx, fz: n.fz }; });
    await page.click("#layBtn");
    out.drag.unlayered = await page.evaluate(() => cur.byId.get("serveur").fy);
    await page.click("#pinBtn");
    out.drag.released = await page.evaluate(() => { const n = cur.byId.get("serveur");
      return { fx: n.fx == null, fy: n.fy == null, fz: n.fz == null, pin: !n.__pin, button: $("#pinBtn").disabled }; });
    out.drag.dblclick = await page.evaluate(() => {
      const n = cur.byId.get("serveur"); G.onNodeDragEnd()(n, { x: 0, y: 0, z: 0 });
      const pinned = n.fx != null;
      st.hover = null; graphEl.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
      return pinned && n.fx == null && n.fy == null && n.fz == null;
    });
    // 4. orbite de la caméra : elle tourne autour du cerveau à distance constante, puis s'arrête en douceur
    const cam = () => page.evaluate(() => { const p = G.camera().position, o = st.orbit;
      return o ? { a: Math.atan2(p.x - o.ctr.x, p.z - o.ctr.z), r: Math.hypot(p.x - o.ctr.x, p.z - o.ctr.z), r0: o.r } : null; });
    out.orbit = { tip: await page.evaluate(() => $("#orbBtn").dataset.tip) };
    await page.click("#orbBtn");
    out.orbit.pressed = await page.evaluate(() => $("#orbBtn").getAttribute("aria-pressed"));
    out.orbit.controlsOff = await page.evaluate(() => G.controls().enabled === false);
    await page.waitForTimeout(400);
    const c1 = await cam();
    out.orbit.turned = !!c1 && await page.waitForFunction(a => { const p = G.camera().position, o = st.orbit;  // machine chargée : on attend
      return !!o && Math.abs(Math.atan2(p.x - o.ctr.x, p.z - o.ctr.z) - a) > 0.01; }, c1.a, { timeout: 15000 }).then(() => true, () => false);
    const c2 = await cam();
    out.orbit.steady = !!c2 && Math.abs(c2.r - c2.r0) < 1;
    await page.click("#orbBtn");
    out.orbit.released = await page.evaluate(() => $("#orbBtn").getAttribute("aria-pressed") === "false" && G.controls().enabled === true);
    out.orbit.stopped = await page.waitForFunction(() => !st.orbit, null, { timeout: 10000 }).then(() => true, () => false);
    await page.click("#orbBtn");
    await page.click("#fxBtn");  // effets coupés : plus d'orbite
    await page.waitForTimeout(200);
    out.orbit.fxOff = await page.evaluate(() => ({ orbit: !!st.orbit, disabled: $("#orbBtn").disabled, controls: G.controls().enabled }));
    await page.click("#fxBtn");
    out.orbit.fxBack = await page.evaluate(() => !$("#orbBtn").disabled);
    // 5. onglet caché : la boucle et le rendu de 3d-force-graph s'arrêtent, puis reprennent
    out.visibility = await page.evaluate(async () => {
      const calls = { pause: 0, resume: 0 }, pause = G.pauseAnimation, resume = G.resumeAnimation;
      G.pauseAnimation = function(){ calls.pause++; return pause.apply(this, arguments); };
      G.resumeAnimation = function(){ calls.resume++; return resume.apply(this, arguments); };
      let hide = true;
      Object.defineProperty(document, "hidden", { configurable: true, get: () => hide });
      const wait = ms => new Promise(r => setTimeout(r, ms));
      document.dispatchEvent(new Event("visibilitychange"));
      document.dispatchEvent(new Event("visibilitychange"));  // deux fois : une seule pause
      const t0 = lastT; await wait(400);
      const r = { paused: anim.paused, raf: anim.raf, frozen: lastT === t0, pause: calls.pause };
      hide = false;
      document.dispatchEvent(new Event("visibilitychange"));
      const t1 = lastT;
      for (let i = 0; i < 100 && lastT <= t1; i++) await wait(100);  // la première image revenue (machine chargée : jusqu'à 10 s)
      Object.assign(r, { resumed: !anim.paused && !!anim.raf, running: lastT > t1, resume: calls.resume });
      delete document.hidden;
      G.pauseAnimation = pause; G.resumeAnimation = resume;
      return r;
    });
    await page.context().close();
    // 6. le système demande moins d'animations : pas d'orbite
    const calm = await open(browser, file, { reducedMotion: "reduce" }, out);
    out.reduced = await calm.evaluate(() => {
      const r = { disabled: $("#orbBtn").disabled, tip: $("#orbBtn").dataset.tip, started: setOrbit(true) };
      $("#orbBtn").click();
      r.orbit = !!st.orbit;
      return r;
    });
    await calm.context().close();
  } catch (e) {
    out.errors.push("script : " + String(e.message || e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
})();
