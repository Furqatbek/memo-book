/* What a browser check should treat as a failure — in one place (A102).
 *
 * Every check watched the page the same way: any `pageerror`, plus any
 * console message of type `error`, failed the run. The second half is
 * wrong, and it is what made `adminwiring` and `freeform` flaky.
 *
 * Chromium logs a console error for ANY resource that fails to load,
 * including a single transient blip on a signed image URL. Measured: zero
 * console errors in a clean run, and exactly one — "Failed to load
 * resource: net::ERR_FAILED" — after one aborted image. That one line was
 * enough to fail a check in which every named assertion still printed `ok`,
 * which is why the failure named nothing and why re-running always said it
 * was fine.
 *
 * It is also asserting something the product does not promise. Since A99 a
 * failed signed image is a condition the editor RECOVERS from: it asks for
 * fresh URLs and redraws. A check that fails because a resource blipped is
 * failing for the thing the product handles.
 *
 * So resource-load noise is counted and reported, never fatal. Everything
 * else stays fatal, and the two that matter are untouched:
 *
 *   - `pageerror` — an uncaught exception, always a real defect;
 *   - a console error our own code wrote, which is us saying something is
 *     wrong.
 *
 * What still covers a genuinely missing asset: `test_editor_assets` in the
 * backend suite proves every referenced local file exists, and
 * `checks/urlrefresh.js` proves a stale signed URL recovers. Neither of
 * those depends on a browser happening not to blip.
 */

/* Browser-generated, not ours. Chromium's wording for a request that did
   not complete — 404, aborted, connection reset, all of them. */
const RESOURCE_NOISE = /Failed to load resource/i;

/** Watch `page`, pushing only real problems into `errors`.
 *  Returns the array of ignored resource-load lines, so a check can print
 *  them: invisible is not the same as harmless. */
function watchPage(page, errors) {
  const noise = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const text = m.text();
    if (RESOURCE_NOISE.test(text)) { noise.push(text); return; }
    errors.push(`console: ${text}`);
  });
  return noise;
}

module.exports = { watchPage, RESOURCE_NOISE };
