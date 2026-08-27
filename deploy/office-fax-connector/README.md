# Office Fax Connector and Bridge

This deployment owns the KaosGDD integration beside the existing office
HylaFAX installation. It does not install, reconfigure, restart, or migrate
HylaFAX or the physical modem.

## Components

- `kaos-office-fax-connector`: authenticated Tailscale HTTP boundary used by
  H3 Governor. It writes validated version-1 queue manifests and presents
  incoming/status information from read-only HylaFAX files.
- `kaosgdd-fax-bridge`: office-local queue consumer. It converts PDF to fax
  TIFF and calls `sendfax` against `127.0.0.1:4559`.

Both components share:

```text
/srv/kaos/data/kaosgdd/brain/fax-outgoing
```

Only the connector mounts `/var/spool/hylafax`, and that mount is read-only.
The bridge reaches hfaxd over host loopback and does not mount the spool.

## Deploy

```bash
cd /srv/projects/KaosGDD-AI
./deploy/office-fax-connector/kaos-office-fax setup
# Fill the generated .env and fax_connector_token.
./deploy/office-fax-connector/kaos-office-fax test
./deploy/office-fax-connector/kaos-office-fax up
```

`preflight` requires the existing queue, spool, conversion tools, connector
secret, readable `setup.cache`/`setup.modem` files in the HylaFAX spool, and a
reachable local scheduler. It does not send a fax.

## Verify without transmitting

```bash
./deploy/office-fax-connector/kaos-office-fax preflight
curl -H "Authorization: Bearer $(tr -d '\\r\\n' < deploy/office-fax-connector/secrets/fax_connector_token)" \
  http://<office-tailscale-ip>:8098/health
docker ps --filter name=kaos-office-fax-connector --filter name=kaosgdd-fax-bridge
faxstat -h localhost -s
```

Do not perform a live outbound test without confirming the exact destination
and document. Do not change `config.ttyACM0`, `hosts.hfaxd`, `faxrcvd`, USB
placement, or systemd units as part of an application deployment.

Use the address configured by `FAX_CONNECTOR_BIND_ADDRESS`. A connector bound
to the office Tailscale address is intentionally not reachable through
`127.0.0.1`.

HylaFAX conversion helpers read the physical spool paths below even when the
canonical generated files also exist under `/etc/hylafax`:

```text
/var/spool/hylafax/etc/setup.cache
/var/spool/hylafax/etc/setup.modem
```

If either spool file is missing, a submitted TIFF can fail before dialing with
`FATAL ERROR: ... setup.cache is missing`. Restore the spool copies from the
corresponding canonical `/etc/hylafax` files with mode `0444`, then rerun
`preflight`. This repair does not require a HylaFAX restart.

## Rollback

The previous bridge image is retained locally during the observation period.
If the new worker cannot start, stop only `kaosgdd-fax-bridge` and recreate the
previous image with the same queue mount and environment. Do not roll back or
restart HylaFAX for an application-only failure.
