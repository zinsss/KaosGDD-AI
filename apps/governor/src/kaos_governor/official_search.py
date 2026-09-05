from __future__ import annotations

from dataclasses import dataclass
import html
from html.parser import HTMLParser
import json
import re
import urllib.parse
import urllib.request
from typing import Callable, Iterable


MAX_SEARCH_PAGE_BYTES = 1_000_000
MAX_CANDIDATES_PER_SEARCH = 12
HIRA_INSURANCE_CRITERIA_URL = "https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrList.do?pgmid=HIRAA030069000400"
HIRA_INSURANCE_CRITERIA_POPUP_URL = "https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrPopup.do"
HEALTH_KR_SEARCH_PAGE_URL = "https://health.kr/searchDrug/search_total_result.asp"
HEALTH_KR_DRUG_SEARCH_URL = "https://health.kr/searchDrug/ajax/ajax_commonSearch.asp"
HEALTH_KR_DRUG_DETAIL_URL = "https://health.kr/searchDrug/ajax/ajax_result_drug.asp"
HEALTH_KR_DRUG_PAGE_URL = "https://health.kr/searchDrug/result_drug.asp"
AAFP_SITEMAP_URL = "https://www.aafp.org/sitemap.xml"


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
    OfficialSearchSite("약학정보원", ("health.kr", "www.health.kr")),
    OfficialSearchSite("국민건강보험공단", ("nhis.or.kr", "www.nhis.or.kr")),
    OfficialSearchSite("노인장기요양보험", ("longtermcare.or.kr", "www.longtermcare.or.kr")),
    OfficialSearchSite("국가정신건강정보포털", ("mentalhealth.go.kr", "www.mentalhealth.go.kr"), "https://www.mentalhealth.go.kr/portal/search/search.do?query={query}"),
    OfficialSearchSite("국립보건연구원", ("nih.go.kr", "www.nih.go.kr")),
    OfficialSearchSite("감염병포털", ("dportal.kdca.go.kr",)),
    OfficialSearchSite("예방접종도우미", ("nip.kdca.go.kr",)),
    OfficialSearchSite("국가건강정보포털", ("health.kdca.go.kr",)),
    OfficialSearchSite("식품안전나라", ("foodsafetykorea.go.kr", "www.foodsafetykorea.go.kr")),
    OfficialSearchSite(
        "의약품통합정보시스템",
        ("nedrug.mfds.go.kr",),
        "https://nedrug.mfds.go.kr/searchDrug?sort=&sortOrder=false&searchYn=true&page=1&searchDivision=detail&itemName={query}",
    ),
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
    OfficialSearchSite("PubMed", ("pubmed.ncbi.nlm.nih.gov",), "https://pubmed.ncbi.nlm.nih.gov/?term={query}"),
    OfficialSearchSite("AAO-HNS Guidelines", ("entnet.org", "www.entnet.org"), "https://www.entnet.org/?s={query}"),
    OfficialSearchSite("NIH NINDS", ("ninds.nih.gov", "www.ninds.nih.gov"), "https://www.ninds.nih.gov/search?search={query}"),
    OfficialSearchSite("NICE CKS", ("cks.nice.org.uk",), "https://cks.nice.org.uk/search/?q={query}"),
    OfficialSearchSite("American Academy of Sleep Medicine", ("aasm.org", "www.aasm.org"), "https://aasm.org/?s={query}"),
    OfficialSearchSite("American Family Physician", ("aafp.org", "www.aafp.org")),
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


