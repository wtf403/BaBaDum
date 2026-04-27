# DeepL Proxy Server

This proxy server handles DeepL API requests to avoid CORS issues when making translations from the browser.

## Setup

1. Make sure Node.js is installed on your system

2. Navigate to the server directory:
```bash
cd server
```

3. Start the proxy server:
```bash
node proxy.js
```

The server will start on `http://localhost:3001`

## Configuration

The proxy server automatically reads the API key from `../config.js`:

```javascript
var Config = {
  deepl: {
    apiKey: "your-api-key-here",
    useFreeApi: true,
  },
};
```

- `apiKey`: Your DeepL API key
- `useFreeApi`: Set to `true` for free API, `false` for pro API

## API Endpoint

**POST** `/api/deepl/translate`

**Request Body (x-www-form-urlencoded):**
- `text`: Text to translate
- `source_lang`: Source language code (e.g., "FR", "DE", "ES")
- `target_lang`: Target language code (e.g., "EN", "FR", "DE")

**Response:**
```json
{
  "translations": [
    {
      "detected_source_language": "FR",
      "text": "translated text"
    }
  ]
}
```

## Running with the App

1. Start the proxy server in one terminal:
```bash
cd server
node proxy.js
```

2. Start your web server in another terminal (from the babadum directory):
```bash
# Example with Python
python -m http.server 8000

# Or with Node.js http-server
npx http-server -p 8000
```

3. Open the app in your browser:
```
http://localhost:8000
```

## Troubleshooting

- **"API key not configured"**: Check that `config.js` has a valid DeepL API key
- **Connection refused**: Make sure the proxy server is running on port 3001
- **CORS errors**: The proxy server should handle CORS automatically
- **Translation not showing**: Check browser console for error messages

## Notes

- The proxy server caches translations to reduce API calls
- Free API has usage limits - check your DeepL account for details
- The server runs on port 3001 by default (can be changed in proxy.js)