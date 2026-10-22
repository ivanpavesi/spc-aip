// Eseguito da pytest con pagine renderizzate dal TestClient e soli dati sintetici.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

async function serve(context, html, script) {
    await context.route('**/*', route => {
        if (route.request().url() === 'https://aip.test/') {
            return route.fulfill({ contentType: 'text/html', body: html });
        }
        if (route.request().url() === 'https://aip.test/static/js/invitation-link.js') {
            return route.fulfill({ contentType: 'application/javascript', body: script });
        }
        return route.abort(); // CDN, immagini e ogni altro URL non raggiungono la rete.
    });
}

(async () => {
    const { cases, script } = JSON.parse(fs.readFileSync(0, 'utf8'));
    const browser = await chromium.launch({
        executablePath: process.env.CHROMIUM_PATH || undefined,
        headless: true,
    });
    try {
        for (const testCase of cases) {
            const context = await browser.newContext();
            await serve(context, testCase.html, script);
            await context.addInitScript(() => {
                window.tailwind = {};
                window.__f03_xss = 0;
                window.copied = [];
                Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
                    writeText: value => new Promise(resolve => {
                        window.copied.push(value);
                        window.finishCopy = resolve;
                    }),
                } });
            });
            const page = await context.newPage();
            const errors = [];
            page.on('pageerror', error => errors.push(error.message));
            page.on('dialog', async dialog => {
                errors.push('Unexpected dialog: ' + dialog.message());
                await dialog.dismiss();
            });
            await page.goto('https://aip.test/');
            const button = page.locator('#copy-invite-link');
            if (testCase.expected === null) {
                assert.equal(await button.count(), 0);
            } else {
                assert.equal(await page.locator('#invite-url-field').inputValue(), testCase.expected);
                assert.equal(await button.getAttribute('onclick'), null);
                await button.click();
                assert.equal(await button.isDisabled(), true);
                assert.ok(!(await button.textContent()).includes('Copiato!'));
                assert.deepEqual(await page.evaluate(() => window.copied), [testCase.expected]);
                await page.evaluate(() => window.finishCopy());
                await page.waitForFunction(() => document.getElementById('copy-invite-link').textContent === 'Copiato!');
                assert.equal(await button.isEnabled(), true);

                // Rifiuto dei permessi e API assente: selezione manuale e nessun falso successo.
                for (const unavailable of [false, true]) {
                    await page.evaluate(unavailable => {
                        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: unavailable ? undefined : {
                            writeText: () => Promise.reject(new Error('Permission denied')),
                        } });
                    }, unavailable);
                    await button.click();
                    await page.waitForFunction(() => document.getElementById('invite-copy-status').textContent.includes('manualmente'));
                    assert.ok(!(await button.textContent()).includes('Copiato!'));
                    assert.equal(await button.isEnabled(), true);
                    assert.deepEqual(await page.locator('#invite-url-field').evaluate(field => [
                        document.activeElement === field, field.selectionStart, field.selectionEnd,
                    ]), [true, 0, testCase.expected.length]);
                }
            }
            assert.equal(await page.evaluate(() => window.__f03_xss), 0);
            assert.deepEqual(errors, []);
            await context.close();
        }
        // Verifica anche la Clipboard API reale di Chromium con il link appena generato.
        const context = await browser.newContext();
        await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://aip.test' });
        await context.addInitScript(() => { window.tailwind = {}; });
        await serve(context, cases[0].html, script);
        const page = await context.newPage();
        await page.goto('https://aip.test/');
        await page.locator('#copy-invite-link').click();
        await page.waitForFunction(() => document.getElementById('copy-invite-link').textContent === 'Copiato!');
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), cases[0].expected);
        await context.close();
        console.log(`${cases.length + 1} browser checks passed`);
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
