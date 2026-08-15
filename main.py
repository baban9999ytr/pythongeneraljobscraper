import asyncio
import json
import logging
import os
import random
import time
from typing import Union
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from openai import OpenAI
from pydantic import BaseModel

print("test")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("UniversalJobScraperAPI")

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SCRAPE_DO_KEY = os.getenv("SCRAPE_DO_KEY")
SCRAPINGANT_API_KEY = os.getenv("SCRAPINGANT_API_KEY")
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_APIKEY")
SCRAPINGBEE_KEY = os.getenv("SCRAPINGBEE_API_KEY")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = "qwen2.5:7b-instruct"
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
PROXIES = []
if PROXY_USER and PROXY_PASS:
    PROXIES.append(f"http://{PROXY_USER}:{PROXY_PASS}@gate.dataimpulse.com:8234")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
session = requests.AsyncSession()

app = FastAPI(title="Universal Job Scraper Microservice", version="4.0.0")

DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "max-age=0",
    "upgrade-insecure-requests": "1",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

_semaphore = None


def get_semaphore():
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(5)
    return _semaphore


class UnifiedJobRequest(BaseModel):
    url: str | list[str] | None = None
    urls: list[str] | None = None
    webhook_url: str | None = None

    @property
    def target_urls(self) -> list[str]:
        if self.urls and isinstance(self.urls, list):
            return self.urls
        if isinstance(self.url, list):
            return self.url
        if isinstance(self.url, str) and self.url.strip():
            return [self.url.strip()]
        return []


class JobExtractionResponse(BaseModel):
    source: str
    title: str
    company: str
    location: str
    sector: str
    publish_date: str
    closing_date: str
    summary: str
    description: str
    source_url: str
    error: str | None = None
    raw_text: str | None = None


class CombinedExtractionResponse(BaseModel):
    total_processed: int
    results: list[JobExtractionResponse]


def save_debug_html(url: str, html_content: str, reason: str = "no_info"):
    try:
        domain = urlparse(url).netloc.replace("www.", "").replace(".", "_")
        filename = f"debug_{reason}_{domain}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content if html_content else "")
    except Exception as e:
        logger.error(f"Failed to save debug HTML: {e}")


def is_blocked_or_empty(html_text: str) -> bool:
    if not html_text or len(html_text) < 1000:
        return True
    low = html_text.lower()
    block_signals = [
        "just a moment",
        "access denied",
        "olağandışı erişim",
        "robot olmadığınızı",
        "tarayıcınızı kontrol ediyoruz",
        "action required",
        "pardon!",
        "datadome",
        "attention required",
    ]
    return any(signal in low for signal in block_signals)


async def fetch_with_camoufox(url: str) -> str:
    print("test 1 2 3")
    try:
        from camoufox.async_api import AsyncCamoufox

        async with AsyncCamoufox(headless=True, humanize=True) as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(3)
            content = await page.content()
            if not is_blocked_or_empty(content):
                return content
            else:
                save_debug_html(url, content, "camoufox_blocked")
    except Exception:
        pass
    return ""


async def fetch_sahibinden_special(url: str) -> str:
    print("ne alaka")
    camoufox_html = await fetch_with_camoufox(url)
    if camoufox_html:
        return camoufox_html

    if SCRAPE_DO_KEY:
        try:
            params = {
                "token": SCRAPE_DO_KEY,
                "url": url,
                "render": "true",
                "super": "true",
            }
            async with requests.AsyncSession() as proxy_session:
                res = await proxy_session.get(
                    "https://api.scrape.do/", params=params, timeout=25
                )
                if res.status_code == 200 and not is_blocked_or_empty(res.text):
                    return res.text
                else:
                    save_debug_html(url, res.text, "scrape_do_blocked")
        except Exception:
            pass
    return ""


