# Local validation — Staff Credit rebuild

## 2026-11-11 — Make patient description optional (19.0.2.0.33)

- Patient / other description is optional for manual entries and native imports. If blank, a generated invoice uses the Staff Credit reference as its line label; report exports leave it blank and deductions use the bill reference.
- Added a regression verifying an empty description can create a linked draft invoice with its fallback line label.
- Validation passed: Python compileall, XML parsing, manifest parsing, `git diff --check`, THA module upgrade, and the full addon suite (**39 tests, 0 failures, 0 errors**).

## 2026-11-11 — Show newly imported bills first (19.0.2.0.32)

- Changed the Staff Credit default order to record ID descending. New entries now appear at the top regardless of their historical Charge Date.
- Extended the native import regression to verify a freshly imported backdated bill sorts above a previously created bill.
- Validation passed: Python compileall, XML parsing, manifest parsing, `git diff --check`, module upgrade on THA, and the full addon suite (**38 tests, 0 failures, 0 errors**).

## 2026-11-11 — Derive department and partner on native imports (19.0.2.0.31)

- Native Odoo imports do not execute form onchanges. When Department and Partner are omitted or blank, Staff Credit creation now fills them from the selected Employee's Department and work contact. Explicit non-empty values remain supported.
- Updated the backdated native-import regression to omit both related columns and verify they are derived.
- Validation passed: Python compileall, XML parsing, manifest parsing, and `git diff --check`; THA module upgrade and addon suite: **38 tests, 0 failures, 0 errors**.

## 2026-11-11 — Repaid stage for completed balances (19.0.2.0.30)

- Added a read-only computed State display: Draft, Posted, Repaid, or Cancelled. A posted bill displays Repaid when posted settlements reduce its balance to zero; the underlying accounting-linked state remains Posted so invoice and deduction workflows continue to use the existing lifecycle.
- The list badge and form statusbar now include Repaid. Repaid is green like Posted. Added regression coverage for partial and complete manual settlement and view decoration.
- Validation: Python compileall, XML parsing, manifest parsing and `git diff --check` passed. Upgrade and full addon tests on THA passed: **38 tests, 0 failures, 0 errors**.

## 2026-11-11 — List stage placement, invoice settings and deletion (19.0.2.0.22)

- Moved the colored State badge to the final list column. Added Original invoice credit account to the bill Settings dialog; applying a bill-specific setting passes it to invoice creation, and saving as company default updates the company configuration.
- Deleting an unposted or cancelled generated invoice clears its pending Staff Credit link, leaving the bill in Draft so the invoice can be recreated. Posted invoices remain protected.
- Added regression coverage for draft invoice deletion. Upgrade THA, run the focused suite, restart Odoo, and create a clearly labeled local Shop Sphere draft invoice with Dr 130100 / Cr 510585.

## 2026-11-11 — Colored stage badge in list view (19.0.2.0.21)

- Render the Draft, Posted and Cancelled stages as colored Odoo badges in the Staff Credit list: blue, green and red respectively. Added a regression that checks the badge widget and all three state decorations.
- Create one clearly labeled local Shop Sphere workflow test bill and linked draft customer invoice after the module upgrade. Verify the journal items use the configured Staff Credit account as Dr and original invoice credit account as Cr. Leave the invoice in Draft; do not post it.
- Upgrade local THA and run the focused addon suite. Restart `odoo_19` and inspect `logs/server.log` for registry and HTTP startup.

## 2026-11-11 — Draft invoices and lifecycle stages (19.0.2.0.20)

