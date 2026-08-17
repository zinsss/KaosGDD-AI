# H3 Service Migration Prep

This note records the non-cutover prep for moving service-native backends from
`kaosclinic` to `kaosgdd`. It does not approve stopping source services or
switching routes by itself.

## Source Inventory

Observed source host: `kaosclinic` at Tailscale `100.94.208.16`.

Move candidates:

| Service | Source image ID | Source data/config |
| --- | --- | --- |
| Radicale | `sha256:ff012f461abd60a439eeee983c4b3de73ca477e6045c439a95e0e1bd81e3482e` | `/srv/kaos/config/radicale`, `/srv/kaos/data/radicale` |
| Memos | `sha256:3e1253477066eb2aefa91145f7f9038bb931ed88c8a3ee05310a933594cdba7d` | `/srv/kaos/data/memos` |
| Vaultwarden | `sha256:ebdfe70701c60ac0c28c697e787cea767d7972940b786037b29fe0d507f821e8` | `/srv/kaos/data/vaultwarden`, `/srv/kaos/secrets/vaultwarden.env` |
| SFTPGo | `sha256:9011fe608d336d3daf6ed6224b16fd40443aab8f3335e0b20853d6a539c58738` | `/srv/kaos/data/sftpgo` |
| Caddy | `sha256:844f60b64e4724a5aa8245e019dace0d3f199f7433ce6c57676cb30a920dbad9` | `/srv/kaos/config/Caddyfile`, `/srv/kaos/data/caddy` |
| cloudflared | `sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf` | `/srv/kaos/secrets/cloudflared.env` |
| Family portal | `sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10` | `/srv/kaos/config/kaosgdd/portal`, `/srv/kaos/data/kaosgdd/portal` |

Transitional family components, only if still required:

| Service | Source image ID | Source data/config |
| --- | --- | --- |
| `kaosgovernor-legacy-api` from legacy brain | `sha256:fbfc2ed5b6ef35b9b26cb8dc6f9fed05d38f7f2209c7c078746dfeeba975f269` | `/srv/kaos/data/kaosgdd/brain`, `/srv/kaos/secrets/kaosgdd-brain.env` |
| `kaosgovernor-legacy-database` | `sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb` | `/srv/kaos/data/kaosgdd/brain/postgres` |
| `calendar-adapter` | `sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df` | `/srv/kaos/data/kaosgdd/calendar-adapter`, `/srv/kaos/secrets/kaosgdd-adapters.env` |
| Family Memos web | `sha256:421e98ec721040392bb0561b75f424a5ffbdd828607acfab6b8b667136df3062` | image must be exported/imported if retained during transition |

Approximate source data sizes at inventory time:

| Path | Size |
| --- | ---: |
| `/srv/kaos/config/radicale` | 12K |
| `/srv/kaos/data/radicale` | 7.9M |
| `/srv/kaos/data/memos` | 488K |
| `/srv/kaos/data/vaultwarden` | 1.5M |
| `/srv/kaos/data/sftpgo` | 396K |
| `/srv/kaos/data/caddy` | 40K |
| `/srv/kaos/data/kaosgdd/portal` | 37M |
| `/srv/kaos/data/kaosgdd/brain` | 55M |
| `/srv/kaos/data/kaosgdd/calendar-adapter` | 88K |

Do not move PACS, Orthanc/DICOM, HylaFAX, Paperless, Stirling-PDF, RustDesk, or
KaosTelegram as part of this service migration.

## Destination Layout

Ready-made services keep native operational names. Stage data under:

```text
/srv/kaos/config/radicale
/srv/kaos/data/radicale
/srv/kaos/data/memos
/srv/kaos/data/vaultwarden
/srv/kaos/data/sftpgo
/srv/kaos/config/Caddyfile
/srv/kaos/data/caddy
/srv/kaos/secrets/vaultwarden.env
/srv/kaos/secrets/cloudflared.env
/srv/kaos/config/family-portal
/srv/kaos/data/family-portal
```

If transitional family APIs are still required, keep their legacy data and
secret paths until the old service is fully retired:

```text
/srv/kaos/data/kaosgdd-gov
/srv/kaos/secrets/kaosgdd-gov.env
/srv/kaos/secrets/kaosgdd-adapters.env
/srv/kaos/data/calendar-adapter
```

## Guarded Commands

The H3 deployment now includes:

```bash
./deploy/h3-backend/kaos-h3 services-preflight
./deploy/h3-backend/kaos-h3 services-up
./deploy/h3-backend/kaos-h3 family-preflight
./deploy/h3-backend/kaos-h3 family-up
./deploy/h3-backend/kaos-h3 edge-preflight
./deploy/h3-backend/kaos-h3 edge-up
```

These commands are intended for after staging data and secrets. They are not a
substitute for the final write-freeze, checksum comparison, service validation,
and one-hostname-at-a-time route switch.
