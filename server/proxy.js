const http = require('http');
const https = require('https');
const url = require('url');
const querystring = require('querystring');

const PORT = 3001;
const DEEPL_FREE_API = 'https://api-free.deepl.com/v2/translate';
const DEEPL_PRO_API = 'https://api.deepl.com/v2/translate';

// Load config
let config = { deepl: { apiKey: '', useFreeApi: true } };
try {
  const fs = require('fs');
  const configContent = fs.readFileSync('../config.js', 'utf8');
  const configMatch = configContent.match(/var Config = ({[\s\S]*?});/);
  if (configMatch) {
    config = eval('(' + configMatch[1] + ')');
  }
} catch (e) {
  console.error('Could not load config.js:', e.message);
}

const server = http.createServer((req, res) => {
  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  if (req.method === 'POST' && req.url === '/api/deepl/translate') {
    let body = '';

    req.on('data', chunk => {
      body += chunk.toString();
    });

    req.on('end', () => {
      try {
        const params = querystring.parse(body);
        const apiKey = config.deepl.apiKey;
        const apiUrl = config.deepl.useFreeApi ? DEEPL_FREE_API : DEEPL_PRO_API;

        if (!apiKey) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'API key not configured' }));
          return;
        }

        const postData = querystring.stringify({
          text: params.text,
          source_lang: params.source_lang,
          target_lang: params.target_lang,
          auth_key: apiKey
        });

        const apiUrlParsed = url.parse(apiUrl);
        const options = {
          hostname: apiUrlParsed.hostname,
          port: 443,
          path: apiUrlParsed.path,
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Content-Length': Buffer.byteLength(postData)
          }
        };

        const proxyReq = https.request(options, (proxyRes) => {
          let data = '';

          proxyRes.on('data', (chunk) => {
            data += chunk;
          });

          proxyRes.on('end', () => {
            res.writeHead(proxyRes.statusCode, {
              'Content-Type': 'application/json'
            });
            res.end(data);
          });
        });

        proxyReq.on('error', (e) => {
          console.error('Proxy request error:', e);
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: e.message }));
        });

        proxyReq.write(postData);
        proxyReq.end();

      } catch (e) {
        console.error('Error processing request:', e);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
  } else {
    res.writeHead(404);
    res.end('Not found');
  }
});

server.listen(PORT, () => {
  console.log(`DeepL proxy server running on http://localhost:${PORT}`);
  console.log(`Using ${config.deepl.useFreeApi ? 'FREE' : 'PRO'} API`);
  console.log(`API Key: ${config.deepl.apiKey ? 'Configured' : 'NOT CONFIGURED'}`);
});
