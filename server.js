const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

/* ── STATIC FILES ── */
app.use(express.static(path.join(__dirname, 'frontend')));

/* ── HEALTH CHECK (useful for hosting platforms) ── */
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok' });
});

/* ── CATCH-ALL (SPA SUPPORT) ── */
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'frontend', 'index.html'));
});

/* ── START SERVER ── */
app.listen(PORT, () => {
  console.log(`🚀 Server running at http://localhost:${PORT}`);
});