def looks_like_treatment_options_query(query: str, alternate_queries: Iterable[str] = ()) -> bool:
    return _looks_like_treatment_options_query([query, *alternate_queries])


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
    health_kr_queries: list[str] = []
    health_kr_candidates: list[OfficialSearchCandidate] = []
    if _looks_like_drug_lookup_query(queries):
        health_kr_queries, health_kr_candidates = _health_kr_drug_queries_and_candidates(queries, urlopen=urlopen)
    queries = _expanded_queries(_unique_queries([*queries, *health_kr_queries]))
    preferred = _preferred_hosts(preferred_domains)
    if _looks_like_medicine_benefit_query(queries):
        preferred.update({"hira.or.kr", "www.hira.or.kr"})
    if _looks_like_treatment_options_query(queries):
        preferred.update(
            {
                "health.kdca.go.kr",
                "mentalhealth.go.kr",
                "www.mentalhealth.go.kr",
                "pubmed.ncbi.nlm.nih.gov",
                "www.entnet.org",
                "cks.nice.org.uk",
                "www.ninds.nih.gov",
                "www.aafp.org",
            }
        )
    treatment_query = _looks_like_treatment_options_query(queries)
    sites = _ordered_sites(preferred)
    candidates: list[OfficialSearchCandidate] = list(health_kr_candidates)
    if treatment_query:
        candidates.extend(_aafp_sitemap_candidates(queries, preferred=preferred, urlopen=urlopen))
    hira_candidates = _hira_insurance_criteria_candidates(queries, preferred=preferred, urlopen=urlopen)
    if hira_candidates and any(host in preferred for host in ("hira.or.kr", "www.hira.or.kr")):
        return _ranked_unique_candidates(hira_candidates)[:limit]
    candidates.extend(hira_candidates)
    for index, site in enumerate(sites):
        if not site.search_url:
            continue
        site_count = 0
        site_limit = max(4, min(MAX_CANDIDATES_PER_SEARCH, limit))
        per_query_limit = max(2, site_limit // 2)
        for search_query in queries[:4 if treatment_query else 2]:
            query_count = 0
            page_url = site.search_url.format(query=urllib.parse.quote(search_query))
            for link in _search_page_links(page_url, urlopen=urlopen):
                candidate = _candidate_from_link(link, site=site, queries=queries, preferred=preferred)
                if candidate:
                    candidates.append(candidate)
                    site_count += 1
                    query_count += 1
                if site_count >= site_limit or query_count >= per_query_limit:
                    break
            if site_count >= site_limit:
                break
        if len(candidates) >= limit * 5 and not _has_remaining_preferred_site(sites[index + 1 :], preferred):
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
        "bppv": ("benign paroxysmal positional vertigo", "BPPV treatment guideline", "이석증", "양성돌발체위현훈"),
        "이석증": ("BPPV", "benign paroxysmal positional vertigo", "양성돌발체위현훈"),
        "양성돌발체위현훈": ("BPPV", "benign paroxysmal positional vertigo", "이석증"),
        "양성돌발성체위현훈": ("BPPV", "benign paroxysmal positional vertigo", "이석증"),
        "하지불안증후군": ("restless legs syndrome", "RLS", "restless legs syndrome treatment guideline"),
        "restless legs syndrome": ("RLS", "하지불안증후군", "restless legs syndrome treatment guideline"),
        "rls": ("restless legs syndrome", "restless legs syndrome treatment guideline", "하지불안증후군"),
    }
    for needle, replacements in aliases.items():
        if needle in joined:
            expanded.extend(replacements)
    if _looks_like_treatment_options_query(expanded):
        expanded.extend(_treatment_query_variants(expanded))
    return _unique_queries(expanded)


def _treatment_query_variants(queries: Iterable[str]) -> list[str]:
    variants: list[str] = []
    for query in list(queries)[:6]:
        base = re.sub(
            r"(치료\s*옵션|치료옵션|치료\s*방법|치료방법|치료법|치료|처치|관리|진료지침|가이드라인|권고|options?|treatments?|therap(?:y|ies)|management|guidelines?|clinical practice)",
            " ",
            str(query or ""),
            flags=re.I,
        )
        base = " ".join(base.replace("/", " ").replace(",", " ").split()).strip(" -·")
        if len(base) < 2:
            continue
        if re.search(r"[가-힣]", base):
            variants.extend((f"{base} 진료지침", f"{base} 치료 지침", f"{base} 치료"))
        if re.search(r"[A-Za-z]", base):
            variants.extend((
                f"{base} clinical practice guideline",
                f"{base} treatment guideline",
                f"{base} management guideline",
            ))
    return variants


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


