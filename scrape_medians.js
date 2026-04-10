/*
 * scrape_medians.js — Refresh 3Y/5Y/10Y median PE for all 14 sectors from Screener.
 *
 * HOW TO USE (two options):
 *
 * OPTION 1 — Paste into Screener console:
 *   1. Open https://www.screener.in/company/NIFTY/ in Chrome (must be logged in)
 *   2. Open DevTools console (Cmd+Opt+J)
 *   3. Paste this entire file and press Enter
 *   4. Wait ~2 minutes — it loops through all 14 sectors in a hidden iframe
 *   5. Copy the final JSON output and save to medians_curated.json
 *
 * OPTION 2 — Ask Claude in Cowork:
 *   "Refresh medians from screener" — Claude will run this via Chrome MCP.
 *
 * Output: a JSON object matching the schema of medians_curated.json
 */

(async () => {
  const SECTORS = {
    "NIFTY 50":           "NIFTY",
    "NIFTY NEXT 50":      "NIFTYJR",
    "NIFTY SMALLCAP 250": "SMALLCA250",
    "NIFTY MICROCAP 250": "NFMICRO250",
    "NIFTY BANK":         "BANKNIFTY",
    "NIFTY PSU BANK":     "CNXPSUBANK",
    "NIFTY AUTO":         "CNXAUTO",
    "NIFTY REALTY":       "CNXREALTY",
    "NIFTY IT":           "CNXIT",
    "NIFTY INFRA":        "CNXINFRAST",
    "NIFTY PHARMA":       "CNXPHARMA",
    "NIFTY FMCG":         "CNXFMCG",
    "NIFTY METAL":        "CNXMETAL",
    "NIFTY ENERGY":       "CNXENERY",
  };

  const wait = ms => new Promise(r => setTimeout(r, ms));

  // Create a hidden iframe for loading sector pages without navigating away
  const iframe = document.createElement("iframe");
  iframe.style.cssText = "position:fixed;top:-9999px;left:-9999px;width:1200px;height:800px";
  document.body.appendChild(iframe);

  const scrapeSector = async (slug) => {
    iframe.src = "/company/" + slug + "/";
    // Wait for load + chart render
    await new Promise(res => iframe.addEventListener("load", res, { once: true }));
    await wait(2000); // let chart JS run

    const doc = iframe.contentDocument;
    const click = (txt) => {
      const b = Array.from(doc.querySelectorAll("button"))
        .find(x => x.textContent.trim() === txt);
      if (b) b.click();
      return !!b;
    };
    const read = () => {
      const t = doc.querySelector("#chart")?.textContent.replace(/\s+/g, " ") || "";
      const m = t.match(/Median (?:Index )?PE\s*=\s*([\d.]+)/i);
      return m ? parseFloat(m[1]) : null;
    };

    click("PE Ratio"); await wait(1200);
    click("3Yr");  await wait(900); const median3y  = read();
    click("5Yr");  await wait(900); const median5y  = read();
    click("10Yr"); await wait(900); const median10y = read();
    return { median3y, median5y, median10y, slug };
  };

  const results = {};
  for (const [name, slug] of Object.entries(SECTORS)) {
    console.log(`[${Object.keys(results).length + 1}/14] Scraping ${name}...`);
    try {
      results[name] = await scrapeSector(slug);
      console.log(`  → 3Y:${results[name].median3y}  5Y:${results[name].median5y}  10Y:${results[name].median10y}`);
    } catch (e) {
      console.error(`  ✗ ${name}: ${e.message}`);
      results[name] = { error: e.message, slug };
    }
  }

  document.body.removeChild(iframe);

  const out = {
    source: "screener.in /company/{slug}/ — PE Ratio chart, 3Yr/5Yr/10Yr toggles",
    scraped_at: new Date().toISOString().split("T")[0],
    note: "Re-scrape monthly. Values read from 'Median Index PE = X' label.",
    medians: results,
  };

  console.log("\n=== SCRAPE COMPLETE — copy the JSON below into medians_curated.json ===\n");
  console.log(JSON.stringify(out, null, 2));

  // Also copy to clipboard if allowed
  try {
    await navigator.clipboard.writeText(JSON.stringify(out, null, 2));
    console.log("\n✓ Copied to clipboard");
  } catch {
    console.log("\n(clipboard copy blocked — manually copy the JSON above)");
  }

  return out;
})();
