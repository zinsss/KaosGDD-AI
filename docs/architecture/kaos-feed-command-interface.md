# Kaos Feed Command Interface

Decision date: 2026-09-03

Status: accepted as target design; implementation not started in this document.

## Decision

The personal `kaosgdd.net` PWA should evolve from separate pages into a
command-feed console. The feed may look conversational, but its main control
surface is openable cards, menus, buttons, and forms rather than a plain chat
box.

Prompt-driven Brain workflows are called **AI Tasks**. They are not throwaway
chat turns: every run creates an archived task record with the prompt, source
material, preview output, confirmation state, final result, timestamps, and
error/rollback metadata.

This replaces the assumption that Discord or Telegram must be the main
communication gateway. Discord may remain as a fallback `#brain` topic during
transition, but daily Kaos control should live in the PWA.

## Interface Model

```text
Kaos Feed
  timeline of system/domain cards
  openable command menus
  structured confirmation cards
  optional short text input for Ask Kaos
```

The key rule is:

```text
Chat is the container.
Cards and buttons are the control surface.
```

Examples:

```text
Morning Digest card
  [ Open Agenda ] [ Weather ] [ Tasks ] [ Documents ]

Fax Received card
  [ Open PDF ] [ Send To Documents ] [ Acknowledge ]

Document Inbox card
  [ Review Metadata ] [ Apply ] [ Open Paperless ]

System Attention card
  [ Full Status ] [ Plan Update ] [ Open #brain fallback ]

Task Proposal card
  [ Create ] [ Edit ] [ Cancel ]
```

The feed should not force every operation through free text. Most daily actions
should remain deterministic button/form operations.

## Ownership

```text
PWA Kaos Feed
  renders cards, buttons, forms, receipts, and deep links

KaosGateway / Governor API
  accepts structured UI commands and returns structured card data

KaosGovernor
  validates actor, scope, policy, confirmation, idempotency, and audit

KaosBrain
  interprets ambiguous/free-text requests only when useful

KaosBrain-OpenAI
  optional OpenClaw/OpenAI provider for Brain reasoning

Domain adapters / MacBridge
  perform approved operations against Radicale, Memos, Paperless, HylaFAX,
  mail, system runbooks, iMessage, Calendar/Reminders mirrors, or macOS apps
```

## Request Flows

### Deterministic button action

```text
User taps [ Complete Task ]
  -> PWA sends structured task.complete request
  -> Governor validates and applies confirmation policy
  -> Governor calls task domain adapter
  -> PWA receives receipt card
```

No Brain or OpenAI call is required.

### Openable command menu

```text
User taps global +
  -> PWA opens page-aware command menu
  -> user picks Add Task / Upload Document / Send Fax / System Status
  -> PWA opens the exact command card/form
```

The menu is UI state only. It does not authorize mutations.

### Ambiguous natural-language request

```text
User types "move unfinished non-clinic tasks to Monday"
  -> PWA sends Ask Kaos request
  -> KaosBrain interprets and drafts structured proposal
  -> Governor validates proposal and decides confirmation requirement
  -> PWA renders confirmation card
  -> final approved write goes through Governor
```

### Alert deep link

```text
Pushover: "Fax received."
  -> tap opens exact PWA feed/card route
  -> card fetches current state from Governor
  -> user acts from structured buttons if needed
```

## Card Types

Initial useful cards:

- daily digest
- agenda/day summary
- AI Task prompt, preview, receipt, and archive cards
- task proposal
- task due/overdue
- document inbox item
- document metadata review
- fax received/sent/failed
- unread mail batch
- supplies quick list
- memo quick capture/result
- system status/maintenance
- MacBridge/iMessage triage, if added later

## AI Tasks

An AI Task is a durable command unit for work that benefits from language
understanding or document synthesis.

Examples:

