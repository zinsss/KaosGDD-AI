from __future__ import annotations

from dataclasses import dataclass
import html
from html.parser import HTMLParser
import re
import urllib.parse
import urllib.request
from typing import Callable, Iterable


MAX_SEARCH_PAGE_BYTES = 1_000_000
MAX_CANDIDATES_PER_SEARCH = 12
HIRA_INSURANCE_CRITERIA_URL = "https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrList.do?pgmid=HIRAA030069000400"
HIRA_INSURANCE_CRITERIA_POPUP_URL = "https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrPopup.do"


@dataclass(frozen=True)
class OfficialSearchSite:
    name: str
    hosts: tuple[str, ...]
    search_url: str = ""


@dataclass(frozen=True)
class OfficialSearchCandidate:
    title: str
    url: str
    host: str
    score: int
    source: str


OFFICIAL_HEALTH_SITES: tuple[OfficialSearchSite, ...] = (
    OfficialSearchSite("보건복지부", ("mohw.go.kr", "www.mohw.go.kr"), "https://www.mohw.go.kr/search.es?mid=a10503000000&act=view&kwd={query}"),
    OfficialSearchSite("질병관리청", ("kdca.go.kr", "www.kdca.go.kr"), "https://www.kdca.go.kr/search.do?kwd={query}&category=TOTAL"),
    OfficialSearchSite("식품의약품안전처", ("mfds.go.kr", "www.mfds.go.kr"), "https://www.mfds.go.kr/search/search.do?searchWord={query}"),
    OfficialSearchSite("건강보험심사평가원", ("hira.or.kr", "www.hira.or.kr")),
    OfficialSearchSite("국민건강보험공단", ("nhis.or.kr", "www.nhis.or.kr")),
    OfficialSearchSite("노인장기요양보험", ("longtermcare.or.kr", "www.longtermcare.or.kr")),
    OfficialSearchSite("국립보건연구원", ("nih.go.kr", "www.nih.go.kr")),
    OfficialSearchSite("감염병포털", ("dportal.kdca.go.kr",)),
    OfficialSearchSite("예방접종도우미", ("nip.kdca.go.kr",)),
    OfficialSearchSite("국가건강정보포털", ("health.kdca.go.kr",)),
    OfficialSearchSite("식품안전나라", ("foodsafetykorea.go.kr", "www.foodsafetykorea.go.kr")),
    OfficialSearchSite("의약품통합정보시스템", ("nedrug.mfds.go.kr",)),
    OfficialSearchSite("의료기기정보포털", ("udiportal.mfds.go.kr",)),
    OfficialSearchSite("식품의약품안전평가원", ("nifds.go.kr", "www.nifds.go.kr")),
    OfficialSearchSite("한국의약품안전관리원", ("drugsafe.or.kr", "www.drugsafe.or.kr")),
    OfficialSearchSite("한국의료기기안전정보원", ("nids.or.kr", "www.nids.or.kr")),
    OfficialSearchSite("한국희귀필수의약품센터", ("kodc.or.kr", "www.kodc.or.kr")),
    OfficialSearchSite("마약류통합관리시스템", ("nims.or.kr", "www.nims.or.kr")),
    OfficialSearchSite("국립중앙의료원", ("nmc.or.kr", "www.nmc.or.kr")),
    OfficialSearchSite("국립암센터", ("ncc.re.kr", "www.ncc.re.kr")),
    OfficialSearchSite("한국보건의료연구원", ("neca.re.kr", "www.neca.re.kr")),
    OfficialSearchSite("한국건강증진개발원", ("khealth.or.kr", "www.khealth.or.kr")),
    OfficialSearchSite("한국보건산업진흥원", ("khidi.or.kr", "www.khidi.or.kr")),
    OfficialSearchSite("한국보건복지인재원", ("kohi.or.kr", "www.kohi.or.kr")),
    OfficialSearchSite("한국보건의료정보원", ("k-his.or.kr", "www.k-his.or.kr")),
    OfficialSearchSite("한국의료분쟁조정중재원", ("k-medi.or.kr", "www.k-medi.or.kr")),
    OfficialSearchSite("한국보건의료인국가시험원", ("kuksiwon.or.kr", "www.kuksiwon.or.kr")),
    OfficialSearchSite("한국장기조직기증원", ("koda1458.kr", "www.koda1458.kr")),
    OfficialSearchSite("의료기관평가인증원", ("koiha.kr", "www.koiha.kr")),
)


OFFICIAL_HEALTH_ALLOWED_HOSTS = frozenset(host for site in OFFICIAL_HEALTH_SITES for host in site.hosts)


class SearchLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        href = values.get("href", "").strip()
        if href:
            self._href = urllib.parse.urljoin(self.base_url, href)
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join("".join(self._text).split())
        self.links.append({"url": self._href, "title": title})
        self._href = ""
        self._text = []


def allowed_official_health_hosts() -> list[str]:
    return sorted(OFFICIAL_HEALTH_ALLOWED_HOSTS)