def _looks_like_medicine_benefit_query(queries: Iterable[str]) -> bool:
    text = " ".join(str(query or "") for query in queries).casefold()
    benefit_words = ("급여기준", "요양급여", "보험인정", "본인부담", "투여조건", "삭감", "약제급여", "급여목록")
    medicine_words = ("정", "캡슐", "시럽", "주사", "경구", "mg", "성분", "약제", "투여", "almotriptan", "choline", "triptan")
    return any(word in text for word in benefit_words) and any(word.casefold() in text for word in medicine_words)


def _looks_like_drug_lookup_query(queries: Iterable[str]) -> bool:
    text = " ".join(str(query or "") for query in queries).casefold()
    lookup_words = (
        "급여기준",
        "요양급여",
        "보험인정",
        "본인부담",
        "투여조건",
        "삭감",
        "약제급여",
        "급여목록",
        "성분",
        "제품정보",
        "허가사항",
        "약품",
        "약제",
        "의약품",
        "mg",
    )
    dosage_form_words = ("정", "캡슐", "시럽", "주사", "점안", "연고", "크림", "패취", "액")
    known_ingredient_words = ("almotriptan", "triptan", "choline alfoscerate", "gabapentin", "pregabalin", "pramipexole")
    return (
        any(word in text for word in lookup_words)
        or any(word.casefold() in text for word in known_ingredient_words)
        or (any(word in text for word in dosage_form_words) and any(word in text for word in ("급여", "허가", "성분", "약")))
    )


def _looks_like_treatment_options_query(queries: Iterable[str]) -> bool:
    text = " ".join(str(query or "") for query in queries).casefold()
    treatment_words = (
        "치료",
        "치료옵션",
        "치료 옵션",
        "치료법",
        "치료방법",
        "처치",
        "관리",
        "management",
        "treatment",
        "therapy",
        "guideline",
        "가이드라인",
        "진료지침",
        "권고",
    )
    benefit_only_words = ("급여기준", "요양급여", "본인부담", "삭감", "급여목록")
    return any(word in text for word in treatment_words) and not (
        any(word in text for word in benefit_only_words) and "치료" not in text
    )


def _ordered_sites(preferred: set[str]) -> list[OfficialSearchSite]:
    with_search = [site for site in OFFICIAL_HEALTH_SITES if site.search_url]
    return sorted(with_search, key=lambda site: 0 if any(host in preferred for host in site.hosts) else 1)


def _has_remaining_preferred_site(sites: Iterable[OfficialSearchSite], preferred: set[str]) -> bool:
    return any(any(host in preferred for host in site.hosts) for site in sites)


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


def _health_kr_drug_queries_and_candidates(
    queries: list[str],
    *,
    urlopen: Callable = urllib.request.urlopen,
) -> tuple[list[str], list[OfficialSearchCandidate]]:
    discovered_queries: list[str] = []
    candidates: list[OfficialSearchCandidate] = []
    searched_terms: set[str] = set()
    for query in queries[:4]:
        for search_term in _health_kr_search_terms(query):
            if search_term.casefold() in searched_terms:
                continue
            searched_terms.add(search_term.casefold())
            results = _health_kr_search_drugs(search_term, urlopen=urlopen)
            for result in results[:3]:
                drug_code = str(result.get("drug_code") or "").strip()
                drug_name = str(result.get("drug_name") or "").strip()
                if not drug_code or not drug_name:
                    continue
                details = _health_kr_drug_detail(drug_code, urlopen=urlopen)
                fields = {**result, **details}
                terms = _health_kr_terms_from_drug(fields)
                discovered_queries.extend(terms)
                url = f"{HEALTH_KR_DRUG_PAGE_URL}?{urllib.parse.urlencode({'drug_cd': drug_code})}"
                candidate_title = _health_kr_candidate_title(fields)
                score = _candidate_score(candidate_title, url, [*queries, *terms]) + 4
                candidates.append(
                    OfficialSearchCandidate(
                        title=candidate_title[:200],
                        url=url[:800],
                        host="health.kr",
                        score=score,
                        source="약학정보원 약품정보",
                    )
                )
            if discovered_queries:
                break
    return _unique_queries(discovered_queries), _ranked_unique_candidates(candidates)[:MAX_CANDIDATES_PER_SEARCH]


