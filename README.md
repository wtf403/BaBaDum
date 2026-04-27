# Ba Ba Dum - Language Learning Game

Play and learn. 1500 words, 21 languages, 5 games.

## Features

- Multiple language support including Chinese (中文)
- DeepL API integration for Chinese character transcription
- Audio pronunciation with replay functionality
- Interactive games for vocabulary learning

## Setup

### DeepL API Configuration (for Chinese transcription)

1. Get a DeepL API key:
   - Visit https://www.deepl.com/pro-api
   - Sign up for a free account (500,000 characters/month)
   - Copy your API key

2. Configure the application:
   ```bash
   cp config.example.js config.js
   ```

3. Edit `config.js` and add your API key:
   ```javascript
   var Config = {
     deepl: {
       apiKey: "your-api-key-here",
       useFreeApi: true,
     },
   };
   ```

4. The `config.js` file is gitignored to protect your API key

### Running the Application

Start the local server:
```bash
python server.py
```

Then open your browser to:
```
http://localhost:8000
```

For Chinese language with transcription:
```
http://localhost:8000/play/?lang=13&game=1
```

## How It Works

When Chinese language is selected (`lang=13`), the application:
1. Displays Chinese characters in the game
2. Makes a request to DeepL API to get English transcription
3. Shows the transcription below the Chinese text
4. Caches results to minimize API calls

## Language Codes

- `lang=1` - English (US)
- `lang=13` - Chinese (中文)
- See `index.html` for full list of supported languages

## Credits

Copyright © Aleksandra Mizielińska & Daniel Mizieliński
http://hipopotamstudio.pl