```text
Official Doc -> Memo
  prompt: "26-27절기 국가 인플루엔자 접종 계획 찾아서 요약 메모 만들어줘"
  source policy: official domains only
  output: memo draft with links and checked date
  final write: confirmed save to Memos

Paperless Tag Assist
  prompt: implicit button action from a document
  source policy: current Paperless document + existing Paperless tags
  output: suggested existing tag names
  final write: confirmed Paperless metadata apply

Mail Summary
  prompt: "보건소 메일 요약해서 미처리만 보여줘"
  source policy: selected read-only mail folders
  output: summary/checklist card
  final write: none unless the user later confirms mark-read/delete/memo-save

Pill ID / Med Finder
  prompt: uploaded pill photos, normally front and back
  source policy: AI extracts visual fields; Governor verifies against trusted
    medicine-identification sources such as 약학정보원/식약처 data
  output: possible candidate medicines with confidence, source links, and
    extracted fields
  final write: none by default; user confirmation only archives the lookup
```

### AI Task lifecycle

```text
draft
  user enters prompt or opens a page-aware AI action
source_selection
  Governor collects allowed sources or asks the user to pick one
preview
  KaosBrain/KaosBrain-OpenAI drafts structured output
confirm
  PWA shows the proposed memo/event/tag/action before any write
applied | archived_without_apply | failed
  Governor stores the final receipt and archive entry
```

The archive is useful for recall and debugging:

- what the user asked
- which official/source URLs or internal records were used
- which AI/provider produced the draft
- what the preview said
- whether the user applied, edited, cancelled, or the task failed
- the resulting Memos/Paperless/Radicale/mail/fax record id when a write was
  confirmed

The archive is not an authority for domain state. Memos, Paperless, Radicale,
mail, and fax remain the source of truth. AI Task archives are receipts and
work history.

### Pill ID / Med Finder plan

Pill identification is a planned AI Task for reducing manual lookup friction,
not for making a medical decision. The PWA should present it as a candidate
finder.

Workflow:

```text
upload/take pill photos
  require front and back when possible
vision extraction preview
  imprint, side A/B, color, shape, score line, coating, approximate size
user correction
  imprint and visual fields stay editable before search
verified lookup
  Governor searches trusted medicine databases using the corrected fields
candidate review
  show likely/possible candidates, source links, and mismatches
archive
  store lookup receipt only; do not create medication records automatically
```

Capture guidance:

- use a plain non-patterned background, not fabric, when possible
- use bright side lighting so embossed/debossed imprints cast shadows
- capture both sides; a blank side is still meaningful evidence
- fill much of the frame while keeping the whole pill visible
- add a ruler/coin or calibrated camera stand when size is needed
- allow an optional macro/microscope closeup for imprint text only

Safety boundaries:

- The UI must say `possible match`, not `identified`.
- The user must be able to correct the extracted imprint before lookup.
- The result must be confirmed against package, prescription history,
  pharmacist, or doctor before taking any medication.
- No dosage, substitution, or take/do-not-take recommendation is generated by
  this workflow.
- The archive records the images' derived fields, searched sources, candidates,
  and whether the user rejected/accepted the lookup as a personal note.

### Official health web-search AI Task

The general-purpose AI Task workbench uses one prompt-first composer. The user
does not choose `WEB SEARCH` versus `DOC -> MEMO` up front; Governor routes the
task from the provided source inputs:

```text
Prompt + PDF/URL/text
  user supplies a natural-language prompt plus official URL, source text, or a
  text-based PDF
  Governor fetches/extracts source text
  KaosBrain-OpenAI drafts a memo
  PWA writes to Memos only after explicit SAVE MEMO

Prompt only
  KaosBrain-OpenAI turns the prompt into a structured search job
  Governor searches/fetches only allowlisted official health/public sites
  KaosBrain-OpenAI summarizes and reasons from the fetched excerpts only
  PWA shows a read-only result with source links and archives the task
```

Treatment-option prompts are handled as a source-bounded medical reference task,
not as personal medical advice. A prompt such as `질환명 치료 옵션 찾아줘` should
prefer:

1. Korean official/public health pages for patient-facing baseline information.
2. Domestic medicine/regulatory/insurance sources when drugs, 허가사항, or 급여 are
   relevant.
3. Guideline-grade international sources when Korean public sources are thin or
   outdated, such as PubMed/NCBI, NIH/NINDS, NICE CKS, AAFP, and professional
   society guideline pages.