def _aafp_sitemap_candidates(
    queries: list[str],
    *,
    preferred: set[str],
    urlopen: Callable = urllib.request.urlopen,
) -> list[OfficialSearchCandidate]:
    request = urllib.request.Request(
        AAFP_SITEMAP_URL,
        headers={
            "Accept": "application/xml, text/xml, text/plain;q=0.9",
            "User-Agent": "KaosGovernor/official-search",
        },
    )
    try:
        with urlopen(request, timeout=7) as response:
            text = _decode(response.read(MAX_SEARCH_PAGE_BYTES * 5), response.headers.get("Content-Type", ""))
    except Exception:
        return []
    candidates: list[OfficialSearchCandidate] = []
    for match in re.finditer(r"<loc>\s*(?P<url>https://www\.aafp\.org/[^<]+)\s*</loc>", text, flags=re.I):
        url = html.unescape(match.group("url")).strip()
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path.lower()
        if not (
            path.startswith("/afp/topics/")
            or path.startswith("/tag/collection/fpe-topics/")
            or path.startswith("/tag/subject/patient-care/")
        ):
            continue
        title = _aafp_title_from_url(url)
        topic_score = _aafp_topic_match_score(title, url, queries)
        if topic_score <= 0:
            continue
        score = _candidate_score(title, url, queries) + 12 + topic_score
        if any(host in preferred for host in ("aafp.org", "www.aafp.org")):
            score += 18
        if score <= 5:
            continue
        candidates.append(
            OfficialSearchCandidate(
                title=title[:200],
                url=url[:800],
                host="www.aafp.org",
                score=score,
                source="American Family Physician",
            )
        )
        if len(candidates) >= MAX_CANDIDATES_PER_SEARCH:
            break
    return _ranked_unique_candidates(candidates)


