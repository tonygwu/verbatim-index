---
name: polite-bulk-fetching
description: Fetch many URLs from a rate-limited endpoint without getting blocked - use when scraping many URLs in bulk, hitting HTTP 429 or an IP block, tuning request rate, backoff and jitter, or deciding whether a proxy is needed.
---

# Polite bulk fetching

Researched 2026-09-05 against yt-dlp 2026.08.19 and youtube-transcript-api 1.2.4. Numbers are tagged DOCUMENTED, COMMUNITY, or UNKNOWN. Do not invent others.

## First decide: throttle or ban

| Signal | Reading | Response |
|---|---|---|
| HTTP 429, or a block that clears in minutes | Throttle | Slow down, back off, keep going |
| Mixed success and failure across items | Throttle | Slow down, back off, keep going |
| Every request fails for 15+ minutes | Ban | Stop the run. Change IP or wait hours |
| Error names the item, not the caller | Neither | Permanent. Never retry |

The last row is the one people get wrong. "Subtitles are disabled", "video unavailable" and "age restricted" are facts about the item. Retrying them spends rate budget on answers that cannot change, and those wasted requests are what push you into a real block.

Intermittent failure that clears on its own is always the throttle case. Pacing fixes it, a proxy does not.

## The pattern

Four parts, all load-bearing. A rate limiter without a circuit breaker still burns an hour hammering a blocked endpoint.

```python
import random, threading, time

class Throttled(Exception):    """Retryable: server says slow down."""
class Permanent(Exception):    """Never retry: the answer cannot change."""


class Pacer:
    """Shared gap between ALL outbound requests, across every thread."""
    def __init__(self, interval: float, max_interval: float = 60.0):
        self.interval, self.max_interval = interval, max_interval
        self._lock, self._next = threading.Lock(), 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            # Reserve the slot under the lock, sleep OUTSIDE it, so waiting
            # threads do not serialize behind each other's sleep.
            self._next = start + self.interval * random.uniform(0.7, 1.3)
            sleep_for = start - now
        if sleep_for > 0:
            time.sleep(sleep_for)

    def slow_down(self, factor: float = 2.0) -> float:
        # Never narrows again: a rate that got pushed back on is too fast.
        with self._lock:
            self.interval = min(self.interval * factor, self.max_interval)
            return self.interval


class Breaker:
    """Ends the whole run once the endpoint is clearly refusing us."""
    def __init__(self, limit: int = 5):
        self.limit, self._lock = limit, threading.Lock()
        self._streak, self._open = 0, False

    def record_ok(self) -> None:
        with self._lock:
            self._streak = 0

    def record_throttle(self) -> bool:
        with self._lock:
            self._streak += 1              # consecutive, across all threads
            self._open = self._open or self._streak >= self.limit
            return self._open

    def is_open(self) -> bool:
        with self._lock:
            return self._open


BASE, CAP, TRIES = 4.0, 300.0, 5

def fetch_with_retry(item, do_fetch, pacer, breaker, log):
    """do_fetch(item) returns a value, or raises Throttled / Permanent."""
    last = None
    for attempt in range(TRIES):
        if breaker.is_open():
            return {"status": "aborted", "item": item, "error": "circuit_open"}
        pacer.wait()
        try:
            value = do_fetch(item)
        except Permanent as exc:
            return {"status": "failed", "item": item, "error": str(exc)}
        except Throttled as exc:
            last = exc
            if breaker.record_throttle():
                log(f"CIRCUIT OPEN after {breaker.limit} consecutive throttles")
                return {"status": "aborted", "item": item, "error": "circuit_open"}
            pace = pacer.slow_down()
            # Full jitter: sleep uniformly in [0, backoff], not exactly backoff.
            delay = random.uniform(0, min(BASE * 2 ** attempt, CAP))
            log(f"throttled {item}: try {attempt+1}/{TRIES}, sleep {delay:.1f}s, "
                f"pace now {pace:.2f}s")
            time.sleep(delay)
            continue
        breaker.record_ok()
        return {"status": "ok", "item": item, "value": value}
    return {"status": "failed", "item": item, "error": "throttled_out",
            "detail": str(last)}
```

Without a shared breaker each thread backs off privately while the others keep hammering, so a blocked endpoint reads as "slow" for an hour. Report `attempted / ok / failed / aborted` plus a count per error name. A bare success count hides a run that gave up at item 12.

## Why jitter beats a fixed sleep

A fixed gap is a fingerprint. Human traffic is irregular, so a request exactly every 1.500 s for 200 requests is a machine signature anti-bot systems can key on.

A fixed backoff also resynchronises your threads. Eight workers hit a 429, all sleep exactly 30 s, and all wake in the same millisecond. That recovery burst is larger than the burst that caused the block. Jitter is the only fix for this thundering herd.

Full jitter beats a jittered offset. Sleep uniformly in `[0, backoff]` rather than `backoff * random(0.9, 1.1)`. It spreads retries across the whole window and on average finishes sooner for the same collision rate.

## Tool settings

### youtube-transcript-api 1.2.4 (signatures read from the installed package)

```python
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
# YouTubeTranscriptApi(proxy_config=None, http_client=None)
# GenericProxyConfig(http_url=None, https_url=None)
# WebshareProxyConfig(proxy_username, proxy_password, filter_ip_locations=None,
#                     retries_when_blocked=10, domain_name='p.webshare.io', proxy_port=80)
api = YouTubeTranscriptApi(proxy_config=GenericProxyConfig(
    http_url="http://user:pass@host:port", https_url="http://user:pass@host:port"))
```