The result should separate:

- non-drug/lifestyle or trigger-management options
- evaluation/tests to consider
- medication/procedure options
- referral or urgent-caution points
- Korea-specific 허가/급여 확인 필요점 when applicable
- source list and checked date

The PWA should label this as a discussion/reference summary. It must not present
the answer as a patient-specific diagnosis, medication order, dosage instruction,
or substitute for clinician judgment.

Initial searchable source adapters target the main national sites that have
public search pages:

- `mohw.go.kr`
- `kdca.go.kr`
- `mfds.go.kr`
- `hira.or.kr`
- `mentalhealth.go.kr`
- `pubmed.ncbi.nlm.nih.gov`
- `entnet.org`
- `ninds.nih.gov`
- `cks.nice.org.uk`
- `aasm.org`
- `aafp.org`

HIRA is handled as a special case for medicine benefit questions. Governor uses
the HIRA 보험인정기준 POST search endpoint instead of the generic site search,
then links directly to the matching 보험인정기준 detail popup. Korean brand-name
queries may be expanded to ingredient/class terms before searching, because
HIRA often indexes current criteria by ingredient or therapeutic class rather
than by product name. Current examples include `알모그란/알모트립탄 ->
Almotriptan/편두통 치료제` and `글리아티린 -> Choline alfoscerate/콜린알포세레이트`.

약학정보원 `health.kr` is allowed as a medicine dictionary helper, not as the
final authority for insurance-benefit decisions. Governor can read its
product-name search and drug detail JSON to discover brand names, English/Korean
ingredient names, MFDS classification codes, and practical category hints, then
use those terms to search HIRA. If HIRA candidates are found for a HIRA-preferred
benefit query, the summary source set is narrowed back to HIRA criteria.

PubMed is also handled as a special case for treatment-option prompts. Public
PubMed article pages may return a cookie wall to a server-side fetch, so Governor
derives the PMID from the PubMed URL and fetches article metadata/abstract text
through NCBI E-utilities before sending excerpts to KaosBrain-OpenAI. PubMed
records without usable abstracts are skipped instead of being summarized from a
title-only cookie page.

For HIRA medicine-benefit searches, KaosBrain-OpenAI should also produce a
source-bounded `차트 기재 추천` section. The recommendation is not an EMR write
and must not invent patient facts. It should provide copyable Korean examples
with clear placeholders and list the clinical facts the clinician should verify
and document, such as diagnosis, symptom/severity, eligibility criteria met,
dose/quantity/interval, and follow-up plan.

The wider official health/public allowlist also permits fetched source links
from national public-health, insurance, evaluation, medicine, and affiliated
agency domains such as `nhis.or.kr`, `longtermcare.or.kr`,
`nedrug.mfds.go.kr`, `nip.kdca.go.kr`, `health.kdca.go.kr`, `nih.go.kr`,
`nmc.or.kr`, `ncc.re.kr`, `neca.re.kr`, `khealth.or.kr`, `khidi.or.kr`,
`kohi.or.kr`, `k-his.or.kr`, `k-medi.or.kr`, `kuksiwon.or.kr`,
`koda1458.kr`, and `koiha.kr`.

This is deliberately not broad web browsing. The model does not choose arbitrary
URLs and Governor rejects fetched pages outside the allowlist. Public-health
documents should always stay preview-before-save.

### Indexed PDF textbook source tier

Server-side medical textbook PDFs can be an AI Task source tier. They are indexed
locally rather than uploaded in full on every prompt. The first implemented
source is Harrison's Principles of Internal Medicine, 22e, stored as a read-only
SQLite FTS index for Governor.

Pipeline:

```text
PDF folder on H3/H4
  operator places trusted textbook/reference PDFs in a configured read-only folder
ingestion job
  extracts embedded text or OCR text, page by page
  stores chunk metadata: filename, page, section heading when available, hash
local index
  builds a searchable local index over chunks
AI Task prompt
  Governor searches official web sources and local textbook chunks separately
  only the most relevant excerpts are sent to KaosBrain-OpenAI
result archive
  stores source citations as filename + page/section + hash, not full copied text
```

