// node scripts/html2pdf.mjs <input.html> <output.pdf>   (uses the Chromium installed for Playwright)
import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";
const [, , input, output] = process.argv;
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(pathToFileURL(input).href, { waitUntil: "networkidle" });
await page.pdf({ path: output, format: "A4", margin: { top: "16mm", bottom: "16mm", left: "15mm", right: "15mm" },
  printBackground: true, displayHeaderFooter: true, headerTemplate: "<span></span>",
  footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#777">GigBid R&amp;D report · page <span class="pageNumber"></span> / <span class="totalPages"></span></div>' });
await browser.close();
console.log("wrote", output);
