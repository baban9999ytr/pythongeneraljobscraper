# Universal Job Scraper Microservice

An asynchronous FastAPI microservice designed to fetch, bypass anti-scraping measures (using `curl_cffi`, proxies, and `camoufox`), and extract structured job posting data using LLM backends (**OpenAI gpt-4o-mini** or local **Ollama Qwen2.5**).

---

## Disclaimer & Legal Notice

1. **Compliance Notice:** Prior to targeting any domain, ensure your scraping activity complies with the target website's `robots.txt`, Terms of Service (ToS), and relevant local data privacy regulations.
2. **No Liability:** The authors and contributors of this repository accept no responsibility or liability for any misuse, server overload, IP bans, or legal consequences resulting from the execution of this code. Use this tool responsibly and at your own risk.
3. **Open Source & License:** This project is open-source software distributed strictly for educational and research purposes.

---

## Features

- **Dual Extraction Engines:** Switch between OpenAI API (`/extract`) and local Ollama execution (`/extractl`).
- **Resilient Network Architecture:** Fallback sequence incorporating `curl_cffi` (impersonating Chrome TLS fingerprints), DataImpulse proxies, Scrape.do, ScrapingAnt, ScraperAPI, and headful/headless browser emulation via `Camoufox`.
- **Structured JSON Output:** Enforces JSON Schema responses for job attributes (`title`, `company`, `location`, `sector`, `dates`, `summary`, `description`).
- **Async Concurrency & Logging:** Controlled via semaphore concurrency limits and background execution tasks (Webhook dispatching & Supabase audit logging).

---

## Tech Stack & Dependencies

Add the following to your `requirements.txt`:

```text
fastapi>=0.100.0
uvicorn[standard]>=0.20.0
pydantic>=2.0.0
curl_cffi>=0.5.0
beautifulsoup4>=4.12.0
openai>=1.0.0
python-dotenv>=1.0.0
camoufox>=0.1.0

```

---

## Setup & Prerequisites

### 1. Environment Configuration (`.env`)

Create a `.env` file in the project root:

```env
SUPABASE_URL=
SCRAPE_DO_KEY=
SCRAPINGANT_API_KEY=
SUPABASE_KEY=
SCRAPERAPI_APIKEY=
TEST=
SCRAPINGBEE_API_KEY=
OPENAI_API_KEY=your_openai_api_key
OLLAMA_BASE_URL=http://localhost:11434
OPENAI_ADMIN_KEY=
HUME_API_KEY=
HUME_API_KEY_BACKUP=
HF_TOKEN=
GEMINI_API_KEY=
GROQ_API_KEY =
#these can change
PORT=8000
HOST=0.0.0.0
```

### 2. Install Camoufox Browser Binaries

Execute the fetching command to install required browser binaries:

```bash
camoufox fetch

```

### 3. Setup Local Ollama Engine (Optional for `/extractl`)

Install and start Ollama along with the Qwen model:

```bash
# Install Ollama
curl -fsSL [https://ollama.com/install.sh](https://ollama.com/install.sh) | sh

# Start Ollama service in background
ollama serve &

# Pull the target extraction model
ollama pull qwen2.5:7b-instruct

```

---

## Running the Application

### Development Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

```

### Production Deployment (via PM2)

To keep the service running persistently in a production environment:

```bash
PYTHONUNBUFFERED=1 pm2 start main.py --name "job-scraper" --interpreter python3

```

---

## API Documentation

### Health Check

- **GET** `/health`
- **Response:** `{"status": "online", "timestamp": 1720000000.0}`

### Extract via OpenAI (`/extract`)

- **POST** `/extract`
- **Body:**

```json
{
  "url": "[https://example.com/job/123](https://example.com/job/123)",
  "webhook_url": "[https://your-domain.com/webhook](https://your-domain.com/webhook)"
}
```

_(Accepts a single string `url`, an array of `url` strings, or a `urls` array)._

### Extract via Local Ollama (`/extractl`)

- **POST** `/extractl`
- **Body:**

```json
{
  "urls": [
    "[https://example.com/job/123](https://example.com/job/123)",
    "[https://example.com/job/456](https://example.com/job/456)"
  ]
}
```

---

## Response Structure

```json
{
  "source": "example.com",
  "title": "Software Engineer",
  "company": "Tech Corp",
  "location": "Istanbul / Hybrid",
  "sector": "Software / IT",
  "publish_date": "2026-08-01",
  "closing_date": "No Info",
  "summary": "Full-stack development position focusing on Python and FastAPI.",
  "description": "Detailed requirements, responsibilities, and criteria...",
  "source_url": "[https://example.com/job/123](https://example.com/job/123)",
  "error": null,
  "raw_text": "Extracted DOM text..."
}
```

---

## Acceptable Use Policy

This tool is intended strictly for:

- Academic research and data extraction from websites where you have explicit permission or ownership.
- Automating internal workflow ingestion compliant with site Terms of Service.

**Prohibited Uses:**

- Scraped data reselling in violation of privacy regulations (GDPR, KVKK, etc.).
- Bypassing paywalls or security infrastructure to perform Denial of Service (DoS) attacks.
- Automated extraction from platforms that explicitly prohibit automated parsing in their `robots.txt` or Terms of Service.