def is_allowed_official_health_host(host: str) -> bool:
    normalized = host.lower().rstrip(".")
    return any(normalized == allowed or normalized.endswith(f".{allowed}") for allowed in OFFICIAL_HEALTH_ALLOWED_HOSTS)


def official_health_search_candidates(
    query: str,
    *,
    alternate_queries: Iterable[str] = (),
    preferred_domains: Iterable[str] = (),
    limit: int = 8,
    urlopen: Callable = urllib.request.urlopen,
) -> list[OfficialSearchCandidate]:
    queries = _expanded_queries(_unique_queries([query, *alternate_queries]))
    if not queries:
        return []
    preferred = _preferred_hosts(preferred_domains)
    sites = _ordered_sites(preferred)
    candidates: list[OfficialSearchCandidate] = []
    hira_candidates = _hira_insurance_criteria_candidates(queries, preferred=preferred, urlopen=urlopen)
    if hira_candidates and any(host in preferred for host in ("hira.or.kr", "www.hira.or.kr")):
        return _ranked_unique_candidates(hira_candidates)[:limit]
    candidates.extend(hira_candidates)
    for site in sites:
        if not site.search_url:
            continue
        for search_query in queries[:2]:
            page_url = site.search_url.format(query=urllib.parse.quote(search_query))
            for link in _search_page_links(page_url, urlopen=urlopen):
                candidate = _candidate_from_link(link, site=site, queries=queries, preferred=preferred)
                if candidate:
                    candidates.append(candidate)
                if len(candidates) >= limit * 5:
                    break
            if len(candidates) >= limit * 5:
                break
    return _ranked_unique_candidates(candidates)[:limit]


def _unique_queries(values: Iterable[str]) -> list[str]:
    selected: list[str] = []
    for value in values:
        query = " ".join(str(value or "").split())
        if query and query not in selected:
            selected.append(query[:200])
    return selected


def _expanded_queries(queries: list[str]) -> list[str]:
    expanded = list(queries)
    joined = " ".join(queries).casefold()
    aliases = {
        "알모그란": ("Almotriptan", "편두통 치료제"),
        "알모트립탄": ("Almotriptan", "편두통 치료제"),
        "almotriptan": ("편두통 치료제",),
        "글리아티린": ("choline alfoscerate", "콜린알포세레이트"),
        "콜린알포세레이트": ("choline alfoscerate",),
        "choline alfoscerate": ("콜린알포세레이트",),
        "수마트립탄": ("Sumatriptan", "편두통 치료제"),
        "이미그란": ("Sumatriptan", "편두통 치료제"),
        "졸미트립탄": ("Zolmitriptan", "편두통 치료제"),
        "조믹": ("Zolmitriptan", "편두통 치료제"),
        "나라트립탄": ("Naratriptan", "편두통 치료제"),
        "나라믹": ("Naratriptan", "편두통 치료제"),
        "프로바트립탄": ("Frovatriptan", "편두통 치료제"),
        "미가드": ("Frovatriptan", "편두통 치료제"),
        "수벡스": ("Sumatriptan Naproxen", "편두통 치료제"),
    }
    for needle, replacements in aliases.items():
        if needle in joined:
            expanded.extend(replacements)
    return _unique_queries(expanded)


def _preferred_hosts(values: Iterable[str]) -> set[str]:
    hosts: set[str] = set()
    for value in values:
        raw = str(value or "").strip().lower()
        if not raw:
            continue
        host = re.sub(r"^https?://", "", raw).split("/", 1)[0].rstrip(".")
        if is_allowed_official_health_host(host):
            hosts.add(host)
    return hosts


def _ordered_sites(preferred: set[str]) -> list[OfficialSearchSite]:
    with_search = [site for site in OFFICIAL_HEALTH_SITES if site.search_url]
    return sorted(with_search, key=lambda site: 0 if any(host in preferred for host in site.hosts) else 1)


