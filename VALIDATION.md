# Local validation - 2026-10-20

Addon version: **19.0.1.0.4**. Database: **THA**. Company: **THUKHA SAYTANAR CO. Ltd (Victoria Hospital)**.

## Result

- Python AST syntax: 13 source/test/validation files passed.
- XML parsing: 5 files passed; manifest data paths checked.
- Installed, upgraded and restarted `odoo_19`; registry started successfully.
- Final focused Odoo suite: **13 tests, 0 failures, 0 errors**. Odoo's aggregate statistics also count setup/teardown, so its statistics line says 15; the actual test result line says 13.
- Authenticated HTTP validation as normal **admin, user ID 2**, passed after restart: register/report/import forms loaded, monthly preview populated, Excel download opened as a valid XLSX with verified reference amounts, and the PDF endpoint returned a valid PDF.
- Generated October 2026 PDF rendered with Poppler and was visually inspected: one A3 landscape page, readable wrapped descriptions, no header overlap, correct reference amounts and totals. The report uses its own heading rather than the company's inherited letterhead.
- Generated XLSX contains Staff Credit, Movements and GL Reconciliation sheets. XML-level checks verified the numeric charge/balance cells. It was not visually opened in Microsoft Excel.

Evidence logs at project root:

- `logs/staff_credit_validation.log`: final suite result `0 failed, 0 error(s) of 13 tests`.
- `logs/staff_credit_demo.log`: demo rendering.
- `logs/server.log`: restarted runtime, successful authenticated report calls and downloads. Existing warnings about unrelated addons' metadata remain outside this addon.

## Functional cases exercised

Reference arithmetic and prior-month paid count; future-payment historical cutoff; split debit and credit sources; allocation caps; partial payments; skipped months; protected settled installments; charge reversals; source-edit guards; unchanged accounting after reporting; rounding; company isolation; reader write denial; outsider and attachment access denial; reconciled suggestions requiring confirmation; refusing suggestions for partially registered debits; company-configuration protection; atomic CSV preview/import and duplicate keys; XLSX cells and actual PDF rendering; form/list/search view loading as normal admin in XML development mode.

## Persistent local demo

Created only in THA, with journal **SCDMO / STAFF CREDIT DEMO ONLY**, department **DEMO Staff Credit Transport**, employee **DEMO Staff Credit Employee**, and contact reference **SC-DEMO-STAFF**. The two charge import keys are **SC-DEMO-HOSPITAL** and **SC-DEMO-MEALS**. All descriptions and remarks identify test data. The script is idempotent and is not loaded during addon installation or upgrade.

| October 2026 company/account total | Amount (MMK) |
| --- | ---: |
| Opening | 313,333 |
| New charges | 250,000 |
| Monthly reductions | 50,000 |
| Closing | 513,333 |
| Posted GL balance on 130100 | 513,333 |
| GL difference | 0 |
| Unlinked debits | 0 |
| Unapplied credits | 0 |

Hospital example: charge **470,000**, settlements through September **156,667**, balance before October deductions **313,333**, October planned **156,667**, Times **1/3**. The October actual partial payment is **50,000**, so this charge's month-end balance is **263,333**. A separate current-month meals charge contributes **250,000** to closing.

Local generated artifacts, deliberately Git-ignored under `artifacts/`:

- `staff_credit_oct_2026.xlsx`
- `staff_credit_oct_2026.pdf`
- `staff_credit_oct_2026.png` (visual review)
- `demo_validation.json`
- `http_validation.json`

To inspect in Odoo: select the hospital company, then **Accounting > Staff Credit > Monthly Report**, choose **2026-10-01**, and refresh. The register retains the two demo charges for review.

## Remaining verification

The browser-control connection timed out (`Emulation.setFocusEmulationEnabled` and `Page.navigate`). No approval was denied or bypassed. Authenticated HTTP/form/download checks succeeded, but browser clicks and client-side rendering were not verified. Multi-process allocation contention was not stress-tested; allocations serialize through configuration metadata to make competing database snapshots retry without modifying accounting balances.

No live deployment or live historical import was performed. Live acceptance still needs the hospital workbook, staff-to-partner mapping, approved schedules, target GL detail and reporter confirmation. Company-currency-only source items are supported in v1. Preserve approved exports because historical metadata edits are audited, not immutable month-close snapshots.

## Menu correction - 2026-10-20, version 19.0.1.0.5

Investigation confirmed the Fixed Asset Register addon was uninstalled in THA. Staff Credit was installed and visible to admin, but belonged to the Invoicing app (`account.menu_finance`), while the shared Other Reports menu belongs to the Accounting app. Restored the existing Fixed Asset Register addon without modifying its source. Moved the Staff Credit parent to `tha_vhg_daily_cash_register.menu_other_reports` and declared that shared-menu addon as a dependency.

Python/XML/manifest checks and the focused menu-visibility regression test passed (1 test, 0 failures/errors). After restart, authenticated `ir.ui.menu.load_menus` as admin verified these complete visible paths:

- **Accounting > Reporting > Other Reports > Fixed Asset Register** (installed version 19.0.1.0.15).
- **Accounting > Reporting > Other Reports > Staff Credit > Monthly Report** (installed version 19.0.1.0.5).

Staff Credit Register, Import and Accounts remain under the same Staff Credit parent with their existing access restrictions. Refresh an already-open browser session to load the updated menu tree. Validation log: `logs/staff_credit_menu_validation.log`.