Runtime defaults:

- H3 bind-mounts `${KAOS_ROOT}/reference/textbooks` into Governor as
  `/data/textbooks:ro`.
- `AI_TASK_TEXTBOOK_INDEX_PATH` defaults to
  `/data/textbooks/harrison/index/harrison22.index.sqlite`.
- `AI_TASK_TEXTBOOK_SEARCH_ENABLED=false` disables the local textbook tier.

Source priority:

1. Current official/guideline sources decide present recommendations.
2. Textbooks provide background, mechanism, differential diagnosis, and clinical
   framing.
3. If textbook content conflicts with newer official/guideline sources, the AI
   Task should surface the conflict and prefer newer dated guidance.

Guardrails:

- The configured textbook folder is server-side only; the PWA does not expose a
  raw file browser.
- Do not send whole books to OpenAI; send bounded excerpts only.
- Cite page/section, checked index date, and source hash.
- Keep copyright-sensitive output as summaries and short citations, not long
  copied passages.
- Treat this as reference support for the user, not autonomous clinical
  decision-making.

## Data Contract

Feed cards should be explicit JSON objects, not rendered HTML blobs from Brain.

Minimum shape:

```json
{
  "id": "card-id",
  "type": "document.metadataReview",
  "title": "Review document metadata",
  "state": "pendingConfirmation",
  "summary": "Title and tags are ready to apply.",
  "actions": [
    {"id": "apply", "label": "Apply", "kind": "confirmingMutation"},
    {"id": "edit", "label": "Edit", "kind": "form"},
    {"id": "cancel", "label": "Cancel", "kind": "dismiss"}
  ],
  "links": [
    {"label": "Paperless", "href": "https://paperless..."}
  ]
}
```

Brain may draft the proposal behind a card, but Governor owns the card state,
confirmation requirement, action idempotency, and final receipt.

## Relationship to Existing Pages

The existing pages remain useful:

- Agenda
- Calendar
- Tasks
- Supplies
- Memos
- Documents
- Fax
- Mail
- Utils
- Settings

The feed should not replace them immediately. It should become a top-level
command/log view that opens exact existing pages or embeds focused command
cards. The current page-specific `+` behavior can become the first command-menu
primitive.

## Notification Relationship

Pushover remains the immediate Apple Watch alert layer. It should not carry
large details or action complexity.

Preferred pattern:

```text
Pushover short text
  -> exact PWA card/deep link
  -> Governor-backed structured action
```

Examples:

- `Good Morning.`
- `Fax received.`
- `Fax send failed.`
- `KaosBrain auth renewal.`
- `System maintenance required.`

## Security Rules

- Do not let PWA cards execute arbitrary shell, JavaScript, SQL, or generated
  model commands.
- Do not store authoritative state only in browser storage.
- Do not let Brain-generated text define executable action targets.
- Destructive or external-send actions require Governor confirmation policy.
- Action IDs must be scoped, expiring, and idempotent.
- MacBridge or system-operator actions remain behind Governor, not direct PWA
  access.
- PWA cards may display links to Discord `#brain`, Paperless, Memos, or other
  upstream UIs, but those links do not replace Governor authorization.

## Migration Path

1. Define read-only feed/card API shape.
2. Add a `Kaos Feed` route to the personal PWA.
3. Start with existing read-only sources:
   - daily digest state
   - mail unread marker
   - Documents Inbox
   - failed fax attention
   - system status
4. Convert current page-specific `+` menu into reusable command-card opening.
5. Add confirmation-card rendering for existing governed mutations.
6. Add optional Ask Kaos text input only after deterministic cards are useful.
7. Add Pushover deep links into exact cards.
8. Retire direct Discord operational surfaces only after feed replacements pass
   production observation.

## Non-Goals

- Do not build a Discord clone.
- Do not make OpenClaw or KaosBrain the action executor.
- Do not route ordinary button actions through an LLM.
- Do not replace existing domain pages in the first slice.
- Do not use browser local storage as the authoritative feed log.
- Do not remove Discord fallback until PWA feed, Pushover links, and Governor
  workflows are observed in production.
