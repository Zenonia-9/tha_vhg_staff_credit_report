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