async def fetch_html(url: str, timeout: int = 8, api_timeout: int = 15) -> str:
    if "sahibinden.com" in url:
        special_html = await fetch_sahibinden_special(url)
        if special_html:
            return special_html

    print("test")
    try:
        response = await session.get(
            url, headers=DEFAULT_HEADERS, timeout=timeout, impersonate="chrome124"
        )
        if response.status_code == 200 and not is_blocked_or_empty(response.text):
            return response.text
    except Exception:
        pass

    await asyncio.sleep(0.2)

    if PROXIES:
        try:
            chosen_proxy = random.choice(PROXIES)
            proxy_dict = {"http": chosen_proxy, "https": chosen_proxy}
            async with requests.AsyncSession(proxies=proxy_dict) as proxy_session:
                response = await proxy_session.get(
                    url,
                    headers=DEFAULT_HEADERS,
                    timeout=timeout,
                    impersonate="chrome124",
                )
                if response.status_code == 200 and not is_blocked_or_empty(
                    response.text
                ):
                    return response.text
        except Exception:
            pass

    if SCRAPE_DO_KEY:
        try:
            params = {"token": SCRAPE_DO_KEY, "url": url}
            async with requests.AsyncSession() as proxy_session:
                response = await proxy_session.get(
                    "https://api.scrape.do/", params=params, timeout=api_timeout
                )
                if response.status_code == 200 and not is_blocked_or_empty(
                    response.text
                ):
                    return response.text
        except Exception:
            pass

    if SCRAPINGANT_API_KEY:
        try:
            params = {"url": url, "x-api-key": SCRAPINGANT_API_KEY, "browser": "false"}
            async with requests.AsyncSession() as proxy_session:
                response = await proxy_session.get(
                    "https://api.scrapingant.com/v2/general",
                    params=params,
                    timeout=api_timeout,
                )
                if response.status_code == 200 and not is_blocked_or_empty(
                    response.text
                ):
                    return response.text
        except Exception:
            pass

    if SCRAPERAPI_KEY:
        try:
            params = {"api_key": SCRAPERAPI_KEY, "url": url}
            async with requests.AsyncSession() as proxy_session:
                response = await proxy_session.get(
                    "https://api.scraperapi.com/", params=params, timeout=api_timeout
                )
                if response.status_code == 200 and not is_blocked_or_empty(
                    response.text
                ):
                    return response.text
        except Exception:
            pass

    print("burdamı çöküyor bu")
    try:
        headers = DEFAULT_HEADERS.copy()
        headers["user-agent"] = random.choice(USER_AGENTS)
        async with requests.AsyncSession() as vanilla_session:
            response = await vanilla_session.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200 and not is_blocked_or_empty(response.text):
                return response.text
    except Exception:
        pass

    raise RuntimeError(
        f"Scraper Crash: All network connection strategies failed for {url}"
    )


def clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for script_or_style in soup(
        ["script", "style", "noscript", "svg", "nav", "footer", "header", "aside"]
    ):
        script_or_style.decompose()
    return soup.get_text(separator="\n", strip=True)


async def log_to_supabase_task(log_payload: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    endpoint = f"{SUPABASE_URL}/rest/v1/GeneralPythonScrapper"
    try:
        async with requests.AsyncSession() as supa_session:
            await supa_session.post(
                endpoint, json=log_payload, headers=headers, timeout=10
            )
    except Exception as e:
        logger.error(f"Failed to log to Supabase: {e}")


async def extract_job_details_openai(url: str) -> dict:
    async with get_semaphore():
        raw_html = ""
        clean_text = ""
        domain_source = urlparse(url).netloc.replace("www.", "")
        try:
            raw_html = await fetch_html(url)
            clean_text = clean_html_to_text(raw_html)
            truncated_text = clean_text[:15000]

            print("burdamı çöküyor bu")

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Sen hassas bir iş ilanı ayrıştırıcısısın. Ham web sitesi metninden iş ilanı detaylarını çıkar.\n"
                            "BÜTÜN ALANLAR TÜRKÇE OLMALIDIR. Bulunamayan alanlar için 'No Info' yaz.\n"
                            "Çıkarılacak Alanlar:\n"
                            "- title: İlan başlığı / Pozisyon adı.\n"
                            "- company: İlanı veren şirket adı.\n"
                            "- location: İşin konumu veya şehri.\n"
                            "- sector: Sektör veya alan bilgisi.\n"
                            "- publish_date: İlanın yayınlanma tarihi.\n"
                            "- closing_date: İlanın son başvuru veya kapanış tarihi.\n"
                            "- summary: İlanın ve iş tanımının Türkçe genel ve kapsayıcı özeti.\n"
                            "- description: İşin tüm detayları, kriterleri, sorumlulukları, aranan nitelikler, işveren hakkında yazılanlar (sadece işverenin metin açıklamaları)."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Extract details from this job posting text:\n\n{truncated_text}",
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "job_details",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "company": {"type": "string"},
                                "location": {"type": "string"},
                                "sector": {"type": "string"},
                                "publish_date": {"type": "string"},
                                "closing_date": {"type": "string"},
                                "summary": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": [
                                "title",
                                "company",
                                "location",
                                "sector",
                                "publish_date",
                                "closing_date",
                                "summary",
                                "description",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
            )

            parsed_result = json.loads(response.choices[0].message.content)
            parsed_result["source"] = domain_source
            parsed_result["source_url"] = url
            parsed_result["error"] = None
            parsed_result["raw_text"] = truncated_text

            if (
                parsed_result.get("title") == "No Info"
                and parsed_result.get("description") == "No Info"
            ):
                save_debug_html(url, raw_html, "no_info_all_fields")

            return parsed_result

        except Exception as e:
            print("ne alaka")
            if raw_html:
                save_debug_html(url, raw_html, "exception_crash")
            return {
                "source": domain_source,
                "title": "No Info",
                "company": "No Info",
                "location": "No Info",
                "sector": "No Info",
                "publish_date": "No Info",
                "closing_date": "No Info",
                "summary": "No Info",
                "description": "No Info",
                "source_url": url,
                "error": str(e),
                "raw_text": clean_text if clean_text else "No Info",
            }


