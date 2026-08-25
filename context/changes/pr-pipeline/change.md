---
change_id: pr-pipeline
title: Add pull request quality and AI review worker pipeline
status: implemented
created: 2026-08-25
updated: 2026-08-25
archived_at: null
---

## Notes

New GitHub Actions pipeline to run an AI PR review worker using the OpenRouter
API.
Pipeline should be triggered when pr is created.
Pipeline should run a review of submitted changes, prepare summary for human reviewer.
The worker is a one-shot Python program hosted by GitHub Actions, not an
autonomous agent framework or separately deployed service. It should review
code against good practices for code quality and security and publish an
advisory summary for a human reviewer.
