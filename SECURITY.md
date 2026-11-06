# Security Policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

Use GitHub's private reporting: **Security → Report a vulnerability** on this repository
(https://github.com/MilkteaTW1/screen-translator/security/advisories/new).

Include what you found, how to reproduce it, and the version. I aim to reply within 7 days.

## Good to know

- Text read from the screen is sent to Google (or to DeepL, Gemini or your own server) only when you leave that engine on; turn it off to stay offline.
- API keys you enter are saved in `settings.json` as plain text. Do not share that file.
