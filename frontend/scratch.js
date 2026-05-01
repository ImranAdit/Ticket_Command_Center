const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch();
  const page = await browser.newPage();
  
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
  page.on('response', response => {
    if (!response.ok()) {
      console.log('RESPONSE ERROR:', response.url(), response.status());
    }
  });

  console.log("Navigating...");
  await page.goto('https://ticketcommandcenter.up.railway.app/', { waitUntil: 'networkidle0' });
  console.log("Navigation complete.");
  
  await browser.close();
})();
