// Ouvre cerveau.html depuis le disque (file://) dans un Chromium sans écran, réseau coupé, et dit en JSON ce qui
// s'est passé : erreurs de la console, requêtes vers l'extérieur, graphe dessiné, effets actifs. Lancé par
// tests/test_vue3d.py quand Playwright et Chromium sont là (sinon ce test-là est sauté, et le dit).
// Usage : node tests/vue3d_navigateur.js <chemin de cerveau.html>
const path = require("path");
const { pathToFileURL } = require("url");

(async () => {
  let playwright;
  try { playwright = require("playwright"); } catch (e) { console.log(JSON.stringify({ skip: "playwright absent" })); return; }
  const file = path.resolve(process.argv[2]);
  const out = { errors: [], outside: [], warnings: [] };
  let browser;
  try {
    const exe = process.env.CERVEAU_CHROMIUM || undefined;
    browser = await playwright.chromium.launch({ executablePath: exe, args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] });
  } catch (e) {
    console.log(JSON.stringify({ skip: "chromium absent : " + String(e.message || e).split("\n")[0] }));
    return;
  }
  try {
    const context = await browser.newContext({ offline: true, viewport: { width: 1200, height: 800 } });
    const page = await context.newPage();
    await page.route("**/*", route => {
      const url = route.request().url();
      if (url.startsWith("file:") || url.startsWith("data:") || url.startsWith("blob:")) return route.continue();
      out.outside.push(url);
      return route.abort();
    });
    page.on("console", m => {
      if (m.type() === "error") out.errors.push(m.text());
      else if (m.type() === "warning") out.warnings.push(m.text());
    });
    page.on("pageerror", e => out.errors.push("pageerror: " + (e.message || e)));
    await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("#boot") && document.querySelector("#boot").classList.contains("done"), null, { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(1500);
    Object.assign(out, await page.evaluate(() => {
      const canvas = document.querySelector("canvas");
      const fb = document.querySelector("#fallback");
      return {
        forceGraph: typeof window.ForceGraph3D === "function",
        fxLoaded: !!(window.__cerveauFX && window.__cerveauFX.THREE),
        fxRevision: window.__cerveauFX ? String(window.__cerveauFX.revision) : null,
        threeRevision: window.__THREE__ ? String(window.__THREE__) : null,
        fxActive: typeof FX !== "undefined" && !!FX.T,
        bloom: typeof FX !== "undefined" && !!FX.bloom,
        canvas: !!canvas, canvasSize: canvas ? [canvas.width, canvas.height] : null,
        fallbackShown: !!fb && getComputedStyle(fb).display !== "none",
        fallbackText: (document.querySelector("#fbmsg") || {}).textContent || "",
        nodes: typeof G !== "undefined" && G && G.graphData ? G.graphData().nodes.length : 0,
      };
    }));
  } catch (e) {
    out.errors.push("script: " + String(e.message || e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
})();
