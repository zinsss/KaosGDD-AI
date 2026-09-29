# KaosGDD 80 mm thermal print connector

This is the narrow hardware boundary for receipt printing. Governor renders a
validated 80 mm PDF, authenticates with a destination-specific bearer token,
and sends it here. The connector accepts only PDF pages no wider than 82 mm and
submits them to one named CUPS queue. It does not receive calendar, task, or
Memos credentials.

The same image is used for both destinations:

- H4: `Home`
- a future office host: `Office`

Each installation must use a different token. Governor selects the URL and
token by destination; the browser never receives either one.

## Start before the printer exists

```bash
./deploy/thermal-print-connector/kaos-thermal-print setup
./deploy/thermal-print-connector/kaos-thermal-print test
./deploy/thermal-print-connector/kaos-thermal-print up
```

Leave `THERMAL_CONNECTOR_MODE=dry-run`. Health will explicitly report
`awaiting_printer`, and print submission remains disabled. The PWA's 80 mm PDF
preview still works through Governor, so layout can be tested without wasting
paper.

## Enable the H4 printer later

1. Install and verify the printer as a host CUPS queue.
2. Set `THERMAL_CONNECTOR_MODE=cups` and `THERMAL_CONNECTOR_PRINTER=<queue>`.
3. Set `CUPS_SERVER=127.0.0.1:631`; the container uses host networking but
   remains a non-root, read-only process.
4. Bind `THERMAL_CONNECTOR_HOST` to H4's Tailscale address.
5. Copy the connector token securely to H3's
   `deploy/h3-backend/secrets/thermal_print_home_token` and configure
   `THERMAL_PRINT_HOME_URL=http://<h4-tailscale-ip>:8100`.
6. Run `preflight`, then `restart`.

For an office printer, repeat the deployment there with a fresh token and set
H3's `THERMAL_PRINT_OFFICE_URL` and `thermal_print_office_token` instead.

The connector stores only bounded job IDs, CUPS IDs, status, and timestamps for
idempotency. Receipt PDFs and their contents are held only in a temporary
directory during `lp` submission and are not retained.