def _aafp_title_from_url(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.strip("/")
    slug = path.rsplit("/", 1)[-1]
    words = [word for word in re.split(r"[-_]+", slug) if word]
    if not words:
        return "American Family Physician"
    return "American Family Physician: " + " ".join(word.upper() if word.lower() in {"copd", "hiv"} else word.capitalize() for word in words)


def _aafp_topic_match_score(title: str, url: str, queries: list[str]) -> int:
    haystack = f"{title} {urllib.parse.unquote(url)}".casefold()
    ignored = {
        "option",
        "options",
        "treatment",
        "treatments",
        "therapy",
        "therapies",
        "management",
        "guideline",
        "guidelines",
        "clinical",
        "practice",
        "치료",
        "옵션",
        "방법",
        "진료지침",
        "가이드라인",
        "관리",
    }
    tokens: list[str] = []
    for query in queries:
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", query.casefold()):
            if token not in ignored:
                tokens.append(token)
    unique_tokens = list(dict.fromkeys(tokens))
    matches = [token for token in unique_tokens if token in haystack]
    return len(matches) * 10


def _health_kr_search_terms(query: str) -> list[str]:
    compact = " ".join(str(query or "").split())
    cleaned = re.sub(
        r"(요양급여기준|급여기준|급여목록|보험기준|급여|보험|처방|기준|약제|투여|본인부담|대상|조건|수량|기간|확인|요약|알려줘|찾아줘)",
        " ",
        compact,
        flags=re.I,
    )
    terms = [compact, " ".join(cleaned.split())]
    terms.extend(re.findall(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣.+-]{1,}", cleaned))
    return _unique_queries(terms)


def _health_kr_search_drugs(search_term: str, *, urlopen: Callable = urllib.request.urlopen) -> list[dict[str, object]]:
    encoded = urllib.parse.quote(search_term)
    body = urllib.parse.urlencode({"search_word": search_term, "search_flag": "all"}).encode("utf-8")
    page_request = urllib.request.Request(
        HEALTH_KR_SEARCH_PAGE_URL,
        data=body,
        method="POST",
        headers={
            "Accept": "text/html, text/plain;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (KaosGovernor/official-search)",
        },
    )
    try:
        with urlopen(page_request, timeout=7) as response:
            page = _decode(response.read(MAX_SEARCH_PAGE_BYTES), response.headers.get("Content-Type", ""))
            cookies = _cookie_header(response.headers)
    except Exception:
        return []
    token_match = re.search(r"window\.csrfToken\s*=\s*\"([^\"]+)\"", page)
    token = token_match.group(1) if token_match else ""
    if not token:
        return []
    ajax_request = urllib.request.Request(
        f"{HEALTH_KR_DRUG_SEARCH_URL}?search_word={encoded}&csrf_token={urllib.parse.quote(token)}&search_flag=all",
        data=urllib.parse.urlencode({"csrf_token": token}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": HEALTH_KR_SEARCH_PAGE_URL,
            "User-Agent": "Mozilla/5.0 (KaosGovernor/official-search)",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": token,
            **({"Cookie": cookies} if cookies else {}),
        },
    )
    try:
        with urlopen(ajax_request, timeout=7) as response:
            payload = _decode(response.read(MAX_SEARCH_PAGE_BYTES), response.headers.get("Content-Type", ""))
    except Exception:
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _health_kr_drug_detail(drug_code: str, *, urlopen: Callable = urllib.request.urlopen) -> dict[str, object]:
    request = urllib.request.Request(
        f"{HEALTH_KR_DRUG_DETAIL_URL}?{urllib.parse.urlencode({'drug_cd': drug_code})}",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": "Mozilla/5.0 (KaosGovernor/official-search)",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = _decode(response.read(MAX_SEARCH_PAGE_BYTES), response.headers.get("Content-Type", ""))
    except Exception:
        return {}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _health_kr_terms_from_drug(fields: dict[str, object]) -> list[str]:
    terms: list[str] = []
    for key in ("drug_name", "drug_enm", "list_sunb_name", "ingr_mg", "sunb", "effect"):
        terms.extend(_health_kr_text_terms(str(fields.get(key) or "")))
    kpic_categories = _health_kr_kpic_terms(str(fields.get("kpic_category") or ""))
    terms.extend(kpic_categories)
    if str(fields.get("cls_code_num") or "") == "114" or str(fields.get("cls_code") or "") == "114":
        terms.append("해열 진통 소염제")
    joined = " ".join(terms)
    if "편두통" in joined or "almotriptan" in joined.casefold():
        terms.append("편두통 치료제")
    return _unique_queries(terms)


def _health_kr_text_terms(value: str) -> list[str]:
    text = _strip_tags(html.unescape(value)).replace("\u3000", " ")
    terms: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z -]{2,}|[가-힣][가-힣·]{1,}", text):
        token = " ".join(raw.split()).strip(" -·")
        if not token:
            continue
        lowered = token.casefold()
        if lowered in {"br", "mg", "tab", "tablet"}:
            continue
        if re.fullmatch(r"[A-Za-z]+", token) and len(token) <= 3:
            continue
        terms.append(token)
        if lowered.endswith(" malate"):
            terms.append(token[: -len(" malate")].strip())
        if token.endswith("말산염"):
            terms.append(token[: -len("말산염")].strip())
    return terms


def _health_kr_kpic_terms(value: str) -> list[str]:
    text = _strip_tags(html.unescape(value)).replace("\u3000", " ")
    return [item.strip() for item in re.split(r">\s*|\n+", text) if item.strip()]


def _health_kr_candidate_title(fields: dict[str, object]) -> str:
    drug_name = " ".join(str(fields.get("drug_name") or "").split())
    ingredient = " ".join(_strip_tags(str(fields.get("sunb") or fields.get("list_sunb_name") or "")).split())
    if ingredient:
        return f"{drug_name} // {ingredient}"
    return drug_name or "약학정보원 약품정보"


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _cookie_header(headers: object) -> str:
    values: list[str] = []
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = [str(value) for value in get_all("Set-Cookie") or []]
    if not values:
        value = getattr(headers, "get", lambda *_args: "")("Set-Cookie", "")
        if value:
            values = [str(value)]
    cookies = []
    for value in values:
        first = value.split(";", 1)[0].strip()
        if first:
            cookies.append(first)
    return "; ".join(cookies)


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
    if lowered.rstrip("/") in {
        "https://pubmed.ncbi.nlm.nih.gov",
        "http://pubmed.ncbi.nlm.nih.gov",
        "https://www.entnet.org",
        "http://www.entnet.org",
        "https://www.aafp.org",
        "http://www.aafp.org",
    }:
        return True
    noise = (
        "javascript:",
        "/login",
        "/member",
        "/privacy",
        "/copyright",
        "/sitemap",
        "/account/",
        "/advanced",
        "/clipboard",
        "/events/",
        "/help/",
        "/join-us/",
        "/myncbi",
        "/search.do",
        "/search/",
        "/search.es",
        "/menu.es",
        "entnet.org/?s=",
        "saml_user_login",
        "pubmed.ncbi.nlm.nih.gov/?term=",
        "aasm.org/?s=",
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
        "본문바로가기",
        "메뉴 바로가기",
        "메뉴바로가기",
        "skip to main page content",
        "skip to main content",
        "skip to content",
        "main content",
        "account settings",
        "annual meeting",
        "advanced",
        "clipboard",
        "dashboard",
        "user guide",
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
    if any(kind in text for kind in ("치료", "management", "treatment", "guideline", "practice guideline", "clinical practice", "diagnosis", "진료지침", "권고")):
        score += 5
    if any(kind in text for kind in ("clinical practice guideline", "american academy", "american family physician", "aafp", "aasm", "aao-hns", "entnet", "practice guideline summary", "nice cks", "nih")):
        score += 8
    if "american family physician" in text or "aafp" in text:
        score += 10
    if "american academy of sleep medicine" in text:
        score += 12
    if "american academy of otolaryngology" in text or "head and neck surgery" in text:
        score += 12
    if text.startswith("clinical practice guideline") or " clinical practice guideline:" in text:
        score += 16
    if "effective diagnosis and treatment" in text or "guideline of diagnosis and treatment" in text:
        score += 8
    if "plain language summary" in text:
        score += 4
    if "guideline adherence" in text or "barriers and facilitators" in text:
        score -= 10
    if "characteristics of assessment and treatment" in text:
        score -= 8
    if "observational study" in text or "atypical" in text:
        score -= 6
    if "poor effect" in text:
        score -= 10
    if any(host in text for host in ("pubmed.ncbi.nlm.nih.gov", "entnet.org", "cks.nice.org.uk", "ninds.nih.gov", "aafp.org", "health.kdca.go.kr", "mentalhealth.go.kr")):
        score += 2
    return score


def _ranked_unique_candidates(candidates: Iterable[OfficialSearchCandidate]) -> list[OfficialSearchCandidate]:
    best: dict[str, OfficialSearchCandidate] = {}
    for candidate in candidates:
        previous = best.get(candidate.url)
        if previous is None or candidate.score > previous.score:
            best[candidate.url] = candidate
    return sorted(best.values(), key=lambda item: (-item.score, item.host, item.title))
