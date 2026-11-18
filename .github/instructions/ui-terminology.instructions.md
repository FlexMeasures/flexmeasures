---
applyTo: "flexmeasures/ui/**"
---
# UI Terminology

Use **"organisation"** (not "account") in all user-visible text. The word "account" is too easily confused with a user login account.

## The rule

| Context | ✅ Use | ❌ Avoid |
|---------|--------|---------|
| Button labels | "Copy to my organisation" | "Copy to my account" |
| Tooltips | "contact your organisation admin" | "contact your account admin" |
| Flash messages | "Organisation not found" | "Account not found" |
| Template strings | "Select organisation" | "Select account" |
| Error messages shown to users | "You must be an organisation admin" | "You must be an account-admin" |

## What stays unchanged

The Python backend model is still named `Account`. Database columns, Python identifiers, URLs, and API field names all stay as-is. Only the text **shown to end users** changes.

## Internal role names

Never expose internal role names (e.g. `account-admin`, `admin`) in UI text. Use plain language instead:

- ✅ "organisation admin"
- ❌ "account-admin"
- ❌ "ACCOUNT_ADMIN"

## Jinja2 template safety

- Sensor/asset IDs embedded in JavaScript use `{{ sensor.id }}` (integer — safe), not `.name` or freeform text.
- User-supplied values displayed in HTML rely on Jinja's auto-escaping (`{{ value }}`); do not mark them `| safe`.
- Data embedded in a `<script>` uses `{{ value | tojson }}`, which yields valid JavaScript and cannot close the script element.
  Never render a Python dict or list with `| safe` there, nor place either inside a JavaScript string literal.
- In JavaScript, set user-supplied text with `textContent`, or pass it through `escapeHtml` (from `ui-utils.js`) when building markup for `innerHTML`.

## Toast vs. inline alert

| Use case | Pattern |
|----------|---------|
| Action result (save, delete, copy) | `showToast("...", "success"/"error")` |
| Background job progress | `showToast("...", "info")` |
| Persistent field description users need while interacting | `<div class="alert alert-info">` |

Do not migrate inline `alert-info` divs showing persistent information to toasts — they could disappear before the user reads them.
