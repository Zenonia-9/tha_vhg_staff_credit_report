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

## Native accounting report - 2026-10-20, version 19.0.1.1.2

Monthly Report now opens a native `account.report` client action, with the same accounting-report framework used by P&L and Balance Sheet. The charge register and existing transient export APIs remain intact. New report definition, handler and scoped OWL filter component provide the standard PDF/XLSX toolbar, month navigation, search, staff/department/category/status selectors, charge/source caret actions and company-wide GL reconciliation. Selecting an unconfigured company displays a clear notice. A complete calendar month is used, based on the selected end date, and only one company is reported at a time.

The native handler reuses the validated register calculations through an unsaved transient object. Native PDF export uses the native report template and renderer with A3 landscape paper and scoped fixed table widths, so all columns fit; other accounting reports are unaffected.

Checks completed:

- Python AST (14 files), XML (7 files), manifest data/assets paths, JavaScript `node --check`, and Git whitespace checks passed.
- Full focused suite: **18 tests, 0 failures, 0 errors**. This includes native values, historical cutoff, status/department/search filters, access checks, native menu action, drill-down, and both export formats.
- After the final PDF base-URL adjustment, the focused native PDF/XLSX regression passed again (1 test, 0 failures/errors). Odoo was upgraded and restarted.
- Authenticated native report requests as ordinary admin returned three demo rows; the Settled filter returned one row with Times `2/2`. Standard `/account_reports` PDF and XLSX downloads passed signature checks. Earlier transient endpoints still passed compatibility checks.
- Browser verification used the user's existing Chrome tab, originally `http://localhost:8019/odoo/action-1481?debug=1`, and left it on `/odoo/staff-credit-monthly?debug=1` in Thukhasaytanar. Verified the native toolbar/filter controls, the three charge rows and the Settled-only result, then restored All Statuses. Saved `artifacts/native_report_screen.png`. This resolves the earlier browser-verification gap for the new Monthly Report interface.
- Rendered the final native PDF with Poppler and visually inspected the A3 landscape page. All fourteen data columns plus the charge reference, all three examples, totals and GL reconciliation values fit without horizontal clipping.

The local demo now has **three charges**: existing partial-payment hospital bill (470,000), current-month meals charge (250,000), and a new fully settled hospital bill (120,000). The settled charge, key `SC-DEMO-SETTLED`, belongs to **DEMO Staff Credit Finance Employee / Finance**; two posted 60,000 installments in August and September clear it completely. Its debit and credits offset, so October's company-wide closing remains **513,333 MMK**, with zero GL difference, unlinked debits or unapplied credits. The seeder remains idempotent and restricted to THA.

Additional Git-ignored artifacts: `staff_credit_native_oct_2026.pdf`, `.xlsx`, `.png`, `native_validation.json`, `native_report_screen.png` and the updated `http_validation.json`. Test log: `logs/staff_credit_native_validation.log`.

Live rollout, historical data mapping and reporter acceptance remain outstanding. The wide screen table uses native horizontal scrolling; the GL reconciliation amount is its last column. The standard native unposted-entry banner may also appear for other draft accounting entries in the selected company; Staff Credit calculations continue to include posted linked entries only.
