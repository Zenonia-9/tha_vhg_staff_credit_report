# Local validation — Staff Credit rebuild

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