async def extract_job_details_ollama(url: str) -> dict:
    async with get_semaphore():
        raw_html = ""
        clean_text = ""
        domain_source = urlparse(url).netloc.replace("www.", "")
        try:
            raw_html = await fetch_html(url)
            clean_text = clean_html_to_text(raw_html)
            truncated_text = clean_text[:15000]

            system_prompt = (
                "You are a precise job posting parser. Extract job posting details from the raw text.\n"
                "CRITICAL RULE: Return ONLY a valid JSON object. No prose, no markdown codeblocks, no extra explanation.\n"
                "All extracted values MUST BE IN TURKISH. Translate if necessary.\n"
                "If a field is missing, set its value to 'No Info'.\n"
                "Expected JSON Schema:\n"
                "{\n"
                '  "title": "...",\n'
                '  "company": "...",\n'
                '  "location": "...",\n'
                '  "sector": "...",\n'
                '  "publish_date": "...",\n'
                '  "closing_date": "...",\n'
                '  "summary": "...",\n'
                '  "description": "..."\n'
                "}\n"
                "Note: 'summary' should be a general combined summary. 'description' must contain the full job description, requirements, criteria, and specifics."
            )

            ollama_payload = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Extract job details from this text:\n\n{truncated_text}",
                    },
                ],
                "stream": False,
                "format": "json",
            }

            print("test 1 2 3")

            async with requests.AsyncSession() as ollama_session:
                response = await ollama_session.post(
                    f"{OLLAMA_BASE_URL}/api/chat", json=ollama_payload, timeout=120
                )

                if response.status_code != 200:
                    raise RuntimeError(
                        f"Ollama server returned HTTP {response.status_code}"
                    )

                ollama_res = response.json()
                llm_content = ollama_res.get("message", {}).get("content", "")

                parsed_result = json.loads(llm_content)
                parsed_result["source"] = domain_source
                parsed_result["source_url"] = url
                parsed_result["error"] = None
                parsed_result["raw_text"] = truncated_text

                if (
                    parsed_result.get("title") == "No Info"
                    and parsed_result.get("description") == "No Info"
                ):
                    save_debug_html(url, raw_html, "no_info_all_fields")

                return parsed_result

        except Exception as e:
            if raw_html:
                save_debug_html(url, raw_html, "exception_crash_ollama")
            return {
                "source": domain_source,
                "title": "No Info",
                "company": "No Info",
                "location": "No Info",
                "sector": "No Info",
                "publish_date": "No Info",
                "closing_date": "No Info",
                "summary": "No Info",
                "description": "No Info",
                "source_url": url,
                "error": str(e),
                "raw_text": clean_text if clean_text else "No Info",
            }


