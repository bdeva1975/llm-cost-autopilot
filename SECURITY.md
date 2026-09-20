# Security Policy

## Scope

This project runs entirely on **synthetic data**: no API keys, no credentials,
no network calls, no real usage data. The attack surface is accordingly small,
but issues are still taken seriously.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting
("Security" tab → "Report a vulnerability") on this repository.
Expect an acknowledgement within a week.

## Notes for deployers

- The Streamlit app has no authentication. If you host it publicly, put it
  behind your own auth layer.
- If you extend it with real provider integrations, keep credentials in
  environment variables or a secrets manager — never in the repository, and
  never in `.streamlit/secrets.toml` committed to git (it is gitignored here).
- Audit events and datasets may contain your own business metadata once you
  point the tool at real data; apply your data-retention rules accordingly.