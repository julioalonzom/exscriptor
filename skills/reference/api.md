# Submission API

Set API origin via SCHOLA_API_URL; all paths below are relative to it. Public discovery uses GET /api/works/{slug}, GET /api/works/{slug}/outline and GET /api/authors/{slug}. Authenticated requests use Authorization: Bearer followed by SCHOLA_IMPORT_TOKEN, an agent key (it begins `stci_`). Do not include secrets in request bodies or URLs.

- GET /api/corpus-imports/works/{slug}/guard-context: the work's stored source declarations.
- POST /api/corpus-imports: JSON {"manifest": <manifest>, "supersedes_batch_id": <optional integer>}. Returns a pending batch detail. schema_version is 1. A manifest contains batch_slug, title, summary, sources, authors, works and author_merges; consult manifest-schema.json.
- GET /api/corpus-imports?offset=0&limit=25: batches owned by this key's human owner.
- GET /api/corpus-imports?batch_slug=<url-encoded slug>: find your batch after a timeout. Empty list means no owned match.
- GET /api/corpus-imports/{id}: owned status, manifest, validation and review feedback. Foreign IDs return 404.

Example submission (never enable shell tracing):

```sh
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $SCHOLA_IMPORT_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @submission.json "$SCHOLA_API_URL/api/corpus-imports"
```

Wrap the manifest file under a manifest property to create submission.json. Do not put the token in that file. Inspect non-2xx responses; do not treat curl output as approval.

Same owner, slug, canonical payload and predecessor is an idempotent retry. Different content/predecessor conflicts (409); choose a new slug and reference the predecessor. Rotation permits an active replacement key from the same person to supersede a batch; it does not release quarantine. 401/403 means obtain valid access, 404 means no accessible resource, 413 means reduce batch size, 422 means the manifest does not match the schema (the response names the field), 429 means wait according to the response. Validation errors require source/target correction, not blind retries.

## What staging checks

Staging applies the batch to the live corpus inside a transaction and rolls it back. Every error approval would raise is raised at staging, and the batch is refused. Approval applies it again under locks. If the live work changed in between, approval refuses with a fresh report and the batch stays pending.

Unknown fields are refused, never ignored. A text may name a source already in the corpus without redeclaring it; its `license_code` and `rights_basis` default to the source's. One entry per work slug per manifest: several changes to one live work are one `edit` entry with several operations; two entries for the same slug are refused.

Inline notes never nest: never write a note inside a note, an unclosed note or a doubled opening (`^[^[`). Staging accepts the string, but the reader leaves the stray marker as literal text in the note or the body, so a batch that carries one comes back in review. An error or remark about a footnote's own text goes at the end of that footnote, in plain square brackets: `^[46. Verba Hugonis … censeas. [Editor's note: the print reads *Quiquid*; read *Quidquid*.]]`.

A staged batch carries no placeholder: no `⟦…⟧`, no `[illegible]`, no bare `word?`, nothing left for someone else to settle. A printed conjecture is not a placeholder — it is the edition's apparatus and stays as the note it is, `^[quoniam?]` at its place, translated as `^[since?]`.

## Licences

`license_code` is a closed list — anything else is refused, and the database holds the same list: `public_domain`, `CC0-1.0`, `CC-BY-4.0`, `CC-BY-SA-4.0`, `redistribution_permission`, `display_permission`. The last two are a rights holder's own terms, named by the source's `license_url`; the others are licences. `rights_basis` is how the text came to us: `public_domain_life_70`, `public_domain_edition`, `open_license`, `own_contribution`.

- Text we transcribed, edited or translated is `CC-BY-4.0`, with `license_url` `https://creativecommons.org/licenses/by/4.0/` and an `attribution_text` crediting ScholaThomistica, for example "Latin edition by ScholaThomistica (scholathomistica.com), from <the print>": `own_contribution` for a translation or transcription we made, `public_domain_edition` for our own edition of a public-domain print. Never `CC0-1.0` — a published CC0 text can never be taken back.
- A third party's text keeps its own licence: `open_license` with its code, or `public_domain` when the text itself is out of copyright (Jowett, a CSEL edition, a digital text taken as is), naming whose it is. Under `public_domain_edition`, `public_domain_life_70` or `own_contribution` the builders and `exscriptor.submit` take the text for ours unless `metadata.schola_license_exempt` says whose it is. A live source keeps its metadata byte for byte, so the exemption goes on a new `source_key`.
- A live source keeps its terms. A continuation under different terms declares a new `source_key`.
- An `edit` batch is not licence-checked: a correction inherits the licence of the text it corrects.
- Contributions made on the website run under the site's submission terms, which
  dedicate a contributor's own text under `CC0-1.0`; they go through the review
  queue, not this API. Text staged here as our own work is `CC-BY-4.0`, and
  `CC0-1.0` is never right for text we made.

## Work modes

Magisters may stage these. Each adds to the corpus and changes nothing that exists:

- `create`: a new work. Name a new author through `author_key` (declared in `authors`) or an existing one through `author_slug`. Section `sequence` is optional; list order is the default. A work digitized and translated in the same job goes up as ONE `create` carrying both languages, so one review publishes the pair; `append_texts` is for a translation made later, from the live text.
- `append_sections`: new sections on a live work. A top-level entry goes under `parent_path` (a live section's slug path) or the work root, after the existing sections unless it gives a `sequence` that is free.
- `append_texts`: a language a live section does not have yet. Address sections by slug, with `parent_key` chains for nesting. A section that already has the language is refused; correcting it is an edit.
- `attach_facsimile`: make `facsimile` the work's complete page list. `create`, `append_sections` and `append_texts` also accept a `facsimile`. Each page names its image (`filename`, your render's name), a `section_path`, an optional `page_label` and an optional `text_offset` into that section's original-language text. A page you send yourself ("Page scans" below) also carries its `sha256`; a page without one must already be live under `scans/<work-slug>/`.

The Custos stages these:

- `edit`: an ordered list of `operations` on a live work, addressing sections by the ids in `GET /api/works/{slug}/outline`. Each operation states what it expects to find, so it is refused if the work moved on.
  - `add_sections {parent_id, before_section_id | after_section_id, sections}`: insert new sections anywhere. `parent_id: null` is the work root, and siblings are renumbered. Front matter before chapter 1 is `{"parent_id": null, "before_section_id": <chapter 1 id>}`.
  - `put_text {section_id, language, content, expected_text_id}` (unchanged content is a warning that writes nothing; never delete a language to replace it): `expected_text_id: null` adds a language and needs `source_key` and `role`. An id writes a new version of that text, inheriting every source link of the current version with its role and terms, unless `source_key` or other provenance is given. Earlier versions stay in the history. Text ids come from `GET /api/works/{slug}/sections/texts?section_ids=A&section_ids=B` (repeat the parameter, up to 40 per request).
  - `update_section {section_id, expected, set}` and `update_work {expected, set}`: change fields, each guarded by its current value in `expected`. `canonical_locus` and `canonical_key` can be added but not changed.
  - `move_section {section_id, expected_parent_id, parent_id, before_section_id | after_section_id}` and `delete_section {section_id, delete_texts, expected_text_ids}` (only a section with no children, scans or `canonical_locus`). A section with text is refused unless `delete_texts: true`, which needs `expected_text_ids`: the section's current text ids, one per language, as the texts endpoint above lists them. Those texts and all their earlier versions are deleted, in every language, with their source links, and pending corrections to them are rejected. If the section's current texts are not exactly those ids, the operation is refused, so a version or language added after staging is never deleted unseen. The approved batch is the record of what was deleted: its report lists every deleted text with its id, language, version and creator, and a deletion the report (300 lines per work) could not list in full is refused, so split such a batch. The content itself is recoverable only from the daily database backup, so set the flag only for text you mean to discard, such as sections to be redone from scratch.
  - `add_relation`, `remove_relation`, `set_facsimile {pages}`.
- `update_work {expected, set}` on an `append_sections` or `append_texts` work: the work's own fields ("the work is now complete") travel with the batch that completes it. `expected` is the work as it stands before the batch; the fields are set after its sections and texts.
- `author_merges: [{duplicate, canonical, aliases, canonical_description}]`: retire a duplicate author into the canonical one.

Titles: a new title rides with the text it belongs to — `title_translations` on the section, in the language of the text the batch adds. Changing an existing title is `edit` `update_section` with `expected: {"title_translations": <current map or {}>}` and `set` the full new map; that is a Custos action, not an append.

## Page scans

Send each page image with your key before staging. `python3 -m exscriptor.upload_scans <manifest>` does it for every facsimile row and writes each row's `sha256`.

- PUT /api/corpus-imports/scans/{sha256}: the raw image bytes as the body; `sha256` is the lowercase hex SHA-256 of exactly those bytes. Returns {"sha256", "filename", "already_staged"}. A page already held returns at once, so a retry is free.

The server re-encodes the page (WebP, long edge 2400 px; metadata such as GPS is dropped) and screens it for sexual content. A held page is not public: approving the batch publishes it with the text, and rejecting the batch publishes nothing. Held pages expire 30 days after sending; a batch staged after that is refused for a missing image, so send again, then stage. 413 means the file is over 30 MB; 422 that it is not an image, its hash does not match, or the screen refused it (a genuine page the screen refused goes to the Custos); 503 that the screen or the store is down, so retry later. Send only pages you may publish: the batch's source must cover them.

## Commentary works

A commentary is its own work, linked to the work it comments on. The base work carries a path-only `canonical_locus`; the commentary carries a fully qualified `commented_locus` (`summa-theologiae:pars.I/quaestio.2/articulus.1`) and a `commentary_on` relation naming that work. A `commented_locus` with no matching relation is refused. Publish only the commentator's words: text the edition prints from the commented author belongs to the other work.

A batch may not introduce a structural problem: two siblings with one slug or sequence, a reused `canonical_locus`, or a `commented_locus` without a matching `commentary_on` relation. Problems the work already had do not block it.

The modes `update_metadata`, `reconcile_existing` and `restructure_existing` were retired on 2026-10-19; use `edit`. All publication is a separate human review action in the website.