- Added a company-configured original invoice income account, defaulting to account code 510585 where present. Draft Staff Credit bills create linked customer invoice drafts; posting the invoice links its Staff Credit receivable debit and moves the bill to Posted. Cancelling the draft invoice moves it to Cancelled. The form statusbar shows Draft, Posted and Cancelled. Non-posted bills show zero settled amount and balance and are excluded from Excel and deduction processing.
- Added upgrade migrations to preserve existing linked bills as Posted and apply account 510585 per company where that income account exists. Local THA has the account for company 5, so that setting was populated. Company 4 has no 510585 account, so its setting remains unset; managers must select a valid company income account before creating invoices. No chart-of-accounts records or Staff Credit transactions were created by the migration.
- Python AST, XML parsing, manifest consistency and `git diff --check` passed. Upgraded local THA with `-u tha_vhg_staff_credit_report --stop-after-init --http-port=8079 --gevent-port=8082 --test-enable --test-tags /tha_vhg_staff_credit_report`. Final result: **33 tests, 0 failures, 0 errors**. Coverage includes invoice debit/credit accounts, draft/post/cancel lifecycle, pending-report exclusion, account defaults and validation, existing invoice linking, and all prior report/deduction workflows.
- Restarted `odoo_19`. Module `19.0.2.0.20` is installed; existing linked bills remain Posted (6 records). The statusbar and views compiled in the test run. No live deployment or browser visual check was performed.
- Updated README, USER_GUIDE and the root `CUSTOM_MODULES.md` catalog.

## 2026-11-05 — Settings from empty list / first-time setup (19.0.2.0.17)

- User reported Expected singleton: tha.staff.credit() on live 10.100.10.61:8019. Inspected the existing live Staff Credit browser tab: an empty list with Settings and the error dialog was visible. No live records, settings, code or services were changed.
- Cause: the always-visible list Settings button called the same singleton-only method as a bill form. Added a company-settings path for an empty/multiple recordset and an explicit list-button context flag so selecting one row also opens company defaults. The bill form retains its bill-specific override wizard. Opening first-time setup returns a new configuration form without creating a record until Save. Manager permission checks remain mandatory.
- Python AST, XML parsing, manifest data-file checks and git diff whitespace checks passed. Upgraded local THA with --http-port=8079 --gevent-port=8082 --test-enable --test-tags /tha_vhg_staff_credit_report --stop-after-init. Final result: **30 tests, 0 failures, 0 errors** (32 phases including setup). The first run's new-company fixture lacked the Manager role and was correctly rejected; corrected the fixture to use an authorized manager before the successful rerun.
- Restarted local odoo_19. Authenticated calls to the actual /web/dataset/call_button/tha.staff.credit/action_settings endpoint passed for empty list, single list selection, multiple list selection and bill form. Company paths returned tha.staff.credit.config; the bill form returned tha.staff.credit.settings.wizard. No settings were saved by these checks. Inspected project runtime logs after restart.
- Updated README, USER_GUIDE and root CUSTOM_MODULES catalog. Live deployment remains pending: install the updated addon code, upgrade tha_vhg_staff_credit_report in the live database and restart its Odoo service.

## 2026-11-05 — Hide unambiguous source debit selector (19.0.2.0.16)

- Original invoice / entry identifies the accounting document; Staff Credit debit item identifies its particular debit line. Kept both links in the data model, but hide the debit-item selector when exactly one debit matches the company's configured Staff Credit account. Existing onchange logic selects that item automatically. The selector stays visible for multiple or zero matching items, allowing manual selection or correction of the source document.
- Added a nonstored visibility flag, computed with elevated read access so Staff Credit Readers do not need new Accounting permissions merely to evaluate form visibility. No accounting values or additional access rights are exposed by this boolean. The hidden source-line field has force_save=1 to preserve its automatic selection when the form saves.
- Python AST, XML parsing, manifest data-file checks and git diff whitespace checks passed. Upgraded local THA with --http-port=8079 --gevent-port=8082 --test-enable --test-tags /tha_vhg_staff_credit_report --stop-after-init. **28 tests passed, 0 failures, 0 errors** (30 phases including setup). Coverage includes single-debit automatic selection/hiding, empty source, multiple eligible debits, selected amount, reader access and the installed force-save/invisible attributes.
- Restarted odoo_19. Authenticated HTTP checks read all four existing Shop Sphere examples: source-line links remain populated and the selector visibility flag is false. Fetched the installed combined form and verified its conditional visibility and force-save attributes. No accounting records were changed. Browser visual inspection was not performed for this follow-up.
- Inspected project runtime logs and updated README, USER_GUIDE and root CUSTOM_MODULES catalog.

## 2026-11-05 — Simplified report date header (19.0.2.0.15)