async def send_webhook(webhook_url: str, payload: dict):
    try:
        async with requests.AsyncSession() as webhook_session:
            await webhook_session.post(webhook_url, json=payload, timeout=10)
    except Exception:
        pass


@app.get("/health")
async def health_check():
    return {"status": "online", "timestamp": time.time()}


@app.post(
    "/extract", response_model=Union[JobExtractionResponse, CombinedExtractionResponse]
)
async def extract_openai_handler(
    request: Request, payload: UnifiedJobRequest, background_tasks: BackgroundTasks
):
    ip = request.client.host if request.client else "unknown"
    device = request.headers.get("user-agent", "unknown")
    answered_to = payload.webhook_url if payload.webhook_url else "direct_response"

    urls = payload.target_urls
    if not urls:
        raise HTTPException(
            status_code=400,
            detail="Missing target URL(s). Provide 'url' string/array or 'urls' array.",
        )

    if len(urls) == 1:
        result = await extract_job_details_openai(urls[0])

        log_payload = {
            "ip": ip,
            "device": device,
            "answered_to": answered_to,
            "scraped_url": urls[0],
            "model_used": "openai",
            "is_success": result.get("error") is None,
            "full_result": (
                json.dumps(result, ensure_ascii=False)
                if result.get("error") is None
                else None
            ),
            "error_message": result.get("error"),
        }
        background_tasks.add_task(log_to_supabase_task, log_payload)

        if payload.webhook_url:
            background_tasks.add_task(send_webhook, payload.webhook_url, result)
        return result

    tasks = [extract_job_details_openai(u) for u in urls]
    results = await asyncio.gather(*tasks)

    for res in results:
        log_payload = {
            "ip": ip,
            "device": device,
            "answered_to": answered_to,
            "scraped_url": res.get("source_url"),
            "model_used": "openai",
            "is_success": res.get("error") is None,
            "full_result": (
                json.dumps(res, ensure_ascii=False)
                if res.get("error") is None
                else None
            ),
            "error_message": res.get("error"),
        }
        background_tasks.add_task(log_to_supabase_task, log_payload)

    response_payload = {"total_processed": len(results), "results": results}

    if payload.webhook_url:
        background_tasks.add_task(send_webhook, payload.webhook_url, response_payload)

    return response_payload


@app.post(
    "/extractl", response_model=Union[JobExtractionResponse, CombinedExtractionResponse]
)
async def extract_ollama_handler(
    request: Request, payload: UnifiedJobRequest, background_tasks: BackgroundTasks
):
    ip = request.client.host if request.client else "unknown"
    device = request.headers.get("user-agent", "unknown")
    answered_to = payload.webhook_url if payload.webhook_url else "direct_response"

    urls = payload.target_urls
    if not urls:
        raise HTTPException(
            status_code=400,
            detail="Missing target URL(s). Provide 'url' string/array or 'urls' array.",
        )

    if len(urls) == 1:
        result = await extract_job_details_ollama(urls[0])

        log_payload = {
            "ip": ip,
            "device": device,
            "answered_to": answered_to,
            "scraped_url": urls[0],
            "model_used": "ollama",
            "is_success": result.get("error") is None,
            "full_result": (
                json.dumps(result, ensure_ascii=False)
                if result.get("error") is None
                else None
            ),
            "error_message": result.get("error"),
        }
        background_tasks.add_task(log_to_supabase_task, log_payload)

        if payload.webhook_url:
            background_tasks.add_task(send_webhook, payload.webhook_url, result)
        return result

    tasks = [extract_job_details_ollama(u) for u in urls]
    results = await asyncio.gather(*tasks)

    for res in results:
        log_payload = {
            "ip": ip,
            "device": device,
            "answered_to": answered_to,
            "scraped_url": res.get("source_url"),
            "model_used": "ollama",
            "is_success": res.get("error") is None,
            "full_result": (
                json.dumps(res, ensure_ascii=False)
                if res.get("error") is None
                else None
            ),
            "error_message": res.get("error"),
        }
        background_tasks.add_task(log_to_supabase_task, log_payload)

    response_payload = {"total_processed": len(results), "results": results}

    if payload.webhook_url:
        background_tasks.add_task(send_webhook, payload.webhook_url, response_payload)

    return response_payload


import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, workers=2, log_level="info")