No sleep or retry options exist, so pacing is entirely your job. `retries_when_blocked` lives only on `WebshareProxyConfig` and only rotates proxy IPs. `http_client` takes a `requests.Session`, which is where a User-Agent or an HTTPAdapter retry policy goes. Cookie authentication is documented as broken; do not build on it.

Classify by exception class, never by message text:

- Retryable throttle: `IpBlocked`, `RequestBlocked`.
- Permanent: `TranscriptsDisabled`, `NoTranscriptFound`, `VideoUnavailable`,
  `VideoUnplayable`, `AgeRestricted`, `InvalidVideoId`, `NotTranslatable`,
  `TranslationLanguageNotAvailable`.
- Ambiguous, retry at most once: `PoTokenRequired`, `YouTubeRequestFailed`.

### yt-dlp 2026.08.19 (flags read from `yt-dlp --help` on this machine)

| Flag | What it does |
|---|---|
| `--sleep-requests SECONDS` | Sleep between requests during data extraction. The one that matters for metadata and search. |
| `--sleep-subtitles SECONDS` | Sleep before each subtitle download. Separate knob: `--sleep-interval` does NOT cover subtitles. |
| `--sleep-interval` / `--max-sleep-interval` | Random sleep before each media download. |
| `-t sleep` | Preset alias for `--sleep-subtitles 5 --sleep-requests 0.75 --sleep-interval 10 --max-sleep-interval 20`. |
| `--retry-sleep [TYPE:]EXPR` | Types `http`, `fragment`, `file_access`, `extractor`. e.g. `--retry-sleep extractor:exp=1:120`. |
| `--extractor-retries N` | Retries for known extractor errors. |
| `--limit-rate RATE` | Bandwidth cap. Does not help with 429, which counts requests not bytes. |
| `--proxy URL` | HTTP, HTTPS or SOCKS proxy. |
| `--impersonate CLIENT[:OS]` | TLS fingerprint impersonation. Needs curl_cffi. |
| `--cookies-from-browser BROWSER` | Raises the ceiling, adds account-ban risk. |

The impersonation warning means curl_cffi is missing. `yt-dlp --list-impersonate-targets` here prints every target as `(unavailable)`. Fix with `pip install "yt-dlp[default,curl-cffi]"`, then re-run that command and confirm a target no longer says unavailable.

Cookies trade one risk for another. The yt-dlp wiki warns an account used with yt-dlp can be banned, temporarily or permanently. Never use a main Google account. For public auto-captions the extra headroom is rarely worth it.

## Numbers: what is actually known

- DOCUMENTED (yt-dlp wiki, YouTube extractor): at default settings a guest session gets roughly 300 videos/hour, about 1000 webpage or player requests per hour. An account gets roughly 2000 videos/hour, about 4000 requests per hour. This is the only request-rate figure from a primary source, and it measures the watch and player endpoints, so read it as a guide for the caption endpoint rather than a guarantee.
- DOCUMENTED (yt-dlp wiki): about 5 to 10 seconds between downloads is the suggested remedy for 429.
- DOCUMENTED (youtube-transcript-api README): YouTube blocks most IPs belonging to cloud providers such as AWS, GCP and Azure, and bans static proxies after extended use. Rotating residential proxies are the maintainer's recommendation.
- COMMUNITY: blocks are reported to clear in roughly 24 to 48 hours. No maintainer figure.
- UNKNOWN: the caption-request rate that triggers a block. No published figure exists. Do not put one in a code comment or a report.

## Proxies: when they are worth it

Skip them for a few hundred items from a home or office connection. Those IPs are not the ones blocked on reputation, so pace the run instead. Use a proxy when you are on a cloud host, which is the documented case and cannot be fixed by slowing down. Use one also when a genuinely paced run still fails, because then the IP is the problem and not the pace.

Costs, from Webshare's public pricing on 2026-09-05. Rotating residential runs about $3.50/GB at 1 GB, $2.25/GB at 100 GB, and $1.40/GB at 3000 GB. Other vendors start near $4/GB and Bright Data nearer $8/GB pay-as-you-go. Datacenter proxies cost about $0.03 each and are close to useless here, because datacenter ranges are exactly what YouTube blocks. The free tier of 10 datacenter proxies is worth nothing.

A caption fetch moves tens of kilobytes, so 200 transcripts stay well under 1 GB. If a proxy is genuinely needed the bill is a few dollars. Buy residential or do not bother.

A consumer VPN is usually a downgrade. Its exit IPs are shared by thousands of users and are widely flagged, so you inherit someone else's reputation and rate budget.

## Measure, do not guess

1. Run 20 items at a deliberately slow pace, one request every 5 seconds. Confirm zero
   throttles. This proves the code works before you tune anything.
2. Halve the interval, run 20 more, record throttles per 20.
3. Repeat until throttles appear. The last clean interval is your ceiling.
4. Run production at 1.5 to 2 times that interval, jittered. Headroom absorbs the other
   traffic sharing your IP.

Count requests, not items. One "fetch a transcript" is often a watch-page request, a caption request, and a separate metadata call. Three requests per item behind a 1.5 s pacer is a real rate of one request every 0.5 s, three times what you configured. Put every outbound call through the same pacer, or your measured ceiling is fiction.

Log the pace, the throttle count and the final interval per run. That log is how the next run starts from knowledge instead of a guess.

## Official APIs: check, but do not assume

For YouTube captions there is no official route. The Data API `captions.download` method costs 200 quota units and requires permission to edit the video, so it cannot return caption text for videos you do not own. It returns 403 forbidden. Auto-caption scraping is the only option, which is why the pacing above matters. 