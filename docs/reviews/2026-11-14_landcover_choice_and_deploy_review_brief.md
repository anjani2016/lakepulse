# Review brief: land-cover source choice + Cloud Run deploy (uncommitted)

Branch `feat/lake-trend-detective`, HEAD `16313b7` (a land-cover-track commit, not part of
this review). Repository `~/dev/esg/lakepulse`. Author: Claude Code; the author must not
review this. Two independent changes; please give a verdict on each.

Not in this review: anything under `landcover/` and `data/external/` (land-cover track).

---

## Part A — Land cover: which source the analysis uses

Owner, verbatim: "we use the guideline and our own assessment and exclude it for analysis";
"go ahead, but we choose one and say why?"; on showing both sources flagged: "ok".
Full decision record: `docs/PLAN.md`, section "Land cover: which source the analysis uses".

Files: `lakepulse/variables.py` (shared `LANDCOVER_NOTES`; `EXCLUDED_FROM_ANALYSIS`;
`ANALYSIS_TIER`; `excluded_reason()`), `lakepulse/analysis.py` (`_analysis_rows`,
`analysis_sources`, `AnalysisSourceError`; excluded series get status "excluded" and no
statistics), `scripts/run_analysis.py` (`analysis_sources` in page data), `web/index.html`
(source picker opens on the analysis source and labels "used in the analysis" / "comparison
only"; verdict headings "Too short to test a trend" / "Not used in the analysis"),
`tests/test_analysis.py` (4 new tests), `docs/PLAN.md`; regenerated
`data/lake_trend_table.csv`, `data/results/*.csv`, `web/site_data.js`.

Behaviour change: the table is now built WITHOUT `--skip-external` (7,396 rows, including
the 27 land-cover-ca rows). Significant trend series 14 → 11 (MODIS forest, cropland, urban
no longer assessed).

Checks run:
- `.venv/bin/pytest -q` → 63 passed, 1 warning.
- `scripts/build_table.py` → 7,396 rows; `scripts/run_analysis.py` → 30 trend series
  (11 significant), 24 correlation rows.
- MODIS 2020 class breakdown read from the MCD12Q1 file (woody savanna 16.9%, mosaic 16.3%,
  savanna 15.2%, mixed forest 4.1%, deciduous broadleaf 3.2%, urban 3.0%).
- Prithvi-EO-2.0-300M facts read from its Hugging Face model card (API and README).
- Browser (local preview): cropland and forest open on land-cover-ca ("Too short to test a
  trend", 9 points); MODIS option "comparison only" ("Not used in the analysis", 25 points,
  no trend line); console clean; no horizontal scroll.

Please check:
1. The plain-language notes (`LANDCOVER_NOTES`) match the evidence and cite correctly
   (MCD12 Table 3 p. 9; p. 3 warning; 2020 values; 48.4%).
2. Selection by tier is fail-closed (two ML sources raise) and cannot pick MODIS land cover.
3. No statistic is shown for an excluded series anywhere (trend table, correlations, page).
4. Wording about Prithvi and IBM/NASA is attribution of a public model, not a partnership.
5. Probes: a third land-cover source with tier "Satellite-derived"; MODIS land cover with
   a 26th year; a practice-lake land-cover row (practice lake keeps its own source).

Unsure: the land-cover-ca rows themselves (model quality) were not reviewed here; the
choice rests on the class check and the model's agreement with its 2020 label map.

---

## Part B — Cloud Run deploy files

Owner, verbatim: "host it on google cloud run". Owner rule: deploys only through GitHub
Actions; never by hand. Project, owner verbatim: "centauri-research-brand"; "we have the
setup already with centauri research.if that is easy to recycle." So LakePulse deploys as
its own Cloud Run service `lakepulse` in the same project, region and Artifact Registry
repository as the website (`centauri-brand-website`), reusing its GitHub-to-Google login.
Login, owner verbatim: "we can use sa key and regenerate as needed". So: a dedicated deploy
account `lakepulse-deploy` (key stored as GitHub secret `GCP_SA_KEY`; roles: Cloud Run admin
on the project, Artifact Registry writer on `cloud-run-source-deploy` only, service-account
user on the runtime account only) and a runtime account `lakepulse-run` with no roles
(`--service-account` flag in the workflow), so the page does not run as Cloud Run's default
account. Please check: Cloud Run admin is project-wide, so a leaked key could still change
the website service; narrowing it to the `lakepulse` service is possible after the first
deploy creates it.

Files: `Dockerfile` (nginx-unprivileged 1.27.4-alpine, serves only `web/`, port 8080),
`deploy/nginx.conf` (caching, gzip, 404 outside `web/`), `deploy/security-headers.conf`
(CSP, X-Frame-Options, nosniff, Referrer-Policy; included in every location),
`.dockerignore` (only `web/` and the two config files), `.github/workflows/deploy.yml`
(tests → image build + smoke test → deploy on push to `main` only; WIF or SA-key auth as in
the Centauri Research website workflow; fails closed when `vars.GCP_PROJECT_ID` is empty;
`--allow-unauthenticated`, 256 MiB, 0–3 instances, region us-central1).

Checks run:
- `actions/setup-python` pin `a26af69…` matched the v5.6.0 tag via the public GitHub API;
  other pins copied from the website workflow.
- `docker build` → image 78,679,454 bytes, user 101. Running it: `/`, `/index.html`,
  `/site_data.js`, `/assets/*.png` → 200; `/Dockerfile`, `/deploy/nginx.conf`,
  `/nonexistent` → 404; `/../data/lake_trend_table.csv` → 400. Headers present on `/` and
  `/assets/`. gzip: site_data.js 70,901 vs 250,484 bytes.
- Browser against the container: data loads, chart, verdict, logo, demos; console clean
  under the CSP.
- Not run: the workflow on GitHub (no project configured yet); no deploy performed.

Please check:
1. CSP covers everything the page loads (inline script/style only, same-origin images).
2. Nothing outside `web/` can reach the image; no secrets in the image or workflow.
3. Fail-closed deploy guard; deploy only on push to `main`.
4. Public access is intended (judges); the page has no forms or user data.

---

Verdict format: per part, APPROVED / CHANGES REQUESTED, with file:line for each item.
Record: this file; commit SHA pending; no review text on file until the reviewer replies.

## Review 1 (2026-11-14, Antigravity / Codex), verbatim as relayed by the owner

Part A — CHANGES REQUESTED

1. [P1] The source comparison is not spatially equivalent.
[docs/PLAN.md (line 103)](/Users/anjanid/dev/esg/lakepulse/docs/PLAN.md:103) says “Same box,” but MODIS covers the 6,961.6 km² bounding box while `data/external/land_cover_ca.csv` covers six watershed polygons totaling about 3,381.5 km². Correct the explanation or use the available model bounding-box results for the comparison. The source choice may remain, but its evidence must disclose the spatial mismatch.
2. [P1] A third comparison source can still publish trend statistics.
[lakepulse/analysis.py (line 107)](/Users/anjanid/dev/esg/lakepulse/lakepulse/analysis.py:107) suppresses statistics only for sources explicitly listed in `EXCLUDED_FROM_ANALYSIS`. The required probe added a third `Satellite-derived` forest source: `analysis_sources()` correctly selected the ML model, but `trend_table()` reported the third source as `ok`, significant, with a slope and p-value. Any non-selected real-lake land-cover source must receive `status="excluded"` and no statistics. Add this probe to the tests.

The other Part A probes passed: two ML sources fail closed, a 26-year MODIS series remains excluded, and practice-lake land cover retains its practice source.
Part B — CHANGES REQUESTED

1. [P2] The image serves a file outside `web/`.
[Dockerfile (line 7)](/Users/anjanid/dev/esg/lakepulse/Dockerfile:7) overlays `web/` onto nginx’s existing document root without clearing it. The resulting image retains `/usr/share/nginx/html/50x.html`, and `GET /50x.html` returns HTTP 200. Clear the default document root before copying, or copy into a clean directory and make that the nginx root. Add `/50x.html` to the isolation smoke tests in [deploy.yml (line 60)](/Users/anjanid/dev/esg/lakepulse/.github/workflows/deploy.yml:60).

Other Part B checks passed:

* Image runs as user 101; repository code, data, and deploy configuration return 404.
* Traversal probe returned 400.
* CSP covers current page resources; security headers are present on HTML and assets.
* No credentials were found in the image or image environment.
* Deploy is restricted to pushes to `main` and fails when `GCP_PROJECT_ID` is empty.
* The setup-python pin matches v5.6.0.
* Shared deploy credentials do create the documented cross-service blast radius: the same account could deploy over `centauri-brand-website`. This is an acknowledged owner trade-off; a dedicated LakePulse deploy identity would reduce it.

Verification: `63 passed, 1 warning`; generated artifacts rebuilt byte-for-byte identically; `git diff --check` clean. No commit, push, or deployment performed.

## Fixes for review 1 (author; please re-review these)

A1. Same-area comparison now used, area difference disclosed.
- `lakepulse/variables.py` `LANDCOVER_NOTES`: the 2020 comparison uses the bounding box for
  both sources (MODIS 7.2 / 35.0 / 3.0%; model 31.6 / 48.8 / 14.3%, from
  `landcover/data/results/modis_agreement.csv`, land-cover track's `modis_agreement.py`);
  a new note states that the page's MODIS series covers the 6,962 km² box and the
  land-cover-ca series covers the six watershed units (3,383 km²; 2020 29.7 / 49.6 / 14.4%).
- `docs/PLAN.md`: "same box" corrected; same-area gap over 2017–2025 (forest 22.0–25.1,
  cropland 12.1–18.0, urban 11.2–11.7 points) and the area difference recorded. The source
  choice stands: the gap is as large over the same area.

A2. Every non-chosen land-cover source on a real lake is excluded.
- `lakepulse/analysis.py`: `_excluded()` gives status "excluded" and no statistics to any
  source of an `ANALYSIS_TIER` variable that is not the chosen one (reason
  `COMPARISON_ONLY_REASON`), in addition to the explicit MODIS list.
- `tests/test_analysis.py::test_any_non_chosen_land_cover_source_gets_no_statistics`: your
  probe (third "Satellite-derived" forest source with a clear trend) → excluded, no slope,
  no p-value, absent from correlations.
- Found while fixing: filtering an empty group with an empty Python list selected columns,
  not rows (KeyError 'variable' when a lake has MODIS land cover but no model rows); now a
  Series row mask.

B1. Served folder holds only `web/`.
- `Dockerfile`: `web/` copied into a fresh `/srv/lakepulse/`; `deploy/nginx.conf` root
  changed to it. nginx's sample pages stay in the image but outside the served root.
- `.github/workflows/deploy.yml` smoke test: `/Dockerfile`, `/deploy/nginx.conf`,
  `/50x.html`, `/index.nginx-debian.html`, `/data/lake_trend_table.csv` must return 404;
  `/../data/lake_trend_table.csv` must return 400.

Also changed since review 1 (owner's login choice, verbatim: "we can use sa key and
regenerate as needed"): dedicated `lakepulse-deploy` account with a key in `GCP_SA_KEY`,
and an empty runtime account `lakepulse-run` (`--service-account` flag). The website's
deploy account is not used, so the cross-service risk you noted is narrowed to what
project-wide Cloud Run admin allows (see Part B note above).

Checks after the fixes:
- `.venv/bin/pytest -q` → 64 passed, 1 warning. `git diff --check` → clean.
- `scripts/build_table.py` → 7,396 rows; `scripts/run_analysis.py` → 30 trend series
  (11 significant), 24 correlation rows.
- Image (`docker build`), smoke test as in the workflow: page, data, logo 200; the five
  paths above 404; traversal 400; served folder 8 files = `web/` 8 files; user 101.
- Browser against the container: forest_share opens on land-cover-ca ("Too short to test a
  trend"); MODIS "comparison only"; new notes shown; console clean; no horizontal scroll.

## Submission-readiness review (2026-11-14, Codex), verbatim as relayed by the owner

Must fix before submission

1. Add an explicit OSI-approved licence.
The repository currently says `[verify: licence terms]` and © Alpha Centauri Ventures Inc. in [README.md (line 77)](/Users/anjanid/dev/esg/lakepulse/README.md:77), with no root `LICENSE` file. NASA requires original work to be openly licensed and requires appropriate licence documentation for third-party materials. Missing citations or licensing can cost a nomination or award under the [2026 Participant Terms](https://www.spaceappschallenge.org/legal/).
2. Resolve the corporate/personal-capacity framing.
The README calls this “A Centauri Research project” in [README.md (line 3)](/Users/anjanid/dev/esg/lakepulse/README.md:3), and the model card says it was made by the company in [land-cover model README (line 29)](/Users/anjanid/dev/esg/lakepulse/landcover/hf/land-cover-ca/README.md:29). Participants must act in their personal capacity, and submissions must not promote commercial services. This is not necessarily disqualifying, but you should submit under the registered participants’ names and confirm that you have authority to open-source company-owned material.
3. Update the stale status statement.
[README.md (line 6)](/Users/anjanid/dev/esg/lakepulse/README.md:6) says only practice data exist, but the repository now contains processed Lake Simcoe data and the generated site uses real results. Judges could mistakenly conclude that the prototype is synthetic.
4. Complete references and third-party notices.
The NASA products are named, but several `[verify]` items remain in [docs/PLAN.md (line 94)](/Users/anjanid/dev/esg/lakepulse/docs/PLAN.md:94), including a catchment-area source. Cite every NASA dataset, Ontario dataset, base model, software package, image/font/logo asset and external model-training resource. The model card claims there is a `LICENSE`, but only its `NOTICE` is present locally.
5. Explicitly disclose AI use.
The internal plan records Claude Code and Antigravity involvement in [docs/PLAN.md (line 151)](/Users/anjanid/dev/esg/lakepulse/docs/PLAN.md:151). Put a concise, transparent AI-use statement on the project page: tools used, what they contributed, and what humans reviewed or validated.
6. Prepare the actual submission package.
You still need a complete English project page, public repository/final-project link, project details, NASA-data explanation, references, and either the required short video or slide demo. Confirm any additional local-event requirements.
7. Lead with the scientifically safest results.
Explain that the catchment variables use a bounding box roughly twice the watershed area, MODIS land cover is not recommended for detecting change, and daytime MODIS temperature has a significant orbit-time drift flag. These do not invalidate LakePulse, but hiding them would weaken validity.

## Changes for the submission-readiness review (author)

Owner decisions (answers to two questions, verbatim): licence "Apache-2.0 (Recommended)";
name "My personal name".

1. Licence: `LICENSE` = official Apache-2.0 text from apache.org (202 lines, unchanged);
   `NOTICE` = "Copyright 2026 Anjani Duddukuru" plus third-party data, model and software
   terms. NASA data terms quoted from NASA Earthdata "Data Use Guidance" (CC0 unless marked;
   cite; no endorsement). Package licences read from installed metadata
   (`importlib.metadata`); nginx licence read from nginx.org/LICENSE.
2. Personal capacity: README, page footer and NOTICE name Anjani Duddukuru; company name
   removed from README and from the workflow comment. NOT changed (land-cover track's
   files, left to that track): `landcover/hf/land-cover-ca/README.md:29`,
   `landcover/hf/land-cover-ca/NOTICE:2`, `landcover/REPORT.md:133`,
   `landcover/scripts/register_model.py:105`, `landcover/config.yaml:117`; the model card
   is also published on Hugging Face and needs republishing there.
3. Status: README now says working prototype with real Lake Simcoe data 2000–2025; practice
   lake described as a labelled learning aid.
4. References: README "References" lists the ten NASA products with DOIs (from CMR this
   session), the product documents used, Ontario datasets, the land-cover-ca inputs,
   software, and the methods (Mann 1945, Kendall 1975, Sen 1968, Gilbert 1987). All five
   `[verify]` items in `docs/PLAN.md` replaced by plain statements of what was and was not
   checked (Giovanni cross-check not done; LAADS approvals; MOD08_M3, MERRA-2 and IMERG
   accuracy not found or not read; 2,990 km² has no source and is used in no calculation).
   The model card's missing `LICENSE` is a land-cover-track item.
5. AI use: README "How AI was used" and a page-footer statement (tools, contributions,
   what the author decided and approved, that reviews were by an AI agent, and that the
   logo change was not reviewed).
6. Submission package: not done in this change (project page text, video or slides,
   local-event requirements) — next step.
7. Safest results first: README "Main results" leads with the night-time lake trend and a
   "Limits" section; the page has a "Key result, and what to keep in mind" panel whose
   headline is read from the analysis results (night-time +0.65 °C/decade, p < 0.001) and
   five plain limits (pass-time drift, skin temperature, box ≈ twice the catchment, land
   cover, model and regional values; association not cause).

Checks: `.venv/bin/pytest -q` → 64 passed, 1 warning; `git diff --check` clean; workflow
YAML parses; browser: key panel and footer render, no company name on the page, console
clean, no horizontal scroll.

## Part D — land-cover dashboard as a page (author, 2026-11-15; please review)

Owner, verbatim: "add this artifact as a page to our output web page
<https://claude.ai/artifact/LG1FJPwnTRxAFLU47k9UWs>"; "lets fix some stuff as the deployment
happens. we push in the next version".

Files: `web/landcover.html` (the dashboard's own markup and two scripts, unchanged except
the Prithvi attribution, now quoting its model card; plus our header, back link, intro,
Sources table and footer), `web/landcover-runtime.js` (local stand-in for the four
dashboard calls the page uses: data, calc, colors, draw), `web/landcover-data.js`
(generated), `web/vendor/d3-7.9.0.min.js` (cdnjs, SHA-512 matched cdnjs's published SRI;
npm licence ISC), `data/landcover_dashboard/*.csv` + `manifest.json` (the six attached CSVs,
SHA-256 matching the artifact's asset store), `scripts/build_landcover_page.py` (checks
checksums, fail closed; parses CSV to text rows), `tests/test_landcover_page.py` (5 tests),
`web/index.html` (link in the key panel), `deploy/nginx.conf` (no-cache for the page and its
two scripts), `.github/workflows/deploy.yml` (smoke test covers the new files),
`NOTICE` (d3, page data).

Found while testing: d3's CSV parser uses `new Function`, which the site's CSP (no
'unsafe-eval') blocks; parsing moved to the build script and a test forbids eval-like code.
A grid min-width issue made the page 515 px wide on a 375 px phone; fixed with
`min-width: 0` on grid children (earlier width checks compared against the widened window).

Checks: `.venv/bin/pytest -q` → 69 passed. Dashboard numbers cross-checked against project
files (2020 MODIS 7.22/35.02/2.96 and model 31.587/48.767/14.329 match
`landcover/data/results/modis_agreement.csv`; 2020 catchment 29.738/49.553/14.368 match
`data/external/land_cover_ca.csv`). Container: page, data, runtime, d3 200; config and data
paths 404; traversal 400; CSP and no-cache headers present. Browser under the container's
CSP: 14/14 numbers, 4 charts, 3 tables, 6 sources, selectors work, console clean; 375 px
light and dark: no overflow.
Please check: the compute section (Colab units per session) is intended for a public page;
the runtime matches what the page calls; no data value reaches innerHTML.

## Team credit (author, 2026-11-15)

Owner on the team member under 18: "he was mostly there for experience. he designed the
logo. read through the rules and various challenges and guidelines. create the template
for presentation". Space Apps 2026 Participant Terms (spaceappschallenge.org/legal): names,
voices and likenesses of persons under 18 should not be included in any submission. So the
README, NOTICE and both page footers credit "a team member under 18 (name withheld, as the
Space Apps rules ask)" with those contributions; the name appears in no project file, in
the git history, or in the text of the presentation decks in output/ and
presentation_build/ (checked with grep and inside the .pptx XML).

## Sign-off

Owner, verbatim: "commit and push".
Review status at commit: Part A and Part B review 1 = CHANGES REQUESTED; the fixes were
made but NOT re-reviewed. Submission-readiness changes (Part C), the land-cover page
(Part D) and the team credit were NOT reviewed. Committed and pushed on the owner's
instruction without a further review. Part B's deploy files were committed separately as
cabe523 before this; this commit adds the smoke-test lines and no-cache rules for the
land-cover page.
Checks at commit: `.venv/bin/pytest -q` → 69 passed, 1 warning; `git diff --check` clean;
workflow YAML parses; outputs rebuilt (7,396 table rows; 30 trend series, 11 significant).
