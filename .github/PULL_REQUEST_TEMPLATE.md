<!-- Delete any sections that don't apply. -->

## What does this change?

<!-- One or two sentences. -->

## Why?

<!-- Link to an issue / discussion, describe the bug / use case, or note the audit doc this addresses. -->

## How was this tested?

- [ ] `uv run pytest` passes locally
- [ ] Installed on a live HA and verified the feature manually
- [ ] Screenshots attached (if UI-facing)

## Checklist

- [ ] Relevant `translations/*.json` entries updated (if new entity / string was added)
- [ ] Entity description `translation_key` set (if new entity was added)
- [ ] `strings.json` matches `translations/en.json`
- [ ] Services added with `selector: device: integration: petlibro_lite` (no raw text)
- [ ] New platform file added to the correct `async_setup_entry`
- [ ] Service handler validates input via voluptuous schema