- Report row 2 now contains only currency and Report date (export generation date in the user's timezone). Removed the Times/monthly amount explanation and the phrase Posted settlements through from that row. Settlement and balance column cutoff labels remain separate.
- Python AST, XML parsing, manifest data-file existence and git diff whitespace checks passed. Upgraded tha_vhg_staff_credit_report in local THA with --stop-after-init --no-http (exit 0), restarted odoo_19 and inspected the last 300 project log lines; registry and HTTP startup succeeded.
- Authenticated actual export/download checks for both All months and October 2026 returned HTTP 200. Inspected XLSX XML: A2 is Currency: MMK | Report date: 05 Nov 2026 in both reports, independent of the selected month; no Times explanation or Posted settlements through phrase remains in the workbook.
- Rendered and visually checked only the changed header region using bundled Artifact Tool. No automated suite was run for this wording-only change; report calculations and accounting data were not changed.
- Updated README, USER_GUIDE and root CUSTOM_MODULES catalog.

## 2026-11-05 — Completed / total repayment progress (19.0.2.0.14)

- Changed Times from the scheduled installment ordinal in the reporting month to completed / total repayments at the settlement cutoff. Cumulative posted settlements cover actual installment amounts oldest first; partial installments and drafts do not count, and dated reversals reduce progress. Without a generated plan, equal installments from the configured count are used. Unpaid bills show 0/total, and progress remains visible in skipped months, after the plan ends and for all-months exports.
- Updated workbook legend, export dialog help, README, USER_GUIDE and the root CUSTOM_MODULES catalog to match the new meaning.
- Python AST, XML parsing, manifest data-file checks and git diff whitespace checks passed.
- Upgraded local THA with --http-port=8079 --gevent-port=8082 --test-enable --test-tags /tha_vhg_staff_credit_report --stop-after-init. Final result: **27 tests, 0 failures, 0 errors** (29 phases including setup). New tests verify 3/5, manual partial installments, unequal amounts, rounding boundaries, historical cutoffs and all-months reporting; existing draft/reversal and skipped-month tests were updated to the requested semantics.
- Restarted odoo_19 and inspected the last 300 lines of logs/server.log. Registry and HTTP startup succeeded. The authenticated export action and file download returned HTTP 200.
- Downloaded a fresh all-months Shop Sphere workbook and inspected its actual worksheet/shared-string XML: SC/4/000001=2/2, SC/4/000003=1/1, SC/4/000004=0/3, SC/4/000002=1/6. Amounts and accounting records were unchanged. Saved under ignored artifacts/export_review/staff_credit_all_months_progress.xlsx.
- Imported and rendered the corrected workbook with the bundled Artifact Tool and visually reviewed the complete report. Times values and the revised explanatory legend are visible. Browser UI clicks were not repeated for this calculation-only follow-up.

## 2026-11-05 — Direct deduction entry navigation (19.0.2.0.13)

- Updated Generated deductions: Journal Entry explicitly uses the native many2one link widget, row opening is disabled, and an explicit Details button opens the selected account.move.line in a readonly-initialized popup. The action checks the current user's read access and does not use sudo.
- Python AST, XML parsing, manifest data-file checks and git diff whitespace checks passed.
- Upgraded tha_vhg_staff_credit_report in local THA with --stop-after-init --no-http (exit 0), restarted odoo_19, and inspected logs/server.log. Registry startup and HTTP service startup succeeded.
- Authenticated HTTP smoke checks exercised Details for the existing November draft and October posted deduction of SC/4/000002. Both returned the correct journal item ID, account.move.line form and target=new. No accounting entries were changed.
- Fetched the installed combined Staff Credit form through get_views and confirmed the direct many2one widget, no_open=1 on the nested list, and explicit Details object button.
- Browser reload was attempted, but Chrome automation then timed out on CDP navigation/state requests. Visual click-through verification of this follow-up remains unconfirmed. No browser settings or permissions were changed. No automated test suite was run for this small navigation change; the checks above validate source, installed view and server action behavior.
- Updated USER_GUIDE.md and the root CUSTOM_MODULES.md catalog.

## 2026-11-05 — Company numbering, examples and Excel export (19.0.2.0.12)

Target: local Docker Odoo 19, database THA. This does not establish production deployment or accounting-team acceptance.

- Python AST, XML parsing, manifest data-file existence and `git diff --check` passed.
- Upgraded with `docker exec odoo_19 odoo -d THA -u tha_vhg_staff_credit_report --stop-after-init --http-port=8079 --gevent-port=8082 --test-enable --test-tags /tha_vhg_staff_credit_report`.
- Final result: **25 tests, 0 failures, 0 errors** (27 phases including setup). Coverage includes independent company sequences, initial continuation after legacy references, selected-bill and form export scope, workbook structure and native download action, plus the existing accounting workflow checks.
- An initial test invocation failed because port 8069 was occupied. The separate port above resolved it. The first suite run found an incorrect merge-count assertion and a pre-existing undefined permission-test helper; both were corrected before the passing final run.
- Restarted `odoo_19`; project server log showed registry startup and successful Staff Credit list/form, export action and file requests.
- Shop Sphere's explicitly created local example changed from SC/4/000174 to SC/4/000001, with a chatter note retaining the former reference. Its posted accounting line labels retain their original reference. Other companies' existing names were not changed.
- Created three more local examples through ORM and existing schedule/deduction methods: SC/4/000002 (60,675 bill, 10,112.50 posted settlement, 50,562.50 outstanding), SC/4/000003 (26,501 fully settled/reconciled), and SC/4/000004 (470,000 outstanding, one generated October draft). No future deductions were posted. All four Shop Sphere bills total 752,676; posted settlements total 232,113.50; balance is 520,562.50 MMK.
- Authenticated HTTP tests exercised the actual export action and downloaded XLSX files for company-wide list (4 rows), selected bills (2 rows), and a bill form (1 row). All returned HTTP 200 and reconciled to independently checked totals.
- **Actual Chrome button tests completed:** list Export Excel → October → Export Excel downloaded `staff_credit_2026_10 (1).xlsx`; the partial bill form Export Excel prefilled its employee/department/category and downloaded `(2).xlsx` with only that bill. The user supplied both exact Downloads paths. Read and verified both files; worksheet XML, shared strings and styles exactly match the inspected server-generated copies.
- Before the fix, exporting with `target=self` replaced the report tab with `ERR_BLOCKED_BY_CLIENT`. No Chrome settings, extensions, permissions or security controls were modified. The updated native `target=download` downloaded both files and preserved the Odoo page. Temporary navigation/control timeouts were recovered through normal Odoo menu navigation.
- Rendered the complete 14-column report and separately reviewed the amount and reference/remark regions using the bundled Artifact Tool. Verified typed dates/numbers, totals, freeze panes, hidden gridlines, wrapped notes and positive/zero balance highlighting. Files are local review artifacts under ignored `artifacts/export_review/`.
- Added USER_GUIDE.md with setup, source posting, numbering, plan generation, draft/posting distinction, partial repayment, existing settlements, corrections, reconciliation and list/form export scope.

## Earlier rebuild evidence

Date: 2026-10-30. Target: local Docker Odoo 19, database THA. Version: 19.0.2.0.3.

## Replacement

- The installed prototype had three local staff-credit records and no installed dependent modules.
- Used Odoo's module lifecycle to uninstall that module before installing the replacement. No manual SQL cleanup was used.
- Accounting entry count was 1,599 immediately before and after uninstall. The three disposable module records were removed; journal entries were retained.
- Fresh installation and subsequent focused upgrades completed. The manifest no longer loads the old native report, PDF, importer, report assets or their menus.
- Exactly one module menu is defined: Other Reports > Staff Credit Report, opening tha.staff.credit list/form.

## Automated checks

- Python AST syntax, manifest data-file existence and XML parsing passed using container Python.
- Full focused final run: **16 tests, 0 failures, 0 errors**. Odoo statistics include two setup phases and therefore show 18 total phases.
- Command:

```powershell
docker exec odoo_19 odoo -d THA -u tha_vhg_staff_credit_report --stop-after-init --http-port=8079 --gevent-port=8089 --max-cron-threads=0 --test-enable --test-tags /tha_vhg_staff_credit_report --logfile=/var/log/odoo/staff_credit_rebuild_final.log
```

- Covered customer invoice and journal-item linking, split source limits, company and foreign-currency rejection, reader/manager access, staff/month grouping, duplicate requests, database uniqueness, draft deletion/regeneration, installment protection, posting, exact standard reversals, historical cutoff, manual settlements, reserved capacity, prevention of generated-credit double counting, installment rounding/skips, report filters and the single menu.
- The duplicate-batch test intentionally triggers and catches a database uniqueness error. Expected access-denied messages also occur in permission tests; neither is a final test failure.
- Earlier test runs exposed test-helper issues (missing manager role, duplicate keyword defaults, and Odoo's unsupported tuple exception assertion). These were corrected. Final results above supersede those runs.
- git diff --check passed after removing trailing blank lines.

## Excel and runtime

- Generated a synthetic two-row XLSX through the module's actual export method without creating database records.
- Imported and rendered it with the bundled artifact-tool runtime. Visually inspected all 14 columns, blue headers, month labels, typed dates, money, references and totals. The XLSX regression test also checks frozen panes and that formula-like description text remains literal text.
- Restarted odoo_19 and inspected the project's logs/server.log. Existing unrelated module manifest warnings remain.
- Browser validation used the user's existing signed-in Chrome Vendor Payments tab after their correction. Its pre-refresh cached menu still showed the prototype entries. Chrome then reported a detached debugger, preventing final visual verification. No new login was attempted after the user requested the existing session.
- No production deployment, historical import, company settings, original bills or real deduction entries were created. Settings must be completed for the target company before registering bills or generating deductions.
- Duplicate generation is protected by a unique staff/month constraint and serialized company configuration writes. A simultaneous multi-client load test was not performed.

Post-restart server verification: installed version 19.0.2.0.3; 1,599 accounting entries; zero new staff bills and deduction batches; one Staff Credit Report menu under Accounting/Reporting/Other Reports; administrator list, bill form, settings form and operation form compiled successfully; obsolete report/import/handler models absent.

## Opening error correction — 2026-10-30

The user reported `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'` when opening Staff Credit Report. The server runs `--dev=xml`; its file view loader concatenates `field_arch.text` with child XML. Inline `<field name="arch" type="xml"><search>` (also the settings and operation forms) supplied no text node. Added a newline before each architecture root without changing core Odoo. Added a regression covering all five source views through `get_view_arch_from_file` and list/form/search compilation.

The actual report and Excel dialog were verified in the user's existing signed-in Chrome tab without another login. The Settings button exposed a separate RPC argument mismatch: `@api.model` incorrectly retained the selected-record argument. Made it a normal recordset button method and added a `call_kw` regression for no selection and reader denial. Version bumped to 19.0.2.0.5.

## Selected-bill deduction workflow — 2026-10-30

User refinement: deduction generation belongs on each staff-credit form and must also work from multiple selected list rows. The list button now requires a selection. The wizard receives those active bill IDs, displays them, derives their company, and refuses unselected or cross-company generation. It no longer expands a selection to every other bill for that employee. Grouping remains one entry per staff/month; additional selected bills append to an existing draft atomically with the matching salary debit, while posted/cancelled batches refuse new bills. Each batch retains its chosen installments for posting validation. Version 19.0.2.0.6.

Added regressions for selected-only form/list defaults, hidden list action without selection, incremental staff draft merging without duplicates, posting a selected subset, no-selection refusal, and refusal to append bills after posting.

Final version 19.0.2.0.6 validation: Python syntax, manifest and all five XML source loader checks passed. Local THA upgrade succeeded and **21 tests passed, 0 failures, 0 errors** (`logs/staff_credit_selected_bills.log`; Odoo statistics include two additional setup phases). This supersedes the earlier 16/18-test results. Settings RPC and all selected-bill workflow regressions passed.

Post-update runtime: odoo_19 restarted successfully and logs/server.log shows the THA registry loaded. Report and Export Excel dialog opening were confirmed in the user's existing Chrome session after the XML correction. The final post-restart browser refresh timed out in Chrome's focus/snapshot command; no further login or test data entry was attempted. Settings and selected-form/list behavior are covered by the passing RPC/ORM and XML regressions. No production changes were made.

## Browser demo selection handoff — 2026-10-30

While creating demo bill SC/5/000142 through the user's existing Chrome session, the deduction wizard displayed the selected bill but dropped its readonly many-to-many value during create. Added force_save to that field and made default_get honor default_mode from context when mode is already explicitly supplied by the web client. Added a regression using the browser-equivalent create payload. Version 19.0.2.0.7. The demo bill links existing posted source SCDMO/26-27/10/0002 (SC-DEMO-MEALS), for 250,000 MMK, five 50,000 MMK installments from October 2026 through February 2027. Hospital settings use 130100, 701010 and STAFF CREDIT DEMO ONLY. No new original bill was posted.

Selection handoff fix validation: Python syntax, manifest consistency, and XML-development loader checks passed. Local THA upgrade to 19.0.2.0.7 succeeded; **22 tests passed, 0 failures, 0 errors** (`logs/staff_credit_browser_selection_fix.log`). Odoo restarted after validation. The browser-equivalent transient create payload is now covered explicitly.

Browser completion verified in the existing signed-in Chrome tab: demo bill SC/5/000142 (`/odoo/staff-credit-report/142`) has five 50,000 MMK installments. Generated October 31, 2026 draft account.move 4909, reference `Staff Credit - DEMO Staff Credit Employee - 2026-10`, in STAFF CREDIT DEMO ONLY: Dr 701010 Salary & wages 50,000 MMK / Cr 130100 Receivable-Internal Under HOD 50,000 MMK with the demo employee partner and bill reference. Verified Draft status and matching debit/credit totals visually; left unposted. All demo creation and settings changes were performed through browser UI. The real browser retry confirmed that the selected bill now survives wizard creation. Screenshots retained under ignored artifacts/.
# User refinements — 2026-10-30

Bill-form Excel export now pre-fills employee, department and category from the active bill. List Settings remains the company-default editor. Form Settings opens a bill-scoped override with an explicit Save as company default checkbox; deduction generation uses the chosen values for the current bill without saving defaults unless selected. Excel uses the supplied two-level header layout and a differently colored green total row. Version 19.0.2.0.8.

Local upgrade attempt for 19.0.2.0.8 started but stalled during the Odoo module-list scan after unrelated addon manifest warnings; it was interrupted before this module began loading. No module upgrade or database changes were confirmed. Static Python/XML/manifest checks passed. Runtime upgrade, service restart, and browser verification remain pending.

## Bulk Excel import and Staff Credit lifecycle — 2026-11-11

Updated the addon to 19.0.2.0.26. Added a blank import template download and manager-only `.xlsx` import for backdated Staff Credit rows; imported rows create pending bills with linked draft customer invoices using company settings. Added cancellation reset-to-draft and deletion support for cancelled entries. The regression imports an XLSX row, checks the blank template headers, verifies the generated invoice accounts/date, resets a cancelled invoice to draft, deletes a cancelled bill, and exercises report export.

Validation: Python compileall, XML parsing, `git diff --check`, and THA module upgrade with the complete addon suite passed (**38 tests, 0 failures, 0 errors**). Local report export completed and served `staff_credit_all_months.xlsx` with HTTP 200. Restarted `odoo_19` after upgrade.

Local browser demo: Shop Sphere staff credit `SC/4/000007`, Hsu Thawda Cho, 150,000 MMK, charged 2026-11-11, outpatient consultation and prescribed medicines. Invoice `INV/2026/11/11/0001` posted with Dr 130100 / Cr 510585. Two installments of 75,000 MMK; November deduction `STCR/2026/11/0001` posted, leaving 75,000 MMK settled and 75,000 MMK open. Deleted cancelled test entry `SC/4/000005` through the local Odoo interface. This is local THA demo data, not production.

## Native Odoo list import — 2026-11-11

Per the user's clarification, the custom upload wizard and template button were removed. The Staff Credit list now enables Odoo's native Import action (`import="1"`). Odoo's model importer can create backdated pending records from standard fields; each imported bill can then use the existing **Create Draft Invoice** action and normal Accounting posting. The Excel report exporter remains a separate feature.

Validation on version 19.0.2.0.28: Python compileall, XML parsing, `git diff --check`, module upgrade on THA, and the full addon suite passed (**38 tests, 0 failures, 0 errors**). A regression exercises Odoo's native model `load()` path with a backdated row, verifies the list import setting, then creates a linked invoice draft with the configured accounts. Odoo restarted after upgrade.