def _hira_insurance_criteria_candidates(
    queries: list[str],
    *,
    preferred: set[str],
    urlopen: Callable = urllib.request.urlopen,
) -> list[OfficialSearchCandidate]:
    candidates: list[OfficialSearchCandidate] = []
    for search_query in queries[:6]:
        request = urllib.request.Request(
            HIRA_INSURANCE_CRITERIA_URL,
            data=urllib.parse.urlencode(
                {
                    "pageIndex": "1",
                    "tabGbn": "01",
                    "searchYn": "Y",
                    "decIteTpCd": "01",
                    "recordCountPerPage": "10",
                    "searchCondition": "TXTALL",
                    "searchKeyword": search_query,
                    "searchWord": search_query,
                    "startDt": "",
                    "endDt": "",
                    "seqListYn": "N",
                    "seqList": "",
                    "divRngCdSc": "",
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "text/html, text/plain;q=0.9",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "KaosGovernor/official-search",
            },
        )
        try:
            with urlopen(request, timeout=7) as response:
                raw = response.read(MAX_SEARCH_PAGE_BYTES)
                content_type = response.headers.get("Content-Type", "")
        except Exception:
            continue
        text = _decode(raw, content_type)
        for match in re.finditer(
            r"viewInsuAdtCrtr\(\s*\d+\s*,\s*'(?P<date>\d{8})'\s*,\s*'(?P<sno>[^']+)'\s*,\s*'(?P<reg>[^']+)'\s*,\s*'\d+'\s*\).*?title=\"(?P<title>[^\"]+)\"",
            text,
            flags=re.S,
        ):
            params = urllib.parse.urlencode(
                {
                    "mtgHmeDd": match.group("date"),
                    "mtgMtrRegSno": match.group("reg"),
                    "sno": match.group("sno"),
                }
            )
            title = " ".join(html.unescape(match.group("title")).replace("새창으로 열기", "").split())
            url = f"{HIRA_INSURANCE_CRITERIA_POPUP_URL}?{params}"
            score = _candidate_score(title, url, queries) + 15 + _hira_criteria_recency_score(match.group("date"))
            if any(host in preferred for host in ("hira.or.kr", "www.hira.or.kr")):
                score += 8
            candidates.append(
                OfficialSearchCandidate(
                    title=title[:200],
                    url=url[:800],
                    host="www.hira.or.kr",
                    score=score,
                    source="건강보험심사평가원 보험인정기준",
                )
            )
            if len(candidates) >= MAX_CANDIDATES_PER_SEARCH:
                return candidates
    return candidates


def _search_page_links(search_url: str, *, urlopen: Callable = urllib.request.urlopen) -> list[dict[str, str]]:
    request = urllib.request.Request(
        search_url,
        headers={
            "Accept": "text/html, text/plain;q=0.9",
            "User-Agent": "KaosGovernor/official-search",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read(MAX_SEARCH_PAGE_BYTES)
            content_type = response.headers.get("Content-Type", "")
    except Exception:
        return []
    parser = SearchLinkParser(search_url)
    try:
        parser.feed(_decode(raw, content_type))
    except Exception:
        return []
    return parser.links


def _decode(raw: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type, flags=re.I)
    charset = match.group(1) if match else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _candidate_from_link(
    link: dict[str, str],
    *,
    site: OfficialSearchSite,
    queries: list[str],
    preferred: set[str],
) -> OfficialSearchCandidate | None:
    parsed = urllib.parse.urlsplit(link.get("url") or "")
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower().rstrip(".")
    if not is_allowed_official_health_host(host):
        return None
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    if _looks_like_noise_url(url):
        return None
    title = " ".join((link.get("title") or "").split()) or host
    if _looks_like_noise_title(title):
        return None
    score = _candidate_score(title, url, queries)
    if any(host == item or host.endswith(f".{item}") for item in preferred):
        score += 8
    if any(host == item or host.endswith(f".{item}") for item in site.hosts):
        score += 3
    if score <= 0:
        return None
    return OfficialSearchCandidate(title=title[:200], url=url[:800], host=host, score=score, source=site.name)


def _looks_like_noise_url(url: str) -> bool:
    lowered = url.lower()
    noise = (
        "javascript:",
        "/login",
        "/member",
        "/privacy",
        "/copyright",
        "/sitemap",
        "/search.do",
        "/search/",
        "/search.es",
        "/menu.es",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "blog.naver.com",
        "twitter.com",
    )
    return any(item in lowered for item in noise)


def _looks_like_noise_title(title: str) -> bool:
    normalized = " ".join(str(title or "").split()).casefold()
    return normalized in {
        "본문 바로가기",
        "본문으로 바로가기",
        "메뉴 바로가기",
        "통합검색",
        "로그인",
        "회원가입",
        "english",
        "공공누리",
        "정책실명제",
        "전체메뉴로 이동",
        "보건복지부 자료실",
        "기초연금",
    }


def _hira_criteria_recency_score(date_value: str) -> int:
    try:
        date_number = int(date_value)
    except ValueError:
        return 0
    if date_number >= 20240101:
        return 6
    if date_number >= 20200101:
        return 3
    return 0


def _candidate_score(title: str, url: str, queries: list[str]) -> int:
    text = f"{title} {urllib.parse.unquote(url)}".casefold()
    tokens = []
    for query in queries:
        tokens.extend(re.findall(r"[0-9A-Za-z가-힣]{2,}", query.casefold()))
    unique_tokens = list(dict.fromkeys(tokens))
    score = sum(5 for token in unique_tokens if token in text)
    if any(kind in text for kind in ("보도자료", "고시", "지침", "정책", "공고", "faq", "pdf", "자료")):
        score += 4
    return score


def _ranked_unique_candidates(candidates: Iterable[OfficialSearchCandidate]) -> list[OfficialSearchCandidate]:
    best: dict[str, OfficialSearchCandidate] = {}
    for candidate in candidates:
        previous = best.get(candidate.url)
        if previous is None or candidate.score > previous.score:
            best[candidate.url] = candidate
    return sorted(best.values(), key=lambda item: (-item.score, item.host, item.title))
