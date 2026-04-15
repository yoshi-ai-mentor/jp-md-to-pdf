# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please **do not open a public issue**.

Instead, report it by:
- Opening a [GitHub Security Advisory](https://github.com/yoshi-ai-mentor/jp-md-to-pdf/security/advisories/new)
- Or contacting the maintainer directly via GitHub

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact

The maintainer will respond as soon as possible and coordinate a fix before public disclosure.

## Scope

This tool is designed for **trusted local use only**. It is not intended to be deployed as a web service or used to process untrusted input in an automated pipeline.

Known intentional behaviors:
- `--allow-http` enables external URL fetching; private/localhost ranges are blocked by default
- `--allow-local` enables local file access scoped to the input directory
- Raw HTML in Markdown is escaped by default